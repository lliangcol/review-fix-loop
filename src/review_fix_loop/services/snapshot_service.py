from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import load_effective_config
from ..domain.types import FreshnessResult, JsonObject, SnapshotRequest
from ..errors import ConfigError, WorkflowError
from ..gates import plan_gates
from ..git_snapshot import collect_scopes, compute_scope_hashes, resolve_repo
from ..repo_map import build_repo_map
from ..run_record import build_run_record, make_run_id, read_json, resolve_run_root, write_run_outputs
from ..slices import attach_slices, compute_slice_hashes, paths_by_slice
from ..utils import resolve_repo_file, sha256_json


@dataclass(frozen=True)
class SnapshotExecutionResult:
    snapshot: JsonObject

    def to_json_output(self) -> JsonObject:
        return self.snapshot


def create_snapshot_request(
    repo_value: str | Path,
    config_value: str | Path,
    mode: str,
    pass_number: int,
    rule_files: list[str],
    *,
    baseline: str | None = None,
    previous_run_record: str | None = None,
    final_pass: bool = False,
    write_run_record: bool = False,
    apply_local_override: bool = True,
    cache_dir: str | None = None,
    include_repo_map: bool = False,
    repo_map_limit: int = 40,
) -> SnapshotExecutionResult:
    return create_snapshot_from_request(SnapshotRequest(
        repo=repo_value,
        config=config_value,
        mode=mode,
        pass_number=pass_number,
        rule_files=rule_files,
        baseline=baseline,
        previous_run_record=previous_run_record,
        final_pass=final_pass,
        write_run_record=write_run_record,
        apply_local_override=apply_local_override,
        cache_dir=cache_dir,
        include_repo_map=include_repo_map,
        repo_map_limit=repo_map_limit,
    ))


def create_snapshot_from_request(request: SnapshotRequest) -> SnapshotExecutionResult:
    if request.pass_number < 1:
        raise WorkflowError("--pass must be 1 or greater")
    if request.pass_number > 1 and not request.previous_run_record:
        raise WorkflowError("--pass > 1 requires --previous-run-record")

    repo = resolve_repo(request.repo)
    config_path = resolve_repo_file(repo, request.config)
    config, config_hash, rule_hashes, source_info = load_effective_config(
        repo,
        config_path,
        request.rule_files,
        apply_local_override=request.apply_local_override,
    )
    mode_config = config["modes"].get(request.mode)
    if mode_config is None:
        raise ConfigError(f"mode is not defined in config: {request.mode}")
    effective_baseline = request.baseline or mode_config.get("baseline")
    mode_scopes = mode_config.get("scope", [])
    # The baseline is only meaningful when the branch diff is actually collected.
    # Key off the scope (not the mode name) so any mode that declares
    # merge_base_to_head records its baseline in the snapshot id and gate args.
    uses_merge_base = "merge_base_to_head" in mode_scopes
    recorded_baseline = effective_baseline if uses_merge_base else None
    merge_base, entries_by_scope = collect_scopes(repo, request.mode, effective_baseline, mode_scopes)
    attach_slices(entries_by_scope, config.get("slices", []))
    scope_hashes = compute_scope_hashes(entries_by_scope)
    slice_hashes = compute_slice_hashes(entries_by_scope)
    planned_gates = plan_gates(config, request.mode, entries_by_scope, request.final_pass)
    repo_map = build_repo_map(repo, entries_by_scope, request.repo_map_limit) if request.include_repo_map else None

    snapshot_seed = {
        "mode": request.mode,
        "baseline": recorded_baseline,
        "merge_base": merge_base,
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        "final_pass": request.final_pass,
        "planned_gates": planned_gates,
        "repo_map_hash": sha256_json(repo_map) if repo_map is not None else None,
    }
    snapshot_id = sha256_json(snapshot_seed)
    freshness = compute_freshness(
        request.pass_number,
        entries_by_scope,
        slice_hashes,
        config_hash,
        rule_hashes,
        request.previous_run_record,
    )
    snapshot: JsonObject = {
        "schema": 1,
        "mode": request.mode,
        "pass": request.pass_number,
        "snapshot_id": snapshot_id,
        "previous_snapshot_id": freshness.get("previous_snapshot_id"),
        "baseline": recorded_baseline,
        "merge_base": merge_base,
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        **source_info,
        "final_pass": request.final_pass,
        "scope_hashes": scope_hashes,
        "slice_hashes": slice_hashes,
        "entries": entries_by_scope,
        "planned_gates": planned_gates,
        **freshness,
    }
    if repo_map is not None:
        snapshot["repo_map"] = repo_map

    if request.write_run_record:
        run_id = make_run_id(snapshot_id)
        run_root = resolve_run_root(repo, request.cache_dir, run_id)
        snapshot["snapshot_path"] = str(run_root / "snapshot.json")
        snapshot["run_record_path"] = str(run_root / "run-record.json")
        run_record = build_run_record(snapshot, run_id)
        run_record["snapshot_path"] = snapshot["snapshot_path"]
        run_record["run_record_path"] = snapshot["run_record_path"]
        write_run_outputs(run_root, snapshot, run_record, config)

    return SnapshotExecutionResult(snapshot=snapshot)


def compute_freshness(
    pass_number: int,
    entries_by_scope: dict[str, list[JsonObject]],
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


def previous_slice_has_fixes(previous: JsonObject, slice_id: str) -> bool:
    for fix in previous.get("fixes", []):
        if isinstance(fix, dict) and fix.get("slice") == slice_id:
            return True
    return False


def previous_slice_has_unresolved_diagnostics(previous: JsonObject, slice_id: str) -> bool:
    if previous.get("stop_decision") == "stop":
        return False
    for diagnostic in previous.get("diagnostics", []):
        if isinstance(diagnostic, dict) and diagnostic.get("slice") == slice_id:
            return True
    return False


def verify_fresh_tree(repo: Path, config: JsonObject, snapshot: JsonObject) -> None:
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
