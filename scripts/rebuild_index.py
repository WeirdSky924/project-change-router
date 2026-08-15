#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import rebuild_index
from router_support.runtime_identity import runtime_identity


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild the repository-local router index.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    parser.add_argument(
        "--initialize-generated-output-baseline",
        metavar="FINGERPRINT",
        help=(
            "Authorize one new generated-output pin only when this exact "
            "fingerprint matches the profile at its trusted source commit."
        ),
    )
    args = parser.parse_args()

    report = rebuild_index(
        Path(args.repo).resolve(),
        write_back=True,
        generated_output_initialization_fingerprint=(
            args.initialize_generated_output_baseline
        ),
    )
    report["runtime_identity"] = runtime_identity()
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} modules={report['generated_modules_count']} capabilities={report['curated_entries_count']}")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
