from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .assets import discover_adapters, read_adapter_config
from .config import load_effective_config
from .domain.types import JsonObject
from .errors import ConfigError, GitError, ReviewFixLoopError, WorkflowError
from .git_snapshot import resolve_repo, run_git
from .i18n import fallback_locale, resolve_locale, translate_message
from .run_record import read_json
from .services.gate_service import execute_gate_request
from .services.schema_service import validate_schema_request
from .services.snapshot_service import create_snapshot_request
from .utils import resolve_repo_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review-fix-loop")
    parser.add_argument("--locale", help="Human-message locale: en or zh-CN")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot", help="Create a live Git review snapshot")
    snapshot.add_argument("--repo", required=True)
    snapshot.add_argument("--config", required=True)
    snapshot.add_argument("--mode", required=True)
    snapshot.add_argument("--baseline")
    snapshot.add_argument("--pass", dest="pass_number", type=int, default=1)
    snapshot.add_argument("--previous-run-record")
    snapshot.add_argument("--final-pass", action="store_true")
    snapshot.add_argument("--write-run-record", action="store_true")
    snapshot.add_argument("--rule-file", action="append", default=[])
    snapshot.add_argument("--no-local-override", action="store_true")
    snapshot.add_argument("--cache-dir")
    snapshot.add_argument("--include-repo-map", action="store_true")
    snapshot.add_argument("--repo-map-limit", type=int, default=40)

    gate = subparsers.add_parser("gate", help="Run gates selected by a snapshot")
    gate.add_argument("--repo", required=True)
    gate.add_argument("--config", required=True)
    gate.add_argument("--snapshot", required=True)
    gate.add_argument("--rule-file", action="append", default=[])
    gate.add_argument("--no-local-override", action="store_true")
    gate.add_argument("--allow-untrusted-gates", action="store_true")
    gate.add_argument("--ci-mode", action="store_true")
    gate.add_argument(
        "--require-fresh-tree",
        action="store_true",
        help="Fail if the working tree no longer matches the snapshot scope hashes. "
        "Leave off when gates intentionally run after fixes were applied.",
    )

    init = subparsers.add_parser("init", help="Create an adapter config in a target repo")
    init.add_argument("--repo", required=True)
    init.add_argument("--adapter", default="generic")
    init.add_argument("--output", default="review-fix-loop.gates.json")
    init.add_argument("--force", action="store_true")

    list_adapters = subparsers.add_parser("list-adapters", help="List built-in and local adapter configs")
    list_adapters.add_argument("--repo")

    validate_config = subparsers.add_parser("validate-config", help="Validate and hash an effective gate config")
    validate_config.add_argument("--repo", required=True)
    validate_config.add_argument("--config", required=True)
    validate_config.add_argument("--rule-file", action="append", default=[])
    validate_config.add_argument("--no-local-override", action="store_true")

    validate_schema = subparsers.add_parser("validate-schema", help="Validate a JSON artifact against a bundled schema")
    validate_schema.add_argument("--schema", required=True, choices=["gate-config", "snapshot", "run-record", "diagnostic"])
    validate_schema.add_argument("--file", required=True)
    validate_schema.add_argument("--repo")

    doctor = subparsers.add_parser("doctor", help="Check local git/config readiness without running gates")
    doctor.add_argument("--repo", required=True)
    doctor.add_argument("--config")
    doctor.add_argument("--rule-file", action="append", default=[])
    doctor.add_argument("--no-local-override", action="store_true")

    inspect = subparsers.add_parser("inspect", help="Summarize a snapshot or run record")
    inspect_input = inspect.add_mutually_exclusive_group(required=True)
    inspect_input.add_argument("--snapshot")
    inspect_input.add_argument("--run-record")
    inspect.add_argument("--format", choices=["json", "markdown"], default="markdown")
    return parser


