from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .domain.types import JsonObject
from .errors import ConfigError
from .gates import BUILTIN_GATE_COMMANDS, BUILTIN_PREFIX
from .utils import normalize_repo_path, sha256_json, sha256_text

VALID_SCOPES = {"staged", "unstaged", "untracked", "merge_base_to_head", "all"}
VALID_RISKS = {"low", "medium", "high"}
VALID_FILTER_MODES = {"added", "diff_context", "file", "nofilter"}
VALID_FAIL_LEVELS = {"none", "info", "warning", "error"}
VALID_PARSERS = {"exit-code", "git-diff-check", "regex-lines", "json-diagnostics", "rdjson", "sarif", "checkstyle"}
MODE_BOOLEAN_FIELDS = {
    "require_fresh_snapshot",
    "require_risk_slices",
    "require_invariant_checks",
    "require_residual_risk_report",
    "requires_merge_base",
    "requires_final_pass",
    "requires_repo_map",
    "requires_residual_risk_report",
}
MODE_LIMIT_FIELDS = {"max_deep_review_files", "max_changed_files", "max_diff_bytes_per_slice"}
GATE_BOOLEAN_FIELDS = {
    "blocking",
    "final_always",
    "trusted",
    "allow_in_ci",
    "writes_worktree",
    "requires_network",
    "parallel_safe",
    "reads_worktree_only",
}


ConfigData = JsonObject
ConfigSourceInfo = JsonObject


def reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> JsonObject:
    result: JsonObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_file(path: Path) -> ConfigData:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle, object_pairs_hook=reject_duplicate_object_keys)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"malformed JSON in {path}: {exc}") from exc
    except ValueError as exc:
        raise ConfigError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain an object: {path}")
    return data


def deep_merge(base: ConfigData, override: ConfigData) -> ConfigData:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_effective_config(
    repo: Path,
    config_path: Path,
    cli_rule_files: list[str] | None = None,
    *,
    apply_local_override: bool = True,
) -> tuple[ConfigData, str, dict[str, str], ConfigSourceInfo]:
    config = load_json_file(config_path)
    local_override = repo / ".review-fix-loop.local.json"
    local_override_available = local_override.exists()
    local_override_applied = apply_local_override and local_override_available
    if local_override_applied:
        config = deep_merge(config, load_json_file(local_override))

    rule_files = list(config.get("rule_files", []))
    if cli_rule_files:
        rule_files.extend(cli_rule_files)
    normalized_rule_files: list[str] = []
    seen = set()
    for raw in rule_files:
        if not isinstance(raw, str):
            raise ConfigError("rule_files entries must be strings")
        normalized = normalize_repo_path(raw)
        if normalized not in seen:
            seen.add(normalized)
            normalized_rule_files.append(normalized)
    config["rule_files"] = normalized_rule_files

    validate_config(config)
    config_hash = sha256_json(config)
    rule_hashes = hash_rule_files(repo, normalized_rule_files)
    source_info: ConfigSourceInfo = {
        "config_sources": [str(config_path.resolve())],
        "local_override_applied": local_override_applied,
        "local_override_available": local_override_available,
        "local_override_disabled": local_override_available and not apply_local_override,
        "local_override_path": str(local_override.resolve()) if local_override_available else None,
    }
    if local_override_applied:
        source_info["config_sources"].append(str(local_override.resolve()))
    return config, config_hash, rule_hashes, source_info


def hash_rule_files(repo: Path, rule_files: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rule_file in rule_files:
        path = (repo / rule_file).resolve()
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"declared rule file is missing: {rule_file}") from exc
        hashes[rule_file] = sha256_text(text)
    return hashes


