from __future__ import annotations

from typing import Any

from .utils import matches_any, normalize_repo_path, sha256_json


UNCATEGORIZED = "__uncategorized__"


def assign_slice(path: str, slices: list[dict[str, Any]]) -> str:
    normalized = normalize_repo_path(path)
    for item in slices:
        if matches_any(normalized, item.get("paths", [])):
            return item["id"]
    return UNCATEGORIZED


def attach_slices(entries_by_scope: dict[str, list[dict[str, Any]]], slices: list[dict[str, Any]]) -> None:
    for entries in entries_by_scope.values():
        for entry in entries:
            entry["slice"] = assign_slice(entry.get("path", ""), slices)


def compute_slice_hashes(entries_by_scope: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    by_slice: dict[str, list[dict[str, Any]]] = {}
    for scope, entries in entries_by_scope.items():
        for entry in entries:
            slice_id = entry.get("slice", UNCATEGORIZED)
            normalized = {key: value for key, value in entry.items() if key not in {"slice"}}
            normalized["scope"] = scope
            by_slice.setdefault(slice_id, []).append(normalized)
    return {
        slice_id: sha256_json(sorted(entries, key=lambda item: (item.get("scope", ""), item.get("path", ""), item.get("old_path", ""))))
        for slice_id, entries in sorted(by_slice.items())
    }


def paths_by_slice(entries_by_scope: dict[str, list[dict[str, Any]]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for entries in entries_by_scope.values():
        for entry in entries:
            result.setdefault(entry.get("slice", UNCATEGORIZED), [])
            path = entry.get("path")
            if path and path not in result[entry.get("slice", UNCATEGORIZED)]:
                result[entry.get("slice", UNCATEGORIZED)].append(path)
    return result

