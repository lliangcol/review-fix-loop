from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
# Gate commands run locally with shell=False and explicit argv.
import subprocess  # nosec B404
import time
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import IO

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
from .domain.types import GateCommandOutput, GateRunResult, JsonObject
from .errors import ConfigError, WorkflowError
from .run_record import update_run_record_after_gates
from .utils import matches_any, normalize_repo_path, redact_data, redact_text, truncate_text

# Canonical set of in-process gate commands. config.validate_config rejects any
# "__builtin__:" argv that is not listed here, so keep this the single source of
# truth for both validation and dispatch.
BUILTIN_GATE_COMMANDS = frozenset({"__builtin__:untracked-whitespace", "__builtin__:policy"})
BUILTIN_PREFIX = "__builtin__:"
MAX_GATE_CAPTURE_BYTES = 2 * 1024 * 1024

GateConfig = JsonObject
SnapshotData = JsonObject
Entry = JsonObject
Diagnostic = JsonObject
EntriesByScope = dict[str, list[Entry]]


def changed_paths_for_scope(entries_by_scope: EntriesByScope, scope: str) -> list[str]:
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


def entries_for_scope(entries_by_scope: EntriesByScope, scope: str) -> list[Entry]:
    if scope == "all":
        return [entry for scope_entries in entries_by_scope.values() for entry in scope_entries]
    return list(entries_by_scope.get(scope, []))


def plan_gates(config: JsonObject, mode: str, entries_by_scope: EntriesByScope, final_pass: bool) -> list[str]:
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


def expand_argv(argv: list[str], snapshot: SnapshotData) -> list[str]:
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


def run_untracked_whitespace_builtin(repo: Path, snapshot: SnapshotData) -> tuple[int, str, str]:
    diagnostics = []
    for entry in snapshot.get("entries", {}).get("untracked", []):
        if entry.get("deleted") or entry.get("binary") or entry.get("symlink"):
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


def run_policy_builtin(gate: GateConfig, snapshot: SnapshotData) -> tuple[int, str, str]:
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


def run_builtin_gate(repo: Path, gate: GateConfig, snapshot: SnapshotData, argv: list[str]) -> tuple[int, str, str] | None:
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


def read_captured_output(handle: IO[bytes], max_bytes: int = MAX_GATE_CAPTURE_BYTES) -> tuple[str, bool, int]:
    handle.flush()
    handle.seek(0, 2)
    total_bytes = handle.tell()
    handle.seek(0)
    raw = handle.read(max_bytes + 1)
    truncated = total_bytes > max_bytes
    text = raw[:max_bytes].decode("utf-8", "replace")
    return text, truncated, total_bytes


