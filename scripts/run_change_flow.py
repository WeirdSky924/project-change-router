#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_support.change_flow import compact_flow_output, run_change_flow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run route, governed checks, incremental evidence classification, and "
            "closeout command planning as one change flow."
        )
    )
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--request", help="Inline change request.")
    parser.add_argument("--request-file", help="UTF-8 file containing the request.")
    parser.add_argument(
        "--changed-path", action="append", default=[], help="Repeatable changed path."
    )
    parser.add_argument("--comparison-commit", help="Trusted comparison commit.")
    parser.add_argument("--runtime-dir", help="External PCR runtime directory.")
    parser.add_argument(
        "--timeout-seconds", type=float, default=60.0, help="Per-check timeout."
    )
    parser.add_argument(
        "--accept-baseline",
        metavar="FINGERPRINT",
        help="Promote the exact current clean, complete candidate snapshot.",
    )
    parser.add_argument(
        "--ci-baseline",
        action="store_true",
        help="Promote a clean complete CI snapshot; requires CI environment.",
    )
    parser.add_argument(
        "--format",
        choices=["compact-json", "full-json", "artifact-reference", "text"],
        default="compact-json",
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        help="Additional compact field. Safety-envelope fields are always retained.",
    )
    parser.add_argument(
        "--exclude-field",
        action="append",
        default=[],
        help="Remove a non-safety compact field; safety-envelope removal is rejected.",
    )
    parser.add_argument("--output", help="Optional output path.")
    args = parser.parse_args()
    if not args.request and not args.request_file:
        parser.error("either --request or --request-file is required")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def main() -> int:
    args = parse_args()
    request_text = (
        args.request
        if args.request is not None
        else Path(args.request_file).read_text(encoding="utf-8")
    )
    report = run_change_flow(
        repo_root=Path(args.repo),
        request_text=request_text,
        changed_paths=args.changed_path,
        comparison_commit=args.comparison_commit,
        runtime_dir=args.runtime_dir,
        timeout_seconds=args.timeout_seconds,
        accept_baseline=args.accept_baseline,
        ci_baseline=args.ci_baseline,
    )
    if args.format == "full-json":
        output = report
    elif args.format == "artifact-reference":
        output = compact_flow_output(report, artifact_reference=True)
    else:
        output = compact_flow_output(
            report,
            fields=args.field or None,
            exclude_fields=args.exclude_field,
        )
    rendered = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    if args.format == "text":
        gate = report["execution_gate"]
        print(
            f"action={report['action']} gate={gate['state']} "
            f"complete={report['output_complete']} artifact={report['artifact_path']}"
        )
        if report["required_commands"]:
            print(f"next: {report['required_commands'][0]}")
    else:
        print(rendered, end="")
    return 2 if report["execution_gate"]["state"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
