from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from .domain.types import JsonObject
from .errors import WorkflowError
from .git_snapshot import git_path
from .utils import redact_data


def make_run_id(snapshot_id: str) -> str:
    # Microseconds keep run ids unique when the same snapshot is written
    # more than once within a second.
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    short_hash = snapshot_id.split(":", 1)[-1][:8]
    return f"{timestamp}-{short_hash}"


def resolve_run_root(repo: Path, cache_dir: str | None, run_id: str) -> Path:
    if cache_dir:
        requested = Path(cache_dir)
        base = requested.resolve() if requested.is_absolute() else (repo / requested).resolve()
    else:
        base = git_path(repo, "review-fix-loop")
    return base / "runs" / run_id


def write_json(path: Path, data: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling temp file and replace atomically so a failed dump
    # cannot leave a truncated JSON file behind.
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def read_json(path: Path) -> JsonObject:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise WorkflowError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"expected object in {path}")
    return data


def optional_string_field(data: JsonObject, field: str) -> str | None:
    value = data.get(field)
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    raise WorkflowError(f"{field} must be a string")


def string_list_field(data: JsonObject, field: str) -> list[str]:
    value = data.get(field, [])
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if all(isinstance(item, str) for item in value):
            return list(value)
    raise WorkflowError(f"{field} must be a list of strings")


def resolve_record_update_path(snapshot: JsonObject, snapshot_path: Path) -> Path:
    run_record_path = optional_string_field(snapshot, "run_record_path")
    if not run_record_path:
        return snapshot_path.parent / "run-record.json"
    path = Path(run_record_path).resolve()
    snapshot_dir = snapshot_path.resolve().parent
    try:
        path.parent.relative_to(snapshot_dir)
    except ValueError as exc:
        raise WorkflowError("run_record_path must stay under the snapshot directory") from exc
    return path


def update_run_record_after_gates(
    snapshot: JsonObject,
    snapshot_path: Path,
    gates: list[JsonObject],
    diagnostics: list[JsonObject],
    exit_status: int,
) -> bool:
    path = resolve_record_update_path(snapshot, snapshot_path)
    if not path.exists():
        return False
    record = read_json(path)
    record["gates"] = gates
    record["diagnostics"] = diagnostics
    record["stop_decision"] = "continue" if exit_status else "stop"
    write_json(path, record)
    return True


def build_run_record(snapshot: JsonObject, run_id: str) -> JsonObject:
    return {
        "schema": 1,
        "run_id": run_id,
        "mode": snapshot["mode"],
        "pass": snapshot["pass"],
        "snapshot_id": snapshot["snapshot_id"],
        "previous_snapshot_id": snapshot.get("previous_snapshot_id"),
        "config_hash": snapshot["config_hash"],
        "rule_hashes": snapshot["rule_hashes"],
        "config_sources": string_list_field(snapshot, "config_sources"),
        "local_override_applied": snapshot.get("local_override_applied", False),
        "local_override_available": snapshot.get("local_override_available", False),
        "local_override_disabled": snapshot.get("local_override_disabled", False),
        "local_override_path": snapshot.get("local_override_path"),
        "final_pass": snapshot.get("final_pass", False),
        "scope_hashes": snapshot["scope_hashes"],
        "slice_hashes": snapshot["slice_hashes"],
        "must_reload": string_list_field(snapshot, "must_reload"),
        "reloaded_slices": string_list_field(snapshot, "reloaded_slices"),
        "reused_slices": string_list_field(snapshot, "reused_slices"),
        "reuse_forbidden_slices": snapshot.get("reuse_forbidden_slices", {}),
        "planned_gates": string_list_field(snapshot, "planned_gates"),
        "diagnostics": [],
        "fixes": [],
        "gates": [],
        "stop_decision": "continue",
        "residual_risks": [],
    }


def write_run_outputs(
    run_root: Path,
    snapshot: JsonObject,
    run_record: JsonObject,
    config: JsonObject,
) -> tuple[Path, Path]:
    config_sources = string_list_field(snapshot, "config_sources")
    must_reload = string_list_field(snapshot, "must_reload")
    planned_gates = string_list_field(snapshot, "planned_gates")
    snapshot_path = run_root / "snapshot.json"
    run_record_path = run_root / "run-record.json"
    write_json(snapshot_path, snapshot)
    write_json(run_record_path, run_record)
    write_json(run_root / "gates.json", redact_data(config))
    summary = (
        f"Status: continue\n"
        f"Mode: {snapshot['mode']}\n"
        f"Pass: {snapshot['pass']}\n"
        f"Snapshot: {snapshot['snapshot_id']}\n"
        f"Config sources: {', '.join(config_sources)}\n"
        f"Local override applied: {snapshot.get('local_override_applied', False)}\n"
        f"Must reload: {', '.join(must_reload)}\n"
        f"Planned gates: {', '.join(planned_gates)}\n"
    )
    write_text_atomic(run_root / "summary.md", summary)
    return snapshot_path, run_record_path