def validate_config(config: ConfigData) -> None:
    if config.get("version") != 1:
        raise ConfigError("config version must be 1")
    modes = config.get("modes")
    slices = config.get("slices")
    gates = config.get("gates")
    if not isinstance(modes, dict) or not modes:
        raise ConfigError("modes must be a non-empty object")
    if not isinstance(slices, list):
        raise ConfigError("slices must be a list")
    if not isinstance(gates, list):
        raise ConfigError("gates must be a list")

    for mode_id, mode in modes.items():
        if not isinstance(mode_id, str) or not mode_id:
            raise ConfigError("mode id must be a non-empty string")
        if not isinstance(mode, dict):
            raise ConfigError(f"mode {mode_id} must be an object")
        scope = mode.get("scope", [])
        if not isinstance(scope, list) or not scope:
            raise ConfigError(f"mode {mode_id} must define a non-empty scope list")
        for item in scope:
            if item not in VALID_SCOPES:
                raise ConfigError(f"invalid scope in mode {mode_id}: {item}")
        if "baseline" in mode and not isinstance(mode["baseline"], str):
            raise ConfigError(f"mode {mode_id} baseline must be a string")
        # Advisory contract fields are validated and recorded in the config
        # hash, but most are honored by the agent/skill rather than enforced by
        # the CLI itself. See docs/architecture.md.
        for flag in MODE_BOOLEAN_FIELDS:
            if flag in mode and not isinstance(mode[flag], bool):
                raise ConfigError(f"mode {mode_id} {flag} must be a boolean")
        if mode.get("requires_merge_base") and "merge_base_to_head" not in scope:
            raise ConfigError(f"mode {mode_id} requires_merge_base needs merge_base_to_head scope")
        for limit_field in MODE_LIMIT_FIELDS:
            if limit_field in mode:
                value = mode[limit_field]
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ConfigError(f"mode {mode_id} {limit_field} must be an integer >= 1")

    seen_slices = set()
    for item in slices:
        if not isinstance(item, dict):
            raise ConfigError("slice entries must be objects")
        slice_id = item.get("id")
        if not isinstance(slice_id, str) or not slice_id:
            raise ConfigError("slice id is required")
        if slice_id in seen_slices:
            raise ConfigError(f"duplicate slice id: {slice_id}")
        seen_slices.add(slice_id)
        if item.get("risk", "medium") not in VALID_RISKS:
            raise ConfigError(f"invalid risk for slice {slice_id}: {item.get('risk')}")
        paths = item.get("paths")
        if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
            raise ConfigError(f"slice {slice_id} paths must be a string list")

    gate_ids = []
    seen_gates = set()
    for gate in gates:
        if not isinstance(gate, dict):
            raise ConfigError("gate entries must be objects")
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id:
            raise ConfigError("gate id is required")
        if gate_id in seen_gates:
            raise ConfigError(f"duplicate gate id: {gate_id}")
        seen_gates.add(gate_id)
        gate_ids.append(gate_id)

    valid_mode_ids = set(modes)
    valid_gate_ids = set(gate_ids)
    for gate in gates:
        gate_id = gate["id"]
        argv = gate.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            raise ConfigError(f"gate {gate_id} argv must be a non-empty string list")
        if argv[0].startswith(BUILTIN_PREFIX) and argv[0] not in BUILTIN_GATE_COMMANDS:
            known = ", ".join(sorted(BUILTIN_GATE_COMMANDS))
            raise ConfigError(f"gate {gate_id} references unknown builtin command: {argv[0]} (known builtins: {known})")
        scope = gate.get("scope")
        if scope not in VALID_SCOPES:
            raise ConfigError(f"gate {gate_id} has invalid scope: {scope}")
        if gate.get("filter_mode", "nofilter") not in VALID_FILTER_MODES:
            raise ConfigError(f"gate {gate_id} has invalid filter_mode")
        if gate.get("fail_level", "error") not in VALID_FAIL_LEVELS:
            raise ConfigError(f"gate {gate_id} has invalid fail_level")
        timeout = gate.get("timeout_seconds", 60)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ConfigError(f"gate {gate_id} timeout_seconds must be an integer >= 1")
        for flag in GATE_BOOLEAN_FIELDS:
            if flag in gate and not isinstance(gate[flag], bool):
                raise ConfigError(f"gate {gate_id} {flag} must be a boolean")
        if "trust_reason" in gate and not isinstance(gate["trust_reason"], str):
            raise ConfigError(f"gate {gate_id} trust_reason must be a string")
        if "depends_on" in gate:
            depends_on = gate["depends_on"]
            if not isinstance(depends_on, list) or not all(isinstance(item, str) for item in depends_on):
                raise ConfigError(f"gate {gate_id} depends_on must be a string list")
            unknown = [item for item in depends_on if item not in valid_gate_ids]
            if unknown:
                raise ConfigError(f"gate {gate_id} depends_on references unknown gate: {unknown[0]}")
        if "modes" in gate:
            if (
                not isinstance(gate["modes"], list)
                or not all(isinstance(mode, str) and mode in valid_mode_ids for mode in gate["modes"])
            ):
                raise ConfigError(f"gate {gate_id} modes must reference configured modes")
        if "when_paths" in gate:
            if not isinstance(gate["when_paths"], list) or not all(isinstance(path, str) for path in gate["when_paths"]):
                raise ConfigError(f"gate {gate_id} when_paths must be a string list")
        parser = gate.get("parser", {"type": "exit-code"})
        if not isinstance(parser, dict) or parser.get("type", "exit-code") not in VALID_PARSERS:
            raise ConfigError(f"gate {gate_id} has invalid parser type")
        parser_type = parser.get("type", "exit-code")
        policy = gate.get("policy")
        if argv[0] == "__builtin__:policy":
            if not isinstance(policy, dict):
                raise ConfigError(f"gate {gate_id} builtin policy requires a policy object")
            for field in ("require_changed_paths", "forbid_changed_paths"):
                if field in policy and (not isinstance(policy[field], list) or not all(isinstance(path, str) for path in policy[field])):
                    raise ConfigError(f"gate {gate_id} policy {field} must be a string list")
            if "require_final_pass" in policy and not isinstance(policy["require_final_pass"], bool):
                raise ConfigError(f"gate {gate_id} policy require_final_pass must be a boolean")
        if parser_type == "regex-lines":
            pattern = parser.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise ConfigError(f"gate {gate_id} regex-lines parser requires a pattern")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ConfigError(f"gate {gate_id} regex-lines parser pattern is invalid: {exc}") from exc
            if parser.get("severity", "error") not in {"info", "warning", "error"}:
                raise ConfigError(f"gate {gate_id} regex-lines parser severity is invalid")
