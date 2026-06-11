from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Iterable


DEFAULT_STREAM_LIMIT_BYTES = 8192
DEFAULT_FILE_HASH_LIMIT_BYTES = 10 * 1024 * 1024


def decode_git_path(data: bytes) -> str:
    return data.decode("utf-8", "surrogateescape")


def normalize_repo_path(path: str | os.PathLike[str]) -> str:
    value = os.fspath(path).replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.strip("/")


def stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def sha256_json(data: Any) -> str:
    return sha256_text(stable_json(data))


def stream_file_hash(path: Path, limit_bytes: int | None = None) -> tuple[str, bool]:
    if limit_bytes is not None:
        size = path.stat().st_size
        if size > limit_bytes:
            digest = hashlib.sha256()
            digest.update(f"sampled-size:{size}\0limit:{limit_bytes}\0".encode("ascii"))
            head_size = limit_bytes // 2
            tail_size = limit_bytes - head_size
            with path.open("rb") as handle:
                digest.update(handle.read(head_size))
                if tail_size:
                    handle.seek(max(size - tail_size, 0))
                    digest.update(handle.read(tail_size))
            return "sha256-sample:" + digest.hexdigest(), True

    digest = hashlib.sha256()
    total = 0
    truncated = False
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if limit_bytes is not None and total > limit_bytes:
                remaining = len(chunk) - (total - limit_bytes)
                if remaining > 0:
                    digest.update(chunk[:remaining])
                truncated = True
                break
            digest.update(chunk)
    prefix = "sha256-prefix:" if truncated else "sha256:"
    return prefix + digest.hexdigest(), truncated


def is_probably_binary(path: Path) -> bool:
    if path.is_symlink() or not path.exists() or not path.is_file():
        return False
    with path.open("rb") as handle:
        return b"\0" in handle.read(8192)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    pattern = normalize_repo_path(pattern)
    output = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                i += 2
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
                    output.append("(?:.*/)?")
                else:
                    output.append(".*")
                continue
            output.append("[^/]*")
        elif char == "?":
            output.append("[^/]")
        else:
            output.append(re.escape(char))
        i += 1
    return re.compile("^" + "".join(output) + "$")


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = normalize_repo_path(path)
    return any(glob_to_regex(pattern).match(normalized) for pattern in patterns)


def truncate_text(text: str, limit_bytes: int = DEFAULT_STREAM_LIMIT_BYTES) -> str:
    encoded = text.encode("utf-8", "surrogateescape")
    if len(encoded) <= limit_bytes:
        return text
    # Decode with "ignore" so a multibyte sequence cut by the byte limit cannot
    # leave lone surrogates that later fail UTF-8 serialization.
    clipped = encoded[:limit_bytes].decode("utf-8", "ignore")
    return clipped + f"\n[truncated to {limit_bytes} bytes]"


SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|api[_-]?key)(\s*[=:]\s*)([^\s;&]+)"),
    re.compile(r"(?i)(bearer\s+)([a-z0-9._\-]+)"),
]


def redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(lambda m: m.group(1) + m.group(2) + "[REDACTED]", redacted)
        else:
            redacted = pattern.sub(lambda m: m.group(1) + "[REDACTED]", redacted)
    return redacted


def redact_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_data(item) for item in value]
    return copy.deepcopy(value)
