#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import (
    build_write_ready_router_bundle,
    guardrail_status,
    route_bundle_from_repo,
)
from router_support.profile_loader import load_active_profile
from router_support.generated_output_baseline.write_policy import (
    generated_output_write_policy,
)
from router_support.structure_guardrails import gather_structure_findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check file, tree, central-growth, and ownership structure baselines.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument(
        "--comparison-commit",
        help="Explicit Git commit used as the changed-file and tree-width baseline.",
    )
    parser.add_argument(
        "--initialize-generated-output-baseline",
        metavar="FINGERPRINT",
        help=(
            "Authorize one new generated-output pin only when this exact fingerprint "
            "matches the profile and its source commit is the comparison commit."
        ),
    )
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    profile = load_active_profile(repo_root)
    has_generated_baseline = generated_output_write_policy(
        repo_root,
        profile,
    ).protected
    generated_output_evidence = []
    expected_generated_bundle = None
    generated_output_rebuild_error = None
    if has_generated_baseline:
        try:
            expected_generated_bundle = build_write_ready_router_bundle(repo_root)
        except Exception as exc:
            generated_output_rebuild_error = f"{type(exc).__name__}: {exc}"
    findings = gather_structure_findings(
        repo_root,
        bundle,
        comparison_commit=args.comparison_commit,
        expected_generated_bundle=expected_generated_bundle,
        generated_output_evidence=generated_output_evidence,
        generated_output_initialization_fingerprint=(
            args.initialize_generated_output_baseline
        ),
        generated_output_rebuild_error=generated_output_rebuild_error,
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
        "generated_output_evidence": generated_output_evidence,
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
