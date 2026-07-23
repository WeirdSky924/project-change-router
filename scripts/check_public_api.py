#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import gather_public_api_findings, guardrail_status, route_bundle_from_repo
from router_support.architecture_baseline import filter_architecture_baseline_by_provenance


def main() -> int:
    parser = argparse.ArgumentParser(description="Check public API boundary usage.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument(
        "--comparison-commit",
        help="Trusted commit whose architecture baselines predate this change.",
    )
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    trusted, provenance_findings = filter_architecture_baseline_by_provenance(
        repo_root,
        bundle.get("change_rules", {}).get("architecture_baseline", []),
        args.comparison_commit,
    )
    bundle = dict(bundle)
    bundle["change_rules"] = dict(bundle.get("change_rules", {}))
    bundle["change_rules"]["architecture_baseline"] = trusted
    findings = gather_public_api_findings(repo_root, bundle)
    findings.extend(provenance_findings)
    status, blocking = guardrail_status(findings)
    report = {
        "report_id": "check-public-api",
        "timestamp": bundle["config"]["generated_at"],
        "script": "check_public_api.py",
        "comparison_commit": args.comparison_commit,
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
        print(f"status={report['status']} findings={len(findings)}")
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
