from __future__ import annotations

import json
import re
from typing import Any

SEVERITY_ORDER = {"none": 0, "info": 1, "warning": 2, "error": 3}


def severity_at_least(severity: str, fail_level: str) -> bool:
    return SEVERITY_ORDER.get(severity, 0) >= SEVERITY_ORDER.get(fail_level, 0) and fail_level != "none"


def normalize_diagnostic(
    *,
    tool: str,
    severity: str,
    message: str,
    scope: str,
    blocking: bool,
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    rule: str | None = None,
    slice_id: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "severity": severity,
        "rule": rule,
        "file": file,
        "line": line,
        "column": column,
        "message": message,
        "scope": scope,
        "slice": slice_id,
        "blocking": blocking,
    }


def parse_git_diff_check(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    diagnostics = []
    for line_text in output.splitlines():
        match = re.match(r"^(?P<file>.*?):(?P<line>\d+):(?P<message>.*)$", line_text)
        if not match:
            continue
        diagnostics.append(normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="git-diff-check",
            file=match.group("file"),
            line=int(match.group("line")),
            message=match.group("message").strip(),
            scope=scope,
            blocking=blocking,
        ))
    return diagnostics


def parse_regex_lines(output: str, parser: dict[str, Any], gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    pattern = re.compile(parser["pattern"])
    default_severity = parser.get("severity", "error")
    diagnostics = []
    for line_text in output.splitlines():
        match = pattern.match(line_text)
        if not match:
            continue
        groups = match.groupdict()
        diagnostics.append(normalize_diagnostic(
            tool=gate_id,
            severity=groups.get("severity") or default_severity,
            rule=groups.get("rule"),
            file=groups.get("file"),
            line=int(groups["line"]) if groups.get("line") else None,
            column=int(groups["column"]) if groups.get("column") else None,
            message=groups.get("message") or line_text,
            scope=scope,
            blocking=blocking,
        ))
    return diagnostics


def parse_json_diagnostics(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="json-diagnostics",
            message=f"Could not parse JSON diagnostics: {exc}",
            scope=scope,
            blocking=blocking,
        )]
    raw_items = data.get("diagnostics", []) if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="json-diagnostics",
            message="JSON diagnostics output must be a list or an object with a diagnostics list",
            scope=scope,
            blocking=blocking,
        )]
    diagnostics = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        diagnostics.append(normalize_diagnostic(
            tool=item.get("tool", gate_id),
            severity=item.get("severity", "error"),
            rule=item.get("rule"),
            file=item.get("file"),
            line=item.get("line"),
            column=item.get("column"),
            message=item.get("message", ""),
            scope=item.get("scope", scope),
            slice_id=item.get("slice"),
            blocking=item.get("blocking", blocking),
        ))
    return diagnostics
