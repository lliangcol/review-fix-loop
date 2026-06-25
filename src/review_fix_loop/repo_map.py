from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict


class PythonSymbol(TypedDict):
    kind: str
    name: str
    line: int


class RepoMapFile(TypedDict):
    path: str
    symbols: list[PythonSymbol]


class RepoMap(TypedDict):
    schema: int
    kind: str
    max_files: int
    truncated: bool
    files: list[RepoMapFile]


SnapshotEntry = Mapping[str, object]
EntriesByScope = Mapping[str, Sequence[SnapshotEntry]]


def changed_snapshot_paths(entries_by_scope: EntriesByScope) -> list[str]:
    paths: list[str] = []
    for entries in entries_by_scope.values():
        for entry in entries:
            path = entry.get("path")
            if isinstance(path, str) and path and path not in paths and not entry.get("deleted"):
                paths.append(path)
    return sorted(paths)


def python_symbols(path: Path) -> list[PythonSymbol]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    symbols: list[PythonSymbol] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            symbols.append({"kind": "class", "name": node.name, "line": node.lineno})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols.append({"kind": "function", "name": node.name, "line": node.lineno})
    return sorted(symbols, key=lambda item: (item["line"], item["kind"], item["name"]))


def build_repo_map(
    repo: Path,
    entries_by_scope: EntriesByScope,
    max_files: int = 40,
) -> RepoMap:
    paths: list[str] = [path for path in changed_snapshot_paths(entries_by_scope) if path.endswith(".py")]
    files: list[RepoMapFile] = []
    truncated = False
    for path in paths:
        if len(files) >= max_files:
            truncated = True
            break
        absolute = repo / path
        if not absolute.exists() or not absolute.is_file() or absolute.stat().st_size > 1_000_000:
            continue
        files.append({
            "path": path,
            "symbols": python_symbols(absolute),
        })
    return {
        "schema": 1,
        "kind": "python-symbols",
        "max_files": max_files,
        "truncated": truncated,
        "files": files,
    }