def run_external_gate(repo: Path, argv: list[str], timeout_seconds: int) -> GateCommandOutput:
    with SpooledTemporaryFile(max_size=MAX_GATE_CAPTURE_BYTES, mode="w+b") as stdout_file, \
         SpooledTemporaryFile(max_size=MAX_GATE_CAPTURE_BYTES, mode="w+b") as stderr_file:
        try:
            # Adapter argv is executed without shell expansion.
            completed = subprocess.run(  # nosec B603
                argv,
                cwd=str(repo),
                shell=False,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
        except OSError as exc:
            exit_code = -2
            stderr_file.write(f"Could not execute gate command: {exc}".encode("utf-8", "replace"))
        except subprocess.TimeoutExpired:
            exit_code = -1
            stderr_file.write(f"\nGate timed out after {timeout_seconds} seconds".encode("utf-8"))

        stdout, stdout_truncated, stdout_bytes = read_captured_output(stdout_file)
        stderr, stderr_truncated, stderr_bytes = read_captured_output(stderr_file)
        return GateCommandOutput(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            stdout_bytes=stdout_bytes,
            stderr_bytes=stderr_bytes,
        )


def parse_gate_output(gate: GateConfig, stdout: str, stderr: str, exit_code: int) -> list[Diagnostic]:
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


def path_matches_entry(path: str, entry: Entry) -> bool:
    normalized = normalize_repo_path(path)
    return normalized == normalize_repo_path(entry.get("path", ""))


def diagnostic_matches_filter(diagnostic: Diagnostic, entries: list[Entry], filter_mode: str) -> bool:
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


def filter_diagnostics(gate: GateConfig, snapshot: SnapshotData, diagnostics: list[Diagnostic]) -> tuple[list[Diagnostic], int]:
    filter_mode = gate.get("filter_mode", "nofilter")
    if filter_mode == "nofilter":
        return diagnostics, 0
    entries = entries_for_scope(snapshot.get("entries", {}), gate["scope"])
    kept = [diagnostic for diagnostic in diagnostics if diagnostic_matches_filter(diagnostic, entries, filter_mode)]
    return kept, len(diagnostics) - len(kept)


def slice_by_path_map(snapshot: SnapshotData) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for scope_entries in snapshot.get("entries", {}).values():
        if not isinstance(scope_entries, list):
            continue
        for entry in scope_entries:
            path = entry.get("path")
            slice_id = entry.get("slice")
            if isinstance(path, str) and path and isinstance(slice_id, str):
                mapping.setdefault(normalize_repo_path(path), slice_id)
    return mapping


def attach_diagnostic_slices(diagnostics: list[Diagnostic], slice_by_path: dict[str, str]) -> None:
    for diagnostic in diagnostics:
        file_name = diagnostic.get("file")
        if diagnostic.get("slice") is None and isinstance(file_name, str) and file_name:
            diagnostic["slice"] = slice_by_path.get(normalize_repo_path(file_name))


def is_builtin_gate(gate: GateConfig, argv: list[str]) -> bool:
    return bool(argv) and argv[0] in BUILTIN_GATE_COMMANDS


def gate_trust_metadata(
    gate: GateConfig,
    argv: list[str],
    *,
    allow_untrusted_gates: bool,
    ci_mode: bool,
) -> JsonObject:
    builtin = is_builtin_gate(gate, argv)
    trusted = True if builtin else bool(gate.get("trusted", False))
    allow_in_ci = True if builtin else bool(gate.get("allow_in_ci", False))
    metadata: JsonObject = {
        "trusted": trusted,
        "allow_in_ci": allow_in_ci,
        "writes_worktree": bool(gate.get("writes_worktree", False)),
        "requires_network": bool(gate.get("requires_network", False)),
        "trust_reason": gate.get("trust_reason") or ("builtin gate" if builtin else ""),
    }
    if not builtin and not trusted and not allow_untrusted_gates:
        metadata["trust_warning"] = "external gate is untrusted; pass --allow-untrusted-gates to acknowledge local execution"
    if not builtin and ci_mode and (not trusted or not allow_in_ci):
        metadata["ci_refused"] = True
    return metadata


def run_configured_gate(
    repo: Path,
    gate: GateConfig,
    snapshot: SnapshotData,
    *,
    allow_untrusted_gates: bool,
    ci_mode: bool,
) -> GateRunResult:
    gate_id = gate["id"]
    argv = expand_argv(gate["argv"], snapshot)
    trust_metadata = gate_trust_metadata(
        gate,
        argv,
        allow_untrusted_gates=allow_untrusted_gates,
        ci_mode=ci_mode,
    )
    start = time.monotonic()
    stdout = ""
    stderr = ""
    stdout_bytes = 0
    stderr_bytes = 0
    stdout_truncated = False
    stderr_truncated = False
    trust_refused = bool(trust_metadata.get("ci_refused"))
    if trust_refused:
        exit_code = -3
        stderr = (
            f"External gate {gate_id} refused in CI mode; set trusted=true and "
            "allow_in_ci=true after reviewing the command"
        )
        stderr_bytes = len(stderr.encode("utf-8"))
    else:
        builtin_result = run_builtin_gate(repo, gate, snapshot, argv)
        if builtin_result is None:
            external_result = run_external_gate(repo, argv, gate.get("timeout_seconds", 60))
            exit_code = external_result.exit_code
            stdout = external_result.stdout
            stderr = external_result.stderr
            stdout_truncated = external_result.stdout_truncated
            stderr_truncated = external_result.stderr_truncated
            stdout_bytes = external_result.stdout_bytes
            stderr_bytes = external_result.stderr_bytes
        else:
            exit_code, stdout, stderr = builtin_result
            stdout_bytes = len(stdout.encode("utf-8"))
            stderr_bytes = len(stderr.encode("utf-8"))
    duration_ms = int((time.monotonic() - start) * 1000)

    if trust_refused:
        raw_gate_diagnostics = [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="untrusted-gate-refused",
            message=stderr,
            scope=gate["scope"],
            blocking=bool(gate.get("blocking", True)),
        )]
    else:
        raw_gate_diagnostics = parse_gate_output(gate, stdout, stderr, exit_code)
    parser_type = gate.get("parser", {"type": "exit-code"}).get("type", "exit-code")
    if parser_type != "exit-code" and (stdout_truncated or stderr_truncated):
        raw_gate_diagnostics.append(normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="output-truncated",
            message=(
                f"Gate output exceeded the {MAX_GATE_CAPTURE_BYTES} byte capture limit; "
                "diagnostics may be incomplete"
            ),
            scope=gate["scope"],
            blocking=bool(gate.get("blocking", True)),
        ))
    gate_diagnostics, filtered_count = filter_diagnostics(gate, snapshot, raw_gate_diagnostics)
    attach_diagnostic_slices(gate_diagnostics, slice_by_path_map(snapshot))
    fail_level = gate.get("fail_level", "error")
    blocking = bool(gate.get("blocking", True))
    diag_blocks = any(
        bool(item.get("blocking", blocking)) and severity_at_least(item.get("severity", "none"), fail_level)
        for item in gate_diagnostics
    )
    command_failed = exit_code != 0 and fail_level != "none" and (parser_type == "exit-code" or not raw_gate_diagnostics)
    failed = blocking and (command_failed or diag_blocks)
    status = "failed" if failed else "passed"
    result: JsonObject = redact_data({
        "id": gate_id,
        "argv": argv,
        "blocking": blocking,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "status": status,
        "diagnostics_count": len(gate_diagnostics),
        "filtered_diagnostics_count": filtered_count,
        "stdout_bytes": stdout_bytes,
        "stderr_bytes": stderr_bytes,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_summary": truncate_text(redact_text(stdout)),
        "stderr_summary": truncate_text(redact_text(stderr)),
        **trust_metadata,
    })
    diagnostics: list[JsonObject] = redact_data(gate_diagnostics)
    return GateRunResult(gate=result, diagnostics=diagnostics, failed=1 if failed else 0)


