from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import load_effective_config
from .errors import ConfigError, GitError, ReviewFixLoopError, WorkflowError
from .gates import plan_gates, run_planned_gates
from .git_snapshot import collect_scopes, compute_scope_hashes, resolve_repo
from .run_record import build_run_record, make_run_id, read_json, resolve_run_root, write_run_outputs
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

    gate = subparsers.add_parser("gate", help="Run gates selected by a snapshot")
    gate.add_argument("--repo", required=True)
    gate.add_argument("--config", required=True)
    gate.add_argument("--snapshot", required=True)
    gate.add_argument("--rule-file", action="append", default=[])
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

    snapshot_seed = {
        "mode": args.mode,
        "baseline": baseline if args.mode == "large_merge" else None,
        "merge_base": merge_base,
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
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
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "entries": entries_by_scope,
        "planned_gates": planned_gates,
        **freshness,
    }

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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            return snapshot_command(args)
        if args.command == "gate":
            return gate_command(args)
        parser.error("unknown command")
        return 2
    except (ReviewFixLoopError, ConfigError, GitError, WorkflowError, ValueError) as exc:
        print(f"review-fix-loop: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
