#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import guardrail_status, route_bundle_from_repo
from router_support.structure_guardrails import gather_structure_findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check file, tree, central-growth, and ownership structure baselines.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument(
        "--comparison-commit",
        help="Explicit Git commit used as the changed-file and tree-width baseline.",
    )
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    findings = gather_structure_findings(
        repo_root,
        bundle,
        comparison_commit=args.comparison_commit,
    )
    status, blocking = guardrail_status(findings)
    report = {
        "report_id": "check-structure",
        "timestamp": bundle["config"]["generated_at"],
        "script": "check_structure.py",
        "comparison_commit": args.comparison_commit
        or bundle.get("config", {}).get("source_commit"),
        "status": status,
        "blocking": blocking,
        "summary": {"finding_count": len(findings)},
        "findings": findings,
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={status} findings={len(findings)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
