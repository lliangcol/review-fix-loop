from __future__ import annotations

from pathlib import Path

from ..domain.types import SchemaValidationRequest, SchemaValidationResult
from ..git_snapshot import resolve_repo
from ..schema_validation import validate_json_schema
from ..utils import resolve_repo_file


def validate_schema_request(
    schema_name: str,
    file_value: str,
    repo_value: str | None = None,
) -> SchemaValidationResult:
    return validate_schema_from_request(SchemaValidationRequest(
        schema_name=schema_name,
        file=file_value,
        repo=repo_value,
    ))


def validate_schema_from_request(request: SchemaValidationRequest) -> SchemaValidationResult:
    repo = None
    if request.repo:
        repo = resolve_repo(request.repo)
        path = resolve_repo_file(repo, request.file)
    else:
        path = Path(request.file).resolve()
    return SchemaValidationResult(validate_json_schema(request.schema_name, path, repo))
