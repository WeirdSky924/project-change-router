#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import gather_dependency_findings, route_bundle_from_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Check architectural dependency direction against the module map.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    findings = gather_dependency_findings(repo_root, bundle)
    blocking = any(finding["severity"] in {"P0", "P1"} for finding in findings)
    report = {
        "report_id": "check-deps",
        "timestamp": bundle["config"]["generated_at"],
        "script": "check_deps.py",
        "status": "fail" if blocking else "pass",
        "blocking": blocking,
        "summary": {"finding_count": len(findings)},
        "findings": findings,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} findings={len(findings)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
