from __future__ import annotations

from typing import Any, TypedDict


class FreshnessResult(TypedDict, total=False):
    previous_snapshot_id: str | None
    must_reload: list[str]
    reloaded_slices: list[str]
    reused_slices: list[str]
    reuse_forbidden_slices: dict[str, list[str]]


JsonObject = dict[str, Any]
