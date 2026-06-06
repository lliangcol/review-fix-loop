from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

from .diagnostics import (
    normalize_diagnostic,
    parse_checkstyle,
    parse_git_diff_check,
    parse_json_diagnostics,
    parse_rdjson,
    parse_regex_lines,
    parse_sarif,
    severity_at_least,
)
from .errors import ConfigError, WorkflowError
from .run_record import read_json, write_json
from .utils import matches_any, normalize_repo_path, redact_data, redact_text, truncate_text


def changed_paths_for_scope(entries_by_scope: dict[str, list[dict[str, Any]]], scope: str) -> list[str]:
    if scope == "all":
        entries = [entry for scope_entries in entries_by_scope.values() for entry in scope_entries]
    else:
        entries = entries_by_scope.get(scope, [])
    result = []
    for entry in entries:
        path = entry.get("path")
        if path and path not in result:
            result.append(path)
    return result


def entries_for_scope(entries_by_scope: dict[str, list[dict[str, Any]]], scope: str) -> list[dict[str, Any]]:
    if scope == "all":
        return [entry for scope_entries in entries_by_scope.values() for entry in scope_entries]
    return list(entries_by_scope.get(scope, []))


def plan_gates(config: dict[str, Any], mode: str, entries_by_scope: dict[str, list[dict[str, Any]]], final_pass: bool) -> list[str]:
    planned: list[str] = []
    for gate in config.get("gates", []):
        gate_id = gate["id"]
        modes = gate.get("modes")
        if modes and mode not in modes:
            continue
        paths = changed_paths_for_scope(entries_by_scope, gate["scope"])
        when_paths = gate.get("when_paths")
        selected = bool(paths)
        if when_paths is not None:
            selected = any(matches_any(path, when_paths) for path in paths)
        if final_pass and gate.get("final_always"):
            selected = True
        if selected and gate_id not in planned:
            planned.append(gate_id)
    return planned


def expand_argv(argv: list[str], snapshot: dict[str, Any]) -> list[str]:
    # Avoid str.format so gate commands can contain JSON or Python literal braces.
    replacements = {
        "{baseline}": snapshot.get("baseline") or "",
        "{merge_base}": snapshot.get("merge_base") or "",
        "{snapshot_id}": snapshot.get("snapshot_id") or "",
    }
    expanded = []
    for arg in argv:
        value = arg
        for token, replacement in replacements.items():
            value = value.replace(token, replacement)
        expanded.append(value)
    return expanded


def safe_snapshot_path(repo: Path, path: str) -> Path:
    candidate = (repo / path).resolve()
    try:
        candidate.relative_to(repo.resolve())
    except ValueError as exc:
        raise WorkflowError(f"snapshot path escapes repo: {path}") from exc
    return candidate


def run_untracked_whitespace_builtin(repo: Path, snapshot: dict[str, Any]) -> tuple[int, str, str]:
    diagnostics = []
    for entry in snapshot.get("entries", {}).get("untracked", []):
        if entry.get("deleted") or entry.get("binary"):
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            continue
        file_path = safe_snapshot_path(repo, path)
        if not file_path.exists() or not file_path.is_file():
            continue
        with file_path.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.rstrip(b"\r\n")
                if line.endswith((b" ", b"\t")):
                    diagnostics.append(f"{path}:{line_number}: trailing whitespace.")
    return (1 if diagnostics else 0, "\n".join(diagnostics), "")


