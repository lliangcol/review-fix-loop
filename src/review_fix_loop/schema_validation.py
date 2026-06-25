from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .assets import read_schema
from .config import load_effective_config
from .domain.types import JsonObject
from .errors import WorkflowError

SchemaObject = JsonObject
ValidationResult = JsonObject


def load_json_object(path: Path) -> SchemaObject:
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


def string_items(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, str)]
    return []


def object_properties(value: object) -> list[tuple[str, SchemaObject]]:
    if not isinstance(value, Mapping):
        return []
    return [(key, item) for key, item in value.items() if isinstance(key, str) and isinstance(item, dict)]


def minimal_validate(data: SchemaObject, schema: SchemaObject, path: Path) -> list[str]:
    errors = []
    for field in string_items(schema.get("required", [])):
        if field not in data:
            errors.append(f"{path}: missing required field: {field}")
    for field, rules in object_properties(schema.get("properties", {})):
        if field not in data:
            continue
        if "const" in rules and data[field] != rules["const"]:
            errors.append(f"{path}: field {field} must be {rules['const']!r}")
        if "enum" in rules and data[field] not in rules["enum"]:
            errors.append(f"{path}: field {field} must be one of {rules['enum']!r}")
    return errors


def validate_json_schema(schema_name: str, path: Path, repo: Path | None = None) -> ValidationResult:
    data = load_json_object(path)
    schema_text, schema_source = read_schema(schema_name)
    schema = json.loads(schema_text)
    if not isinstance(schema, dict):
        raise WorkflowError(f"bundled schema is not a JSON object: {schema_source}")
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
