from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import load_effective_config
from ..domain.types import GateRequest, JsonObject
from ..errors import WorkflowError
from ..gates import run_planned_gates
from ..git_snapshot import resolve_repo
from ..run_record import read_json
from ..utils import resolve_repo_file
from .snapshot_service import verify_fresh_tree


@dataclass(frozen=True)
class GateExecutionResult:
    gates: list[JsonObject]
    diagnostics: list[JsonObject]
    exit_status: int

    def to_json_output(self) -> JsonObject:
        return {"gates": self.gates, "diagnostics": self.diagnostics}


def execute_gate_request(
    repo_value: str | Path,
    config_value: str | Path,
    snapshot_value: str | Path,
    rule_files: list[str],
    *,
    apply_local_override: bool = True,
    allow_untrusted_gates: bool = False,
    ci_mode: bool = False,
    require_fresh_tree: bool = False,
) -> GateExecutionResult:
    return execute_gate_from_request(GateRequest(
        repo=repo_value,
        config=config_value,
        snapshot=snapshot_value,
        rule_files=rule_files,
        apply_local_override=apply_local_override,
        allow_untrusted_gates=allow_untrusted_gates,
        ci_mode=ci_mode,
        require_fresh_tree=require_fresh_tree,
    ))


def execute_gate_from_request(request: GateRequest) -> GateExecutionResult:
    repo = resolve_repo(request.repo)
    config_path = resolve_repo_file(repo, request.config)
    config, config_hash, rule_hashes, _source_info = load_effective_config(
        repo,
        config_path,
        request.rule_files,
        apply_local_override=request.apply_local_override,
    )
    snapshot_path = Path(request.snapshot)
    snapshot = read_json(snapshot_path)
    if snapshot.get("config_hash") != config_hash:
        raise WorkflowError("effective config hash differs from snapshot config_hash; create a fresh snapshot")
    if snapshot.get("rule_hashes", {}) != rule_hashes:
        raise WorkflowError("rule file hashes differ from snapshot rule_hashes; create a fresh snapshot")
    if request.require_fresh_tree:
        verify_fresh_tree(repo, config, snapshot)
    gates, diagnostics, exit_status = execute_planned_gates(
        repo,
        config,
        snapshot,
        snapshot_path,
        allow_untrusted_gates=request.allow_untrusted_gates,
        ci_mode=request.ci_mode,
    )
    return GateExecutionResult(gates=gates, diagnostics=diagnostics, exit_status=exit_status)


def execute_planned_gates(
    repo: Path,
    config: JsonObject,
    snapshot: JsonObject,
    snapshot_path: Path,
    *,
    allow_untrusted_gates: bool = False,
    ci_mode: bool = False,
) -> tuple[list[JsonObject], list[JsonObject], int]:
    return run_planned_gates(
        repo,
        config,
        snapshot,
        snapshot_path,
        allow_untrusted_gates=allow_untrusted_gates,
        ci_mode=ci_mode,
    )
