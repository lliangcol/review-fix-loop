from __future__ import annotations

from pathlib import Path
from typing import Any

from ..gates import run_planned_gates


def execute_planned_gates(
    repo: Path,
    config: dict[str, Any],
    snapshot: dict[str, Any],
    snapshot_path: Path,
    *,
    allow_untrusted_gates: bool = False,
    ci_mode: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    return run_planned_gates(
        repo,
        config,
        snapshot,
        snapshot_path,
        allow_untrusted_gates=allow_untrusted_gates,
        ci_mode=ci_mode,
    )
