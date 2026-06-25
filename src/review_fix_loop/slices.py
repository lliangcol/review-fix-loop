from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence

from .utils import matches_any, normalize_repo_path, sha256_json


UNCATEGORIZED = "__uncategorized__"
SliceConfig = Mapping[str, object]
SnapshotEntry = MutableMapping[str, object]
EntriesByScope = Mapping[str, Sequence[SnapshotEntry]]


def string_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, str)]
    return []


def string_value(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def assign_slice(path: str, slices: Sequence[SliceConfig]) -> str:
    normalized = normalize_repo_path(path)
    for item in slices:
        if matches_any(normalized, string_list(item.get("paths", []))):
            return string_value(item.get("id"), UNCATEGORIZED)
    return UNCATEGORIZED


def attach_slices(entries_by_scope: EntriesByScope, slices: Sequence[SliceConfig]) -> None:
    for entries in entries_by_scope.values():
        for entry in entries:
            entry["slice"] = assign_slice(string_value(entry.get("path")), slices)


def compute_slice_hashes(entries_by_scope: EntriesByScope) -> dict[str, str]:
    by_slice: dict[str, list[dict[str, object]]] = {}
    for scope, entries in entries_by_scope.items():
        for entry in entries:
            slice_id = string_value(entry.get("slice"), UNCATEGORIZED)
            normalized = {key: value for key, value in entry.items() if key not in {"slice"}}
            normalized["scope"] = scope
            by_slice.setdefault(slice_id, []).append(normalized)
    return {
        slice_id: sha256_json(sorted(
            entries,
            key=lambda item: (
                string_value(item.get("scope")),
                string_value(item.get("path")),
                string_value(item.get("old_path")),
            ),
        ))
        for slice_id, entries in sorted(by_slice.items())
    }


def paths_by_slice(entries_by_scope: EntriesByScope) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entries in entries_by_scope.values():
        for entry in entries:
            slice_id = string_value(entry.get("slice"), UNCATEGORIZED)
            result.setdefault(slice_id, [])
            path = entry.get("path")
            if isinstance(path, str) and path not in result[slice_id]:
                result[slice_id].append(path)
    return result
