from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .assets import discover_adapters, read_adapter_config
from .config import load_effective_config
from .errors import ConfigError, GitError, ReviewFixLoopError, WorkflowError
from .gates import plan_gates, run_planned_gates
from .git_snapshot import collect_scopes, compute_scope_hashes, resolve_repo, run_git
from .repo_map import build_repo_map
from .run_record import build_run_record, make_run_id, read_json, resolve_run_root, write_run_outputs
from .schema_validation import validate_json_schema
from .slices import attach_slices, compute_slice_hashes, paths_by_slice
from .utils import sha256_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-fix-loop")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Create a live Git review snapshot")
    snapshot.add_argument("--repo", required=True)
    snapshot.add_argument("--config", required=True)
    snapshot.add_argument("--mode", required=True, choices=["normal_loop", "large_merge"])
    snapshot.add_argument("--baseline")
    snapshot.add_argument("--pass", dest="pass_number", type=int, default=1)
    snapshot.add_argument("--previous-run-record")
    snapshot.add_argument("--final-pass", action="store_true")
    snapshot.add_argument("--write-run-record", action="store_true")
    snapshot.add_argument("--rule-file", action="append", default=[])
    snapshot.add_argument("--cache-dir")
    snapshot.add_argument("--include-repo-map", action="store_true")
    snapshot.add_argument("--repo-map-limit", type=int, default=40)

    gate = subparsers.add_parser("gate", help="Run gates selected by a snapshot")
    gate.add_argument("--repo", required=True)
    gate.add_argument("--config", required=True)
    gate.add_argument("--snapshot", required=True)
    gate.add_argument("--rule-file", action="append", default=[])

    init = subparsers.add_parser("init", help="Create an adapter config in a target repo")
    init.add_argument("--repo", required=True)
    init.add_argument("--adapter", default="generic")
    init.add_argument("--output", default="review-fix-loop.gates.json")
    init.add_argument("--force", action="store_true")

    list_adapters = subparsers.add_parser("list-adapters", help="List built-in and local adapter configs")
    list_adapters.add_argument("--repo")

    validate_config = subparsers.add_parser("validate-config", help="Validate and hash an effective gate config")
    validate_config.add_argument("--repo", required=True)
    validate_config.add_argument("--config", required=True)
    validate_config.add_argument("--rule-file", action="append", default=[])

    validate_schema = subparsers.add_parser("validate-schema", help="Validate a JSON artifact against a bundled schema")
    validate_schema.add_argument("--schema", required=True, choices=["gate-config", "snapshot", "run-record", "diagnostic"])
    validate_schema.add_argument("--file", required=True)
    validate_schema.add_argument("--repo")

    doctor = subparsers.add_parser("doctor", help="Check local git/config readiness without running gates")
    doctor.add_argument("--repo", required=True)
    doctor.add_argument("--config")
    doctor.add_argument("--rule-file", action="append", default=[])

    inspect = subparsers.add_parser("inspect", help="Summarize a snapshot or run record")
    inspect_input = inspect.add_mutually_exclusive_group(required=True)
    inspect_input.add_argument("--snapshot")
    inspect_input.add_argument("--run-record")
    inspect.add_argument("--format", choices=["json", "markdown"], default="markdown")
    return parser


