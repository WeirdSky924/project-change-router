#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import freshness_report, route_bundle_from_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Check routing bundle freshness.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    report = freshness_report(repo_root, bundle)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} missing={len(report['missing_references'])}")
    return 2 if report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