def gate_dependencies(gate: GateConfig, planned_ids: set[str]) -> set[str]:
    return {gate_id for gate_id in gate.get("depends_on", []) if gate_id in planned_ids}


def next_ready_gate_group(
    planned_gate_ids: list[str],
    remaining: set[str],
    completed: set[str],
    gate_by_id: dict[str, GateConfig],
) -> list[str]:
    ready = [
        gate_id
        for gate_id in planned_gate_ids
        if gate_id in remaining and gate_dependencies(gate_by_id[gate_id], set(planned_gate_ids)) <= completed
    ]
    if not ready:
        raise WorkflowError("planned gates have a dependency cycle or unmet dependency")
    first = ready[0]
    if not bool(gate_by_id[first].get("parallel_safe", False)):
        return [first]
    group = []
    ready_set = set(ready)
    start_index = planned_gate_ids.index(first)
    for gate_id in planned_gate_ids[start_index:]:
        if gate_id not in remaining:
            continue
        if gate_id not in ready_set or not bool(gate_by_id[gate_id].get("parallel_safe", False)):
            break
        group.append(gate_id)
    return group or [first]


def run_planned_gates(
    repo: Path,
    config: JsonObject,
    snapshot: SnapshotData,
    snapshot_path: Path,
    *,
    allow_untrusted_gates: bool = False,
    ci_mode: bool = False,
) -> tuple[list[JsonObject], list[JsonObject], int]:
    gate_by_id = {gate["id"]: gate for gate in config.get("gates", [])}
    planned_gate_ids = list(snapshot.get("planned_gates", []))
    results_by_id: dict[str, JsonObject] = {}
    diagnostics_by_id: dict[str, list[JsonObject]] = {}
    exit_status = 0
    remaining = set(planned_gate_ids)
    completed: set[str] = set()

    for gate_id in planned_gate_ids:
        if gate_id not in gate_by_id:
            raise WorkflowError(f"planned gate is missing from current config: {gate_id}")

    while remaining:
        group = next_ready_gate_group(planned_gate_ids, remaining, completed, gate_by_id)
        if len(group) == 1:
            gate_id = group[0]
            gate_run = run_configured_gate(
                repo,
                gate_by_id[gate_id],
                snapshot,
                allow_untrusted_gates=allow_untrusted_gates,
                ci_mode=ci_mode,
            )
            results_by_id[gate_id] = gate_run.gate
            diagnostics_by_id[gate_id] = gate_run.diagnostics
            exit_status = max(exit_status, gate_run.failed)
        else:
            with ThreadPoolExecutor(max_workers=len(group)) as executor:
                future_by_id = {
                    gate_id: executor.submit(
                        run_configured_gate,
                        repo,
                        gate_by_id[gate_id],
                        snapshot,
                        allow_untrusted_gates=allow_untrusted_gates,
                        ci_mode=ci_mode,
                    )
                    for gate_id in group
                }
                for gate_id in group:
                    gate_run = future_by_id[gate_id].result()
                    results_by_id[gate_id] = gate_run.gate
                    diagnostics_by_id[gate_id] = gate_run.diagnostics
                    exit_status = max(exit_status, gate_run.failed)
        remaining.difference_update(group)
        completed.update(group)

    results = [results_by_id[gate_id] for gate_id in planned_gate_ids]
    diagnostics = [
        diagnostic
        for gate_id in planned_gate_ids
        for diagnostic in diagnostics_by_id.get(gate_id, [])
    ]

    update_run_record_after_gates(snapshot, snapshot_path, results, diagnostics, exit_status)
    return results, diagnostics, exit_status