def run_policy_builtin(gate: dict[str, Any], snapshot: dict[str, Any]) -> tuple[int, str, str]:
    policy = gate.get("policy", {})
    if not isinstance(policy, dict):
        return -2, "", "__builtin__:policy requires a policy object"
    paths = changed_paths_for_scope(snapshot.get("entries", {}), gate.get("scope", "all"))
    diagnostics = []
    for pattern in policy.get("require_changed_paths", []):
        if not any(matches_any(path, [pattern]) for path in paths):
            diagnostics.append({
                "tool": gate["id"],
                "severity": "error",
                "rule": "require_changed_paths",
                "message": f"No changed path matched required policy pattern: {pattern}",
                "scope": gate.get("scope", "all"),
                "blocking": bool(gate.get("blocking", True)),
            })
    for pattern in policy.get("forbid_changed_paths", []):
        for path in paths:
            if matches_any(path, [pattern]):
                diagnostics.append({
                    "tool": gate["id"],
                    "severity": "error",
                    "rule": "forbid_changed_paths",
                    "file": path,
                    "message": f"Changed path matched forbidden policy pattern: {pattern}",
                    "scope": gate.get("scope", "all"),
                    "blocking": bool(gate.get("blocking", True)),
                })
    if policy.get("require_final_pass") and not snapshot.get("final_pass"):
        diagnostics.append({
            "tool": gate["id"],
            "severity": "error",
            "rule": "require_final_pass",
            "message": "Policy requires a snapshot created with --final-pass",
            "scope": gate.get("scope", "all"),
            "blocking": bool(gate.get("blocking", True)),
        })
    output = {"diagnostics": diagnostics}
    import json
    return (1 if diagnostics else 0, json.dumps(output, ensure_ascii=False), "")


def run_builtin_gate(repo: Path, gate: dict[str, Any], snapshot: dict[str, Any], argv: list[str]) -> tuple[int, str, str] | None:
    if not argv:
        return None
    command = argv[0]
    if command == "__builtin__:untracked-whitespace":
        if gate.get("scope") != "untracked":
            return -2, "", "__builtin__:untracked-whitespace requires scope=untracked"
        return run_untracked_whitespace_builtin(repo, snapshot)
    if command == "__builtin__:policy":
        return run_policy_builtin(gate, snapshot)
    return None


def parse_gate_output(gate: dict[str, Any], stdout: str, stderr: str, exit_code: int) -> list[dict[str, Any]]:
    parser = gate.get("parser", {"type": "exit-code"})
    parser_type = parser.get("type", "exit-code")
    scope = gate["scope"]
    blocking = bool(gate.get("blocking", True))
    gate_id = gate["id"]
    combined = stdout + ("\n" if stdout and stderr else "") + stderr
    if parser_type == "exit-code":
        if exit_code == 0:
            return []
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="exit-code",
            message=f"Gate {gate_id} exited with code {exit_code}",
            scope=scope,
            blocking=blocking,
        )]
    if parser_type == "git-diff-check":
        return parse_git_diff_check(combined, gate_id, scope, blocking)
    if parser_type == "regex-lines":
        return parse_regex_lines(combined, parser, gate_id, scope, blocking)
    if parser_type == "json-diagnostics":
        return parse_json_diagnostics(stdout or stderr, gate_id, scope, blocking)
    if parser_type == "rdjson":
        return parse_rdjson(stdout or stderr, gate_id, scope, blocking)
    if parser_type == "sarif":
        return parse_sarif(stdout or stderr, gate_id, scope, blocking)
    if parser_type == "checkstyle":
        return parse_checkstyle(stdout or stderr, gate_id, scope, blocking)
    raise ConfigError(f"unsupported parser type: {parser_type}")


def line_in_ranges(line: int | None, ranges: list[list[int]]) -> bool:
    if line is None:
        return False
    return any(start <= line <= end for start, end in ranges)


def path_matches_entry(path: str, entry: dict[str, Any]) -> bool:
    normalized = normalize_repo_path(path)
    return normalized == normalize_repo_path(entry.get("path", ""))


def diagnostic_matches_filter(diagnostic: dict[str, Any], entries: list[dict[str, Any]], filter_mode: str) -> bool:
    file_name = diagnostic.get("file")
    if filter_mode == "nofilter" or not file_name:
        return True
    matching_entries = [entry for entry in entries if path_matches_entry(file_name, entry)]
    if not matching_entries:
        return False
    if filter_mode == "file":
        return True
    line = diagnostic.get("line")
    if not isinstance(line, int):
        return True
    key = "changed_lines" if filter_mode == "added" else "diff_context_lines"
    return any(line_in_ranges(line, entry.get(key, [])) for entry in matching_entries)


