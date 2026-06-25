from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict


class FreshnessResult(TypedDict, total=False):
    previous_snapshot_id: str | None
    must_reload: list[str]
    reloaded_slices: list[str]
    reused_slices: list[str]
    reuse_forbidden_slices: dict[str, list[str]]


JsonObject = dict[str, Any]


@dataclass(frozen=True)
class SnapshotRequest:
    repo: str | Path
    config: str | Path
    mode: str
    pass_number: int
    rule_files: list[str] = field(default_factory=list)
    baseline: str | None = None
    previous_run_record: str | None = None
    final_pass: bool = False
    write_run_record: bool = False
    apply_local_override: bool = True
    cache_dir: str | None = None
    include_repo_map: bool = False
    repo_map_limit: int = 40


@dataclass(frozen=True)
class GateRequest:
    repo: str | Path
    config: str | Path
    snapshot: str | Path
    rule_files: list[str] = field(default_factory=list)
    apply_local_override: bool = True
    allow_untrusted_gates: bool = False
    ci_mode: bool = False
    require_fresh_tree: bool = False


@dataclass(frozen=True)
class SchemaValidationRequest:
    schema_name: str
    file: str | Path
    repo: str | Path | None = None


@dataclass(frozen=True)
class SchemaValidationResult:
    result: JsonObject

    @property
    def valid(self) -> bool:
        return bool(self.result.get("valid", False))

    def to_json_output(self) -> JsonObject:
        return self.result


@dataclass(frozen=True)
class GateCommandOutput:
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_bytes: int
    stderr_bytes: int


@dataclass(frozen=True)
class GateRunResult:
    gate: JsonObject
    diagnostics: list[JsonObject]
    failed: int
