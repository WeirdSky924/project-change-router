#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import freshness_report, route_bundle_from_repo
from router_support.freshness_checks import collect_git_changed_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Check routing bundle freshness.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--changed-path", action="append", default=None, help="Repeatable changed path to verify.")
    parser.add_argument("--comparison-commit", help="Include committed changes from this revision through HEAD.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    merged_changes = set(
        collect_git_changed_paths(repo_root, args.comparison_commit)
    )
    merged_changes.update(args.changed_path or [])
    changed_paths = sorted(merged_changes)
    report = freshness_report(repo_root, bundle, changed_paths)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} unmapped={len(report['unmapped_changed_paths'])}")
    return 2 if report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