def filter_diagnostics(gate: dict[str, Any], snapshot: dict[str, Any], diagnostics: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    filter_mode = gate.get("filter_mode", "nofilter")
    if filter_mode == "nofilter":
        return diagnostics, 0
    entries = entries_for_scope(snapshot.get("entries", {}), gate["scope"])
    kept = [diagnostic for diagnostic in diagnostics if diagnostic_matches_filter(diagnostic, entries, filter_mode)]
    return kept, len(diagnostics) - len(kept)


def resolve_record_update_path(snapshot: dict[str, Any], snapshot_path: Path) -> Path:
    run_record_path = snapshot.get("run_record_path")
    if not run_record_path:
        return snapshot_path.parent / "run-record.json"
    path = Path(run_record_path).resolve()
    snapshot_dir = snapshot_path.resolve().parent
    try:
        path.parent.relative_to(snapshot_dir)
    except ValueError as exc:
        raise WorkflowError("run_record_path must stay under the snapshot directory") from exc
    return path


def run_planned_gates(repo: Path, config: dict[str, Any], snapshot: dict[str, Any], snapshot_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    gate_by_id = {gate["id"]: gate for gate in config.get("gates", [])}
    results = []
    diagnostics = []
    exit_status = 0
    for gate_id in snapshot.get("planned_gates", []):
        if gate_id not in gate_by_id:
            raise WorkflowError(f"planned gate is missing from current config: {gate_id}")
        gate = gate_by_id[gate_id]
        argv = expand_argv(gate["argv"], snapshot)
        start = time.monotonic()
        builtin_result = run_builtin_gate(repo, gate, snapshot, argv)
        if builtin_result is None:
            try:
                completed = subprocess.run(
                    argv,
                    cwd=str(repo),
                    shell=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=gate.get("timeout_seconds", 60),
                )
                exit_code = completed.returncode
                stdout = completed.stdout.decode("utf-8", "replace")
                stderr = completed.stderr.decode("utf-8", "replace")
            except OSError as exc:
                exit_code = -2
                stdout = ""
                stderr = f"Could not execute gate command: {exc}"
            except subprocess.TimeoutExpired as exc:
                exit_code = -1
                stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                stderr += f"\nGate timed out after {gate.get('timeout_seconds', 60)} seconds"
        else:
            exit_code, stdout, stderr = builtin_result
        duration_ms = int((time.monotonic() - start) * 1000)

        raw_gate_diagnostics = parse_gate_output(gate, stdout, stderr, exit_code)
        gate_diagnostics, filtered_count = filter_diagnostics(gate, snapshot, raw_gate_diagnostics)
        fail_level = gate.get("fail_level", "error")
        blocking = bool(gate.get("blocking", True))
        diag_blocks = any(
            bool(item.get("blocking", blocking)) and severity_at_least(item.get("severity", "none"), fail_level)
            for item in gate_diagnostics
        )
        parser_type = gate.get("parser", {"type": "exit-code"}).get("type", "exit-code")
        command_failed = exit_code != 0 and fail_level != "none" and (parser_type == "exit-code" or not raw_gate_diagnostics)
        failed = blocking and (command_failed or diag_blocks)
        status = "failed" if failed else "passed"
        if failed:
            exit_status = 1
        result = redact_data({
            "id": gate_id,
            "argv": argv,
            "blocking": blocking,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "status": status,
            "diagnostics_count": len(gate_diagnostics),
            "filtered_diagnostics_count": filtered_count,
            "stdout_summary": truncate_text(redact_text(stdout)),
            "stderr_summary": truncate_text(redact_text(stderr)),
        })
        results.append(result)
        diagnostics.extend(redact_data(gate_diagnostics))

    path = resolve_record_update_path(snapshot, snapshot_path)
    if path.exists():
        record = read_json(path)
        record["gates"] = results
        record["diagnostics"] = diagnostics
        record["stop_decision"] = "continue" if exit_status else "stop"
        write_json(path, record)
    return results, diagnostics, exit_status
