from __future__ import annotations

from importlib import resources
from pathlib import Path

from .errors import WorkflowError

PACKAGE = "review_fix_loop"
PACKAGED_ADAPTERS = {
    "generic": "templates/generic.gates.json",
}
PACKAGED_SCHEMAS = {
    "gate-config": "schemas/gate-config.schema.json",
    "snapshot": "schemas/snapshot.schema.json",
    "run-record": "schemas/run-record.schema.json",
    "diagnostic": "schemas/diagnostic.schema.json",
}


def source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def packaged_text(relative_path: str) -> str:
    return resources.files(PACKAGE).joinpath(relative_path).read_text(encoding="utf-8")


def discover_adapters(repo: Path | None = None) -> list[dict[str, str]]:
    adapters: dict[str, dict[str, str]] = {}
    for name, resource_path in PACKAGED_ADAPTERS.items():
        adapters[name] = {
            "name": name,
            "source": "package",
            "path": resource_path,
        }

    candidates = []
    root = source_root()
    candidates.append(root / "adapters")
    if repo is not None:
        candidates.append(repo / "adapters")
    for adapter_root in candidates:
        if not adapter_root.exists():
            continue
        for gates_path in adapter_root.glob("*/gates.json"):
            name = gates_path.parent.name
            adapters[name] = {
                "name": name,
                "source": "filesystem",
                "path": str(gates_path),
            }
    return sorted(adapters.values(), key=lambda item: item["name"])


def read_adapter_config(adapter: str, repo: Path | None = None) -> tuple[str, str]:
    candidate = Path(adapter)
    if repo is not None and not candidate.is_absolute() and not candidate.exists():
        candidate = repo / candidate
    if candidate.exists():
        path = candidate if candidate.is_file() else candidate / "gates.json"
        if not path.exists():
            raise WorkflowError(f"adapter path does not contain gates.json: {adapter}")
        return path.read_text(encoding="utf-8"), str(path)

    for item in discover_adapters(repo):
        if item["name"] != adapter:
            continue
        adapter_path = item["path"]
        if item["source"] == "package":
            return packaged_text(adapter_path), adapter_path
        return Path(adapter_path).read_text(encoding="utf-8"), adapter_path
    raise WorkflowError(f"unknown adapter: {adapter}")


def read_schema(schema_name: str) -> tuple[str, str]:
    if schema_name not in PACKAGED_SCHEMAS:
        raise WorkflowError(f"unknown schema: {schema_name}")
    resource_path = PACKAGED_SCHEMAS[schema_name]
    return packaged_text(resource_path), resource_path
