from __future__ import annotations

import json
import re
# Parses bounded local gate output without adding runtime dependencies.
import xml.etree.ElementTree as ET  # nosec B405
from typing import Any

SEVERITY_ORDER = {"none": 0, "info": 1, "warning": 2, "error": 3}
VALID_DIAGNOSTIC_SEVERITIES = set(SEVERITY_ORDER)


def normalize_severity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized == "note":
        normalized = "info"
    if normalized in VALID_DIAGNOSTIC_SEVERITIES:
        return normalized
    return None


def severity_at_least(severity: str, fail_level: str) -> bool:
    normalized = normalize_severity(severity) or "error"
    return SEVERITY_ORDER[normalized] >= SEVERITY_ORDER[fail_level] and fail_level != "none"


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
        "severity": normalize_severity(severity) or severity,
        "rule": rule,
        "file": file,
        "line": line,
        "column": column,
        "message": message,
        "scope": scope,
        "slice": slice_id,
        "blocking": blocking,
    }


def invalid_severity_diagnostic(
    *,
    tool: str,
    raw_severity: Any,
    scope: str,
    blocking: bool,
    file: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    return normalize_diagnostic(
        tool=tool,
        severity="error",
        rule="invalid-severity",
        file=file,
        line=line,
        message=f"Invalid diagnostic severity: {raw_severity!r}",
        scope=scope,
        blocking=blocking,
    )


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_git_diff_check(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
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
        severity = groups.get("severity") or default_severity
        normalized_severity = normalize_severity(severity)
        if normalized_severity is None:
            diagnostics.append(invalid_severity_diagnostic(
                tool=gate_id,
                raw_severity=severity,
                file=groups.get("file"),
                line=_int_or_none(groups.get("line")),
                scope=scope,
                blocking=blocking,
            ))
            continue
        diagnostics.append(normalize_diagnostic(
            tool=gate_id,
            severity=normalized_severity,
            rule=groups.get("rule"),
            file=groups.get("file"),
            line=_int_or_none(groups.get("line")),
            column=_int_or_none(groups.get("column")),
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
        severity = item.get("severity", "error")
        normalized_severity = normalize_severity(severity)
        if normalized_severity is None:
            diagnostics.append(invalid_severity_diagnostic(
                tool=item.get("tool", gate_id),
                raw_severity=severity,
                file=item.get("file"),
                line=_int_or_none(item.get("line")),
                scope=item.get("scope", scope),
                blocking=blocking,
            ))
            continue
        diagnostics.append(normalize_diagnostic(
            tool=item.get("tool", gate_id),
            severity=normalized_severity,
            rule=item.get("rule"),
            file=item.get("file"),
            line=_int_or_none(item.get("line")),
            column=_int_or_none(item.get("column")),
            message=item.get("message", ""),
            scope=item.get("scope", scope),
            slice_id=item.get("slice"),
            blocking=item.get("blocking", blocking),
        ))
    return diagnostics


def parse_rdjson(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="rdjson",
            message=f"Could not parse RDJSON diagnostics: {exc}",
            scope=scope,
            blocking=blocking,
        )]
    raw_items = data.get("diagnostics", []) if isinstance(data, dict) else data
    if not isinstance(raw_items, list):
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="rdjson",
            message="RDJSON output must be a diagnostics list or an object with a diagnostics list",
            scope=scope,
            blocking=blocking,
        )]
    diagnostics = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        location = item.get("location", {}) if isinstance(item.get("location"), dict) else {}
        range_data = location.get("range", {}) if isinstance(location.get("range"), dict) else {}
        start = range_data.get("start", {}) if isinstance(range_data.get("start"), dict) else {}
        code = item.get("code", {}) if isinstance(item.get("code"), dict) else {}
        severity = item.get("severity", "error")
        normalized_severity = normalize_severity(severity)
        file = location.get("path") if isinstance(location.get("path"), str) else item.get("file")
        line = _int_or_none(start.get("line") if start else item.get("line"))
        if normalized_severity is None:
            diagnostics.append(invalid_severity_diagnostic(
                tool=gate_id,
                raw_severity=severity,
                file=file,
                line=line,
                scope=scope,
                blocking=blocking,
            ))
            continue
        diagnostics.append(normalize_diagnostic(
            tool=gate_id,
            severity=normalized_severity,
            rule=code.get("value") if isinstance(code.get("value"), str) else item.get("rule"),
            file=file,
            line=line,
            column=_int_or_none(start.get("column") if start else item.get("column")),
            message=str(item.get("message", "")),
            scope=scope,
            blocking=blocking,
        ))
    return diagnostics


def parse_sarif(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="sarif",
            message=f"Could not parse SARIF diagnostics: {exc}",
            scope=scope,
            blocking=blocking,
        )]
    runs = data.get("runs", []) if isinstance(data, dict) else []
    if not isinstance(runs, list):
        runs = []
    diagnostics = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        results = run.get("results", [])
        if not isinstance(results, list):
            continue
        for result in results:
            if not isinstance(result, dict):
                continue
            location: dict[str, Any] = {}
            locations = result.get("locations", [])
            if isinstance(locations, list) and locations and isinstance(locations[0], dict):
                location = locations[0].get("physicalLocation", {}) if isinstance(locations[0].get("physicalLocation"), dict) else {}
            artifact = location.get("artifactLocation", {}) if isinstance(location.get("artifactLocation"), dict) else {}
            region = location.get("region", {}) if isinstance(location.get("region"), dict) else {}
            message = result.get("message", {})
            message_text = message.get("text", "") if isinstance(message, dict) else str(message)
            severity = result.get("level", "error")
            normalized_severity = normalize_severity(severity)
            file = artifact.get("uri") if isinstance(artifact.get("uri"), str) else None
            line = _int_or_none(region.get("startLine"))
            if normalized_severity is None:
                diagnostics.append(invalid_severity_diagnostic(
                    tool=gate_id,
                    raw_severity=severity,
                    file=file,
                    line=line,
                    scope=scope,
                    blocking=blocking,
                ))
                continue
            diagnostics.append(normalize_diagnostic(
                tool=gate_id,
                severity=normalized_severity,
                rule=result.get("ruleId"),
                file=file,
                line=line,
                column=_int_or_none(region.get("startColumn")),
                message=message_text,
                scope=scope,
                blocking=blocking,
            ))
    return diagnostics