def snapshot_command(args: argparse.Namespace) -> int:
    result = create_snapshot_request(
        args.repo,
        args.config,
        args.mode,
        args.pass_number,
        args.rule_file,
        baseline=args.baseline,
        previous_run_record=args.previous_run_record,
        final_pass=args.final_pass,
        write_run_record=args.write_run_record,
        apply_local_override=not args.no_local_override,
        cache_dir=args.cache_dir,
        include_repo_map=args.include_repo_map,
        repo_map_limit=args.repo_map_limit,
    )
    print(json.dumps(result.to_json_output(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def gate_command(args: argparse.Namespace) -> int:
    result = execute_gate_request(
        args.repo,
        args.config,
        args.snapshot,
        args.rule_file,
        apply_local_override=not args.no_local_override,
        allow_untrusted_gates=args.allow_untrusted_gates,
        ci_mode=args.ci_mode,
        require_fresh_tree=args.require_fresh_tree,
    )
    print(json.dumps(result.to_json_output(), ensure_ascii=False, indent=2, sort_keys=True))
    return result.exit_status


def init_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    text, source = read_adapter_config(args.adapter, repo)
    output = resolve_repo_file(repo, args.output)
    if output.exists() and not args.force:
        raise WorkflowError(f"output already exists: {output}; pass --force to overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps({
        "adapter": args.adapter,
        "source": source,
        "output": str(output),
        "status": "written",
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def list_adapters_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo) if args.repo else None
    print(json.dumps({"adapters": discover_adapters(repo)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def validate_config_command(args: argparse.Namespace) -> int:
    repo = resolve_repo(args.repo)
    config_path = resolve_repo_file(repo, args.config)
    config, config_hash, rule_hashes, source_info = load_effective_config(
        repo,
        config_path,
        args.rule_file,
        apply_local_override=not args.no_local_override,
    )
    summary = {
        "valid": True,
        "config": str(config_path),
        "config_hash": config_hash,
        "rule_hashes": rule_hashes,
        **source_info,
        "modes": sorted(config.get("modes", {})),
        "slices": len(config.get("slices", [])),
        "gates": [gate["id"] for gate in config.get("gates", [])],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def validate_schema_command(args: argparse.Namespace) -> int:
    result = validate_schema_request(args.schema, args.file, args.repo)
    print(json.dumps(result.to_json_output(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.valid else 1


def doctor_command(args: argparse.Namespace) -> int:
    status: JsonObject = {
        "ok": True,
        "errors": [],
        "warnings": [],
    }
    repo: Path | None = None
    try:
        repo = resolve_repo(args.repo)
        status["repo"] = str(repo)
        version = run_git(repo, ["--version"], check=False).stdout.decode("utf-8", "replace").strip()
        status["git"] = version
    except ReviewFixLoopError as exc:
        status["ok"] = False
        status["errors"].append(str(exc))

    if repo is not None and args.config:
        try:
            config_path = resolve_repo_file(repo, args.config)
            config, config_hash, rule_hashes, source_info = load_effective_config(
                repo,
                config_path,
                args.rule_file,
                apply_local_override=not args.no_local_override,
            )
            status["config"] = str(config_path)
            status["config_hash"] = config_hash
            status["rule_hashes"] = rule_hashes
            status.update(source_info)
            status["gates"] = len(config.get("gates", []))
        except ReviewFixLoopError as exc:
            status["ok"] = False
            status["errors"].append(str(exc))

    print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status["ok"] else 1


def inspect_summary(data: JsonObject, kind: str) -> JsonObject:
    if kind == "snapshot":
        entries = data.get("entries", {})
        return {
            "kind": "snapshot",
            "snapshot_id": data.get("snapshot_id"),
            "mode": data.get("mode"),
            "pass": data.get("pass"),
            "final_pass": data.get("final_pass", False),
            "entries": {scope: len(items) for scope, items in entries.items() if isinstance(items, list)},
            "must_reload": data.get("must_reload", []),
            "planned_gates": data.get("planned_gates", []),
            "reloaded_slices": data.get("reloaded_slices", []),
            "reused_slices": data.get("reused_slices", []),
            "repo_map_files": len(data.get("repo_map", {}).get("files", [])) if isinstance(data.get("repo_map"), dict) else 0,
        }
    return {
        "kind": "run-record",
        "run_id": data.get("run_id"),
        "snapshot_id": data.get("snapshot_id"),
        "mode": data.get("mode"),
        "pass": data.get("pass"),
        "final_pass": data.get("final_pass", False),
        "stop_decision": data.get("stop_decision"),
        "planned_gates": data.get("planned_gates", []),
        "gates": [
            {"id": gate.get("id"), "status": gate.get("status"), "exit_code": gate.get("exit_code")}
            for gate in data.get("gates", [])
            if isinstance(gate, dict)
        ],
        "diagnostics": len(data.get("diagnostics", [])),
    }


def format_markdown_summary(summary: JsonObject) -> str:
    lines = [
        f"# review-fix-loop {summary['kind']}",
        "",
    ]
    for key, value in summary.items():
        if key == "kind":
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) if value else "-"
        elif isinstance(value, dict):
            rendered = ", ".join(f"{item_key}={item_value}" for item_key, item_value in value.items()) if value else "-"
        else:
            rendered = str(value)
        lines.append(f"- {key}: {rendered}")
    return "\n".join(lines)


def inspect_command(args: argparse.Namespace) -> int:
    if args.snapshot:
        path = Path(args.snapshot)
        data = read_json(path)
        summary = inspect_summary(data, "snapshot")
    else:
        path = Path(args.run_record)
        data = read_json(path)
        summary = inspect_summary(data, "run-record")
    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_markdown_summary(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    locale = fallback_locale()
    try:
        args = parser.parse_args(argv)
        locale = resolve_locale(args.locale)
        if args.command == "snapshot":
            return snapshot_command(args)
        if args.command == "gate":
            return gate_command(args)
        if args.command == "init":
            return init_command(args)
        if args.command == "list-adapters":
            return list_adapters_command(args)
        if args.command == "validate-config":
            return validate_config_command(args)
        if args.command == "validate-schema":
            return validate_schema_command(args)
        if args.command == "doctor":
            return doctor_command(args)
        if args.command == "inspect":
            return inspect_command(args)
        parser.error("unknown command")
        return 2
    except (ReviewFixLoopError, ConfigError, GitError, WorkflowError, ValueError) as exc:
        print(f"review-fix-loop: error: {translate_message(str(exc), locale)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
