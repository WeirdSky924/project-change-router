#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import generate_feedback, resolve_bundle_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate feedback proposals from route and guardrail reports.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    report = generate_feedback(resolve_bundle_root(repo_root))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} proposals={len(report['proposals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
