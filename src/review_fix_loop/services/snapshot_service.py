from __future__ import annotations

from pathlib import Path
from typing import Any

from ..domain.types import FreshnessResult
from ..errors import WorkflowError
from ..git_snapshot import collect_scopes, compute_scope_hashes
from ..run_record import read_json
from ..slices import attach_slices, paths_by_slice


def compute_freshness(
    pass_number: int,
    entries_by_scope: dict[str, list[dict[str, Any]]],
    slice_hashes: dict[str, str],
    config_hash: str,
    rule_hashes: dict[str, str],
    previous_run_record: str | None,
) -> FreshnessResult:
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


def verify_fresh_tree(repo: Path, config: dict[str, Any], snapshot: dict[str, Any]) -> None:
    mode = snapshot.get("mode")
    if not isinstance(mode, str):
        raise WorkflowError("snapshot mode must be a string")
    mode_config = config.get("modes", {}).get(mode)
    if not isinstance(mode_config, dict):
        raise WorkflowError(f"snapshot mode is not defined in config: {mode}")
    baseline_value = snapshot.get("baseline") or mode_config.get("baseline")
    baseline = baseline_value if isinstance(baseline_value, str) else None
    mode_scopes = mode_config.get("scope", [])
    if not isinstance(mode_scopes, list) or not all(isinstance(scope, str) for scope in mode_scopes):
        raise WorkflowError(f"snapshot mode has invalid scope list: {mode}")
    _, entries_by_scope = collect_scopes(repo, mode, baseline, mode_scopes)
    attach_slices(entries_by_scope, config.get("slices", []))
    if compute_scope_hashes(entries_by_scope) != snapshot.get("scope_hashes"):
        raise WorkflowError("working tree changed since snapshot; create a fresh snapshot")