def snapshot_command(args: argparse.Namespace) -> int:
    if args.pass_number < 1:
        raise WorkflowError("--pass must be 1 or greater")
    if args.pass_number > 1 and not args.previous_run_record:
        raise WorkflowError("--pass > 1 requires --previous-run-record")

    repo = resolve_repo(args.repo)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo / config_path
    config, config_hash, rule_hashes = load_effective_config(repo, config_path, args.rule_file)
    mode_config = config["modes"][args.mode]
    baseline = args.baseline or mode_config.get("baseline")
    mode_scopes = mode_config.get("scope", [])
    merge_base, entries_by_scope = collect_scopes(repo, args.mode, baseline, mode_scopes)
    attach_slices(entries_by_scope, config.get("slices", []))
    scope_hashes = compute_scope_hashes(entries_by_scope)
    slice_hashes = compute_slice_hashes(entries_by_scope)
    planned_gates = plan_gates(config, args.mode, entries_by_scope, args.final_pass)
    repo_map = build_repo_map(repo, entries_by_scope, args.repo_map_limit) if args.include_repo_map else None

    snapshot_seed = {
        "mode": args.mode,
        "baseline": baseline if args.mode == "large_merge" else None,
        "merge_base": merge_base,
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        "final_pass": args.final_pass,
        "planned_gates": planned_gates,
        "repo_map_hash": sha256_json(repo_map) if repo_map is not None else None,
    }
    snapshot_id = sha256_json(snapshot_seed)
    freshness = compute_freshness(
        args.pass_number,
        entries_by_scope,
        slice_hashes,
        config_hash,
        rule_hashes,
        args.previous_run_record,
    )
    snapshot: dict[str, Any] = {
        "schema": 1,
        "mode": args.mode,
        "pass": args.pass_number,
        "snapshot_id": snapshot_id,
        "previous_snapshot_id": freshness.get("previous_snapshot_id"),
        "baseline": baseline if args.mode == "large_merge" else None,
        "merge_base": merge_base,
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        "final_pass": args.final_pass,
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "entries": entries_by_scope,
        "planned_gates": planned_gates,
        **freshness,
    }
    if repo_map is not None:
        snapshot["repo_map"] = repo_map

    if args.write_run_record:
        run_id = make_run_id(snapshot_id)
        run_root = resolve_run_root(repo, args.cache_dir, run_id)
        snapshot["snapshot_path"] = str(run_root / "snapshot.json")
        snapshot["run_record_path"] = str(run_root / "run-record.json")
        run_record = build_run_record(snapshot, run_id)
        run_record["snapshot_path"] = snapshot["snapshot_path"]
        run_record["run_record_path"] = snapshot["run_record_path"]
        write_run_outputs(run_root, snapshot, run_record, config)

    print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def compute_freshness(
    pass_number: int,
    entries_by_scope: dict[str, list[dict[str, Any]]],
    slice_hashes: dict[str, str],
    config_hash: str,
    rule_hashes: dict[str, str],
    previous_run_record: str | None,
) -> dict[str, Any]:
    current_paths = paths_by_slice(entries_by_scope)
    if pass_number == 1:
        all_paths = sorted({path for paths in current_paths.values() for path in paths})
        return {
            "must_reload": all_paths,
            "reloaded_slices": sorted(current_paths),
            "reused_slices": [],
            "reuse_forbidden_slices": {},
        }

    previous = read_json(Path(previous_run_record or ""))
    previous_slice_hashes = previous.get("slice_hashes", {})
    previous_rule_hashes = previous.get("rule_hashes", {})
    previous_config_hash = previous.get("config_hash")
    forbidden: dict[str, list[str]] = {}
    reused = []
    must_reload = []
    for slice_id, current_hash in slice_hashes.items():
        reasons = []
        if previous_slice_hashes.get(slice_id) != current_hash:
            reasons.append("slice hash changed")
        if previous_config_hash != config_hash:
            reasons.append("gate config changed")
        if previous_rule_hashes != rule_hashes:
            reasons.append("project rules changed")
        if previous_slice_has_fixes(previous, slice_id):
            reasons.append("previous pass fixed files in slice")
        if previous_slice_has_unresolved_diagnostics(previous, slice_id):
            reasons.append("previous pass had unresolved diagnostics in slice")
        if reasons:
            forbidden[slice_id] = reasons
            must_reload.extend(current_paths.get(slice_id, []))
        else:
            reused.append(slice_id)
    return {
        "previous_snapshot_id": previous.get("snapshot_id"),
        "must_reload": sorted(set(must_reload)),
        "reloaded_slices": sorted(forbidden),
        "reused_slices": sorted(reused),
        "reuse_forbidden_slices": forbidden,
    }


def previous_slice_has_fixes(previous: dict[str, Any], slice_id: str) -> bool:
    for fix in previous.get("fixes", []):
        if isinstance(fix, dict) and fix.get("slice") == slice_id:
            return True
    return False


def previous_slice_has_unresolved_diagnostics(previous: dict[str, Any], slice_id: str) -> bool:
    if previous.get("stop_decision") == "stop":
        return False
    for diagnostic in previous.get("diagnostics", []):
        if isinstance(diagnostic, dict) and diagnostic.get("slice") == slice_id:
            return True
    return False


