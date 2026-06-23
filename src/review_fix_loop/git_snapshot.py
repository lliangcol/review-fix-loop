from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .errors import GitError
from .utils import (
    DEFAULT_FILE_HASH_LIMIT_BYTES,
    decode_git_path,
    is_probably_binary,
    normalize_repo_path,
    sha256_json,
    sha256_text,
    stream_file_hash,
)

SCOPES = ["merge_base_to_head", "staged", "unstaged", "untracked"]


def run_git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    command = ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=None, shell=False)
    except OSError as exc:
        raise GitError(f"could not execute git: {exc}") from exc
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git command failed: {' '.join(args)}: {stderr}")
    return result


def resolve_repo(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    if not candidate.exists():
        raise GitError(f"repo path does not exist: {candidate}")
    result = run_git(candidate, ["rev-parse", "--show-toplevel"])
    return Path(result.stdout.decode("utf-8", "replace").strip()).resolve()


def git_path(repo: Path, name: str) -> Path:
    result = run_git(repo, ["rev-parse", "--git-path", name])
    value = result.stdout.decode("utf-8", "replace").strip()
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def parse_name_status_z(data: bytes, scope: str) -> list[dict[str, Any]]:
    tokens = [decode_git_path(token) for token in data.split(b"\0") if token]
    entries: list[dict[str, Any]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not status:
            continue
        status_kind = status[0]
        if status_kind in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise GitError("invalid rename/copy name-status output")
            old_path = normalize_repo_path(tokens[index])
            path = normalize_repo_path(tokens[index + 1])
            index += 2
            entries.append({
                "scope": scope,
                "status": status,
                "status_kind": status_kind,
                "old_path": old_path,
                "path": path,
                "deleted": False,
            })
        else:
            if index >= len(tokens):
                raise GitError("invalid name-status output")
            path = normalize_repo_path(tokens[index])
            index += 1
            entries.append({
                "scope": scope,
                "status": status,
                "status_kind": status_kind,
                "path": path,
                "deleted": status_kind == "D",
            })
    return entries


def staged_blob_ids(repo: Path, paths: list[str]) -> dict[str, str]:
    if not paths:
        return {}
    result = run_git(repo, ["ls-files", "-s", "-z", "--", *paths])
    output = result.stdout
    blobs: dict[str, str] = {}
    for record in output.split(b"\0"):
        if not record:
            continue
        text = decode_git_path(record)
        meta, path = text.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 2:
            blobs[normalize_repo_path(path)] = parts[1]
    return blobs


def head_blob_id(repo: Path, path: str) -> str | None:
    result = run_git(repo, ["rev-parse", f"HEAD:{path}"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def blob_is_binary(repo: Path, blob_id: str | None) -> bool:
    if not blob_id:
        return False
    process = subprocess.Popen(
        ["git", "-C", str(repo), "cat-file", "-p", blob_id],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=None,
        shell=False,
    )
    try:
        sample = process.stdout.read(8192) if process.stdout else b""
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    return b"\0" in sample


def merge_line_ranges(lines: list[int]) -> list[list[int]]:
    if not lines:
        return []
    ranges: list[list[int]] = []
    start = previous = lines[0]
    for line in lines[1:]:
        if line == previous + 1:
            previous = line
            continue
        ranges.append([start, previous])
        start = previous = line
    ranges.append([start, previous])
    return ranges


def merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda item: (item[0], item[1]))
    # Copy the first range so callers' input lists are never mutated in place.
    merged = [list(ordered[0])]
    for start, end in ordered[1:]:
        current = merged[-1]
        if start <= current[1] + 1:
            current[1] = max(current[1], end)
        else:
            merged.append([start, end])
    return merged


def parse_diff_line_ranges(diff_output: bytes) -> tuple[list[list[int]], list[list[int]]]:
    added_lines: list[int] = []
    context_ranges: list[list[int]] = []
    new_line = 0
    for line_text in diff_output.decode("utf-8", "replace").splitlines():
        match = re.match(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@", line_text)
        if match:
            new_line = int(match.group("start"))
            count = int(match.group("count") or "1")
            if count > 0:
                context_ranges.append([new_line, new_line + count - 1])
            continue
        if line_text.startswith("+++") or line_text.startswith("---"):
            continue
        if line_text.startswith("+"):
            added_lines.append(new_line)
            new_line += 1
        elif line_text.startswith("-"):
            continue
        elif line_text.startswith(" "):
            new_line += 1
    return merge_line_ranges(added_lines), merge_ranges(context_ranges)


def diff_line_ranges_for_path(repo: Path, scope: str, path: str, merge_base: str | None = None) -> tuple[list[list[int]], list[list[int]]]:
    if scope == "staged":
        args = ["diff", "--cached", "--unified=3", "--no-ext-diff", "--", path]
    elif scope == "unstaged":
        args = ["diff", "--unified=3", "--no-ext-diff", "--", path]
    elif scope == "merge_base_to_head":
        if not merge_base:
            return [], []
        args = ["diff", "--unified=3", "--no-ext-diff", f"{merge_base}..HEAD", "--", path]
    else:
        return [], []
    result = run_git(repo, args, check=False)
    if result.returncode != 0:
        return [], []
    return parse_diff_line_ranges(result.stdout)


def count_text_lines(path: Path) -> int:
    size = path.stat().st_size
    if size > DEFAULT_FILE_HASH_LIMIT_BYTES:
        return 2_147_483_647
    with path.open("rb") as handle:
        content = handle.read()
    if not content:
        return 1
    return content.count(b"\n") + (0 if content.endswith((b"\n", b"\r")) else 1)


def attach_untracked_ranges(file_path: Path, entry: dict[str, Any]) -> None:
    if entry.get("deleted") or entry.get("binary") or entry.get("symlink"):
        entry["changed_lines"] = []
        entry["diff_context_lines"] = []
        return
    line_count = count_text_lines(file_path)
    entry["changed_lines"] = [[1, line_count]]
    entry["diff_context_lines"] = [[1, line_count]]


def enrich_worktree_entry(repo: Path, entry: dict[str, Any]) -> None:
    path = entry["path"]
    file_path = repo / path
    if file_path.is_symlink():
        entry["deleted"] = False
        entry["binary"] = False
        entry["symlink"] = True
        entry["content_hash"] = "symlink:" + sha256_text(os.readlink(file_path))
        entry["changed_lines"] = []
        entry["diff_context_lines"] = []
        return
    if entry.get("deleted") or not file_path.exists():
        entry["deleted"] = True
        entry["binary"] = False
        entry["content_hash"] = None
        entry["changed_lines"] = []
        entry["diff_context_lines"] = []
        return
    entry["deleted"] = False
    entry["binary"] = is_probably_binary(file_path)
    content_hash, truncated = stream_file_hash(file_path, DEFAULT_FILE_HASH_LIMIT_BYTES)
    entry["content_hash"] = content_hash
    entry["size_bytes"] = file_path.stat().st_size
    if truncated:
        entry["hash_truncated"] = True


def collect_staged(repo: Path) -> list[dict[str, Any]]:
    result = run_git(repo, ["diff", "--cached", "--name-status", "-z"])
    entries = parse_name_status_z(result.stdout, "staged")
    paths = [entry["path"] for entry in entries if not entry.get("deleted")]
    blobs = staged_blob_ids(repo, paths)
    for entry in entries:
        if entry.get("deleted"):
            entry["binary"] = False
            entry["content_hash"] = None
            entry["changed_lines"] = []
            entry["diff_context_lines"] = []
            continue
        blob = blobs.get(entry["path"])
        entry["blob_id"] = blob
        entry["content_hash"] = f"gitblob:{blob}" if blob else None
        entry["binary"] = blob_is_binary(repo, blob)
        entry["changed_lines"], entry["diff_context_lines"] = diff_line_ranges_for_path(repo, "staged", entry["path"])
    return entries


def collect_unstaged(repo: Path) -> list[dict[str, Any]]:
    result = run_git(repo, ["diff", "--name-status", "-z"])
    entries = parse_name_status_z(result.stdout, "unstaged")
    for entry in entries:
        enrich_worktree_entry(repo, entry)
        if not entry.get("deleted"):
            entry["changed_lines"], entry["diff_context_lines"] = diff_line_ranges_for_path(repo, "unstaged", entry["path"])
    return entries


def collect_untracked(repo: Path) -> list[dict[str, Any]]:
    result = run_git(repo, ["ls-files", "--others", "--exclude-standard", "-z"])
    entries = []
    for token in result.stdout.split(b"\0"):
        if not token:
            continue
        path = normalize_repo_path(decode_git_path(token))
        entry: dict[str, Any] = {
            "scope": "untracked",
            "status": "?",
            "status_kind": "?",
            "path": path,
            "deleted": False,
        }
        enrich_worktree_entry(repo, entry)
        attach_untracked_ranges(repo / path, entry)
        entries.append(entry)
    return entries


def collect_merge_base_to_head(repo: Path, baseline: str | None) -> tuple[str, list[dict[str, Any]]]:
    if not baseline:
        raise GitError("large_merge mode requires a baseline")
    merge_base_result = run_git(repo, ["merge-base", baseline, "HEAD"])
    merge_base = merge_base_result.stdout.decode("utf-8", "replace").strip()
    if not merge_base:
        raise GitError(f"could not resolve merge base for baseline: {baseline}")
    result = run_git(repo, ["diff", "--name-status", "-z", f"{merge_base}..HEAD"])
    entries = parse_name_status_z(result.stdout, "merge_base_to_head")
    for entry in entries:
        if entry.get("deleted"):
            entry["binary"] = False
            entry["content_hash"] = None
            entry["changed_lines"] = []
            entry["diff_context_lines"] = []
            continue
        blob = head_blob_id(repo, entry["path"])
        entry["blob_id"] = blob
        entry["content_hash"] = f"gitblob:{blob}" if blob else None
        entry["binary"] = blob_is_binary(repo, blob)
        entry["changed_lines"], entry["diff_context_lines"] = diff_line_ranges_for_path(repo, "merge_base_to_head", entry["path"], merge_base)
    return merge_base, entries


def collect_scopes(repo: Path, mode: str, baseline: str | None, mode_scopes: list[str]) -> tuple[str | None, dict[str, list[dict[str, Any]]]]:
    entries_by_scope = {scope: [] for scope in SCOPES}
    merge_base = None
    if "merge_base_to_head" in mode_scopes:
        merge_base, entries_by_scope["merge_base_to_head"] = collect_merge_base_to_head(repo, baseline)
    if "staged" in mode_scopes:
        entries_by_scope["staged"] = collect_staged(repo)
    if "unstaged" in mode_scopes:
        entries_by_scope["unstaged"] = collect_unstaged(repo)
    if "untracked" in mode_scopes:
        entries_by_scope["untracked"] = collect_untracked(repo)
    return merge_base, entries_by_scope


def compute_scope_hashes(entries_by_scope: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for scope, entries in entries_by_scope.items():
        hashes[scope] = sha256_json(sorted(entries, key=lambda item: (item.get("path", ""), item.get("old_path", ""))))
    return hashes
