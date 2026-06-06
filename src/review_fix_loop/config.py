from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .utils import normalize_repo_path, sha256_json, sha256_text, stable_json

VALID_SCOPES = {"staged", "unstaged", "untracked", "merge_base_to_head", "all"}
VALID_MODES = {"normal_loop", "large_merge"}
VALID_RISKS = {"low", "medium", "high"}
VALID_FILTER_MODES = {"added", "diff_context", "file", "nofilter"}
VALID_FAIL_LEVELS = {"none", "info", "warning", "error"}
VALID_PARSERS = {"exit-code", "git-diff-check", "regex-lines", "json-diagnostics", "rdjson", "sarif", "checkstyle"}


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain an object: {path}")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_effective_config(repo: Path, config_path: Path, cli_rule_files: list[str] | None = None) -> tuple[dict[str, Any], str, dict[str, str]]:
    config = load_json_file(config_path)
    local_override = repo / ".review-fix-loop.local.json"
    if local_override.exists():
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
    return config, config_hash, rule_hashes


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


def validate_config(config: dict[str, Any]) -> None:
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
        if mode_id not in VALID_MODES:
            raise ConfigError(f"invalid mode id: {mode_id}")
        if not isinstance(mode, dict):
            raise ConfigError(f"mode {mode_id} must be an object")
        scope = mode.get("scope", [])
        if not isinstance(scope, list) or not scope:
            raise ConfigError(f"mode {mode_id} must define a non-empty scope list")
        for item in scope:
            if item not in VALID_SCOPES:
                raise ConfigError(f"invalid scope in mode {mode_id}: {item}")

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
        argv = gate.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
            raise ConfigError(f"gate {gate_id} argv must be a non-empty string list")
        scope = gate.get("scope")
        if scope not in VALID_SCOPES:
            raise ConfigError(f"gate {gate_id} has invalid scope: {scope}")
        if gate.get("filter_mode", "nofilter") not in VALID_FILTER_MODES:
            raise ConfigError(f"gate {gate_id} has invalid filter_mode")
        if gate.get("fail_level", "error") not in VALID_FAIL_LEVELS:
            raise ConfigError(f"gate {gate_id} has invalid fail_level")
        if "modes" in gate:
            if not isinstance(gate["modes"], list) or not all(mode in VALID_MODES for mode in gate["modes"]):
                raise ConfigError(f"gate {gate_id} modes must reference valid modes")
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


def config_for_hash(config: dict[str, Any]) -> str:
    return stable_json(config)