def gate_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo / config_path
    config, config_hash, rule_hashes = load_effective_config(repo, config_path, args.rule_file)
    snapshot_path = Path(args.snapshot)
    snapshot = read_json(snapshot_path)
    if snapshot.get("config_hash") != config_hash:
        raise WorkflowError("effective config hash differs from snapshot config_hash; create a fresh snapshot")
    if snapshot.get("rule_hashes", {}) != rule_hashes:
        raise WorkflowError("rule file hashes differ from snapshot rule_hashes; create a fresh snapshot")
    results, diagnostics, exit_status = run_planned_gates(repo, config, snapshot, snapshot_path)
    print(json.dumps({"gates": results, "diagnostics": diagnostics}, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_status


def resolve_repo_file(repo: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo / path


def init_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    text, source = read_adapter_config(args.adapter, repo)
    output = resolve_repo_file(repo, args.output)
    if output.exists() and not args.force:
        raise WorkflowError(f"output already exists: {output}; pass --force to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({
        "adapter": args.adapter,
        "source": source,
        "output": str(output),
        "status": "written",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def list_adapters_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo) if args.repo else None
    print(json.dumps({"adapters": discover_adapters(repo)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def validate_config_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    config_path = resolve_repo_file(repo, args.config)
    config, config_hash, rule_hashes = load_effective_config(repo, config_path, args.rule_file)
    summary = {
        "valid": True,
        "config": str(config_path),
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        "modes": sorted(config.get("modes", {})),
        "slices": len(config.get("slices", [])),
        "gates": [gate["id"] for gate in config.get("gates", [])],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def validate_schema_command(args: argparse.Namespace) -> int:
    repo = None
    if args.repo:
        repo = resolve_repo(args.repo)
        path = resolve_repo_file(repo, args.file)
    else:
        path = Path(args.file).resolve()
    result = validate_json_schema(args.schema, path, repo)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


def doctor_command(args: argparse.Namespace) -> int:
    status: dict[str, Any] = {
        "ok": True,
        "errors": [],
        "warnings": [],
    }
    repo: Path | None = None
    try:
        repo = resolve_repo(args.repo)
        status["repo"] = str(repo)
        version = run_git(repo, ["--version"], check=False).stdout.decode("utf-8", "replace").strip()
        status["git"] = version
    except ReviewFixLoopError as exc:
        status["ok"] = False
        status["errors"].append(str(exc))

    if repo is not None and args.config:
        try:
            config_path = resolve_repo_file(repo, args.config)
            config, config_hash, rule_hashes = load_effective_config(repo, config_path, args.rule_file)
            status["config"] = str(config_path)
            status["config_hash"] = config_hash
            status["rule_hashes"] = rule_hashes
            status["gates"] = len(config.get("gates", []))
        except ReviewFixLoopError as exc:
            status["ok"] = False
            status["errors"].append(str(exc))

    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status["ok"] else 1


def inspect_summary(data: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "snapshot":
        entries = data.get("entries", {})
        return {
            "kind": "snapshot",
            "snapshot_id": data.get("snapshot_id"),
            "mode": data.get("mode"),
            "pass": data.get("pass"),
            "final_pass": data.get("final_pass", False),
            "entries": {scope: len(items) for scope, items in entries.items() if isinstance(items, list)},
            "must_reload": data.get("must_reload", []),
            "planned_gates": data.get("planned_gates", []),
            "reloaded_slices": data.get("reloaded_slices", []),
            "reused_slices": data.get("reused_slices", []),
            "repo_map_files": len(data.get("repo_map", {}).get("files", [])) if isinstance(data.get("repo_map"), dict) else 0,
        }
    return {
        "kind": "run-record",
        "run_id": data.get("run_id"),
        "snapshot_id": data.get("snapshot_id"),
        "mode": data.get("mode"),
        "pass": data.get("pass"),
        "final_pass": data.get("final_pass", False),
        "stop_decision": data.get("stop_decision"),
        "planned_gates": data.get("planned_gates", []),
        "gates": [
            {"id": gate.get("id"), "status": gate.get("status"), "exit_code": gate.get("exit_code")}
            for gate in data.get("gates", [])
            if isinstance(gate, dict)
        ],
        "diagnostics": len(data.get("diagnostics", [])),
    }


def format_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        f"# review-fix-loop {summary['kind']}",
        "",
    ]
    for key, value in summary.items():
        if key == "kind":
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) if value else "-"
        elif isinstance(value, dict):
            rendered = ", ".join(f"{item_key}={item_value}" for item_key, item_value in value.items()) if value else "-"
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


def inspect_command(args: argparse.Namespace) -> int:
    if args.snapshot:
        path = Path(args.snapshot)
        data = read_json(path)
        summary = inspect_summary(data, "snapshot")
    else:
        path = Path(args.run_record)
        data = read_json(path)
        summary = inspect_summary(data, "run-record")
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_markdown_summary(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            return snapshot_command(args)
        if args.command == "gate":
            return gate_command(args)
        if args.command == "init":
            return init_command(args)
        if args.command == "list-adapters":
            return list_adapters_command(args)
        if args.command == "validate-config":
            return validate_config_command(args)
        if args.command == "validate-schema":
            return validate_schema_command(args)
        if args.command == "doctor":
            return doctor_command(args)
        if args.command == "inspect":
            return inspect_command(args)
        parser.error("unknown command")
        return 2
    except (ReviewFixLoopError, ConfigError, GitError, WorkflowError, ValueError) as exc:
        print(f"review-fix-loop: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
