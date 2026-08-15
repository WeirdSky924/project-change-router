#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import audit_bundle_governance, route_bundle_from_repo
from router_support.runtime_identity import runtime_identity


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit repository-local project-change-router bundle governance quality.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional JSON report output path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on P0 or P1 governance findings. Without --strict, only P0 findings fail.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    report = audit_bundle_governance(repo_root, bundle)
    report["runtime_identity"] = runtime_identity()
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        counts = report["severity_counts"]
        print(
            "status={status} P0={p0} P1={p1} P2={p2} repair_suggestions={repairs}".format(
                status=report["status"],
                p0=counts["P0"],
                p1=counts["P1"],
                p2=counts["P2"],
                repairs=len(report.get("repair_suggestions", [])),
            )
        )
        for finding in report["findings"][:10]:
            print(f"{finding['severity']} {finding['rule']}: {finding['message']}")
        for suggestion in report.get("repair_suggestions", [])[:5]:
            print(f"repair {suggestion['kind']} {suggestion['target']}: {suggestion['suggestion']}")
    if report["severity_counts"]["P0"]:
        return 1
    if args.strict and report["severity_counts"]["P1"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
