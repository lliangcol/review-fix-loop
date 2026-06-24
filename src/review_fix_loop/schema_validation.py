from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assets import read_schema
from .config import load_effective_config
from .errors import WorkflowError


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise WorkflowError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"malformed JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"expected JSON object in {path}")
    return data


def minimal_validate(data: dict[str, Any], schema: dict[str, Any], path: Path) -> list[str]:
    errors = []
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"{path}: missing required field: {field}")
    properties = schema.get("properties", {})
    for field, rules in properties.items():
        if field not in data or not isinstance(rules, dict):
            continue
        if "const" in rules and data[field] != rules["const"]:
            errors.append(f"{path}: field {field} must be {rules['const']!r}")
        if "enum" in rules and data[field] not in rules["enum"]:
            errors.append(f"{path}: field {field} must be one of {rules['enum']!r}")
    return errors


def validate_json_schema(schema_name: str, path: Path, repo: Path | None = None) -> dict[str, Any]:
    data = load_json_object(path)
    schema_text, schema_source = read_schema(schema_name)
    schema = json.loads(schema_text)
    validator = "minimal"
    errors: list[str] = []
    try:
        import jsonschema  # type: ignore[import-not-found,import-untyped]
    except ImportError:
        errors = minimal_validate(data, schema, path)
    else:
        validator = "jsonschema"
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator_instance = validator_cls(schema)
        errors = [f"{path}: {error.message}" for error in sorted(validator_instance.iter_errors(data), key=str)]

    if schema_name == "gate-config" and not errors:
        config_repo = repo or path.parent
        try:
            load_effective_config(config_repo, path)
        except Exception as exc:  # noqa: BLE001 - convert semantic validation to a schema result.
            errors.append(f"{path}: semantic config validation failed: {exc}")

    return {
        "schema": schema_name,
        "schema_source": schema_source,
        "file": str(path),
        "validator": validator,
        "valid": not errors,
        "errors": errors,
    }
