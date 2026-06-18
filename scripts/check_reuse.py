#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import gather_reuse_report, route_bundle_from_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect duplicate implementations and forbidden reuse bypasses.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--changed-path", action="append", default=[], help="Optional changed path filters.")
    parser.add_argument("--max-candidate-files", type=int, help="Maximum changed or full-scan candidate files.")
    parser.add_argument("--max-owner-files", type=int, help="Maximum owner files scanned per capability.")
    parser.add_argument("--max-comparisons", type=int, help="Maximum full-text similarity comparisons.")
    parser.add_argument("--max-file-bytes", type=int, help="Maximum file size eligible for full similarity.")
    parser.add_argument("--top-k-owner-files", type=int, help="Maximum prefiltered owner files compared per candidate and capability.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    budget_overrides = {
        "max_candidate_files": args.max_candidate_files,
        "max_owner_files_per_capability": args.max_owner_files,
        "max_comparisons": args.max_comparisons,
        "max_file_bytes_for_full_similarity": args.max_file_bytes,
        "top_k_owner_files_per_candidate": args.top_k_owner_files,
    }
    budget_overrides = {key: value for key, value in budget_overrides.items() if value is not None}
    reuse_report = gather_reuse_report(repo_root, bundle, args.changed_path or None, budget_overrides)
    findings = reuse_report["findings"]
    blocking = any(finding["severity"] in {"P0", "P1"} for finding in findings)
    incomplete = reuse_report["scan"].get("status") != "complete"
    report = {
        "report_id": "check-reuse",
        "timestamp": bundle["config"]["generated_at"],
        "script": "check_reuse.py",
        "status": "fail" if blocking else "warn" if incomplete else "pass",
        "blocking": blocking,
        "summary": {"finding_count": len(findings), "scan": reuse_report["scan"]},
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