def parse_checkstyle(output: str, gate_id: str, scope: str, blocking: bool) -> list[dict[str, Any]]:
    if not output.strip():
        return []
    try:
        # Gate output is captured and bounded before parsing.
        root = ET.fromstring(output)  # nosec B314
    except ET.ParseError as exc:
        return [normalize_diagnostic(
            tool=gate_id,
            severity="error",
            rule="checkstyle",
            message=f"Could not parse Checkstyle diagnostics: {exc}",
            scope=scope,
            blocking=blocking,
        )]
    diagnostics = []
    for file_node in root.findall(".//file"):
        file_name = file_node.attrib.get("name")
        for error_node in file_node.findall("error"):
            severity = error_node.attrib.get("severity", "error")
            normalized_severity = normalize_severity(severity)
            line = _int_or_none(error_node.attrib.get("line"))
            if normalized_severity is None:
                diagnostics.append(invalid_severity_diagnostic(
                    tool=gate_id,
                    raw_severity=severity,
                    file=file_name,
                    line=line,
                    scope=scope,
                    blocking=blocking,
                ))
                continue
            diagnostics.append(normalize_diagnostic(
                tool=gate_id,
                severity=normalized_severity,
                rule=error_node.attrib.get("source"),
                file=file_name,
                line=line,
                column=_int_or_none(error_node.attrib.get("column")),
                message=error_node.attrib.get("message", ""),
                scope=scope,
                blocking=blocking,
            ))
    return diagnostics
