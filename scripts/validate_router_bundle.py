#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import (
    audit_bundle_governance,
    load_bundle,
    resolve_bundle_root,
    schema_dir,
    validate_against_schema,
    validate_bundle_files,
)
from router_support.generated_output_baseline import validate_generated_output_rules
from router_support.profile_loader import load_active_profile


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a repository-local project-change-router bundle against the skill schemas.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle_root = resolve_bundle_root(repo_root)
    errors = validate_bundle_files(bundle_root)
    profile = load_active_profile(repo_root)
    guardrails = profile.get("guardrails", {})
    generated_rules = (
        guardrails.get("generated_output_baseline", [])
        if isinstance(guardrails, dict)
        else guardrails
    )
    errors.extend(
        "generated-output-baseline: " + item
        for item in validate_against_schema(
            generated_rules,
            schema_dir() / "generated-output-baseline.schema.json",
        )
    )
    errors.extend(
        "generated-output-baseline: "
        + str(item.get("diagnostic_code"))
        + ": "
        + str(item.get("message"))
        for item in validate_generated_output_rules(profile, repo_root=repo_root)
    )
    bundle = load_bundle(bundle_root)
    governance = audit_bundle_governance(repo_root, bundle) if bundle else {}
    report = {
        "status": "pass" if not errors else "fail",
        "bundle_root": str(bundle_root),
        "errors": errors,
        "governance": {
            "status": governance.get("status"),
            "severity_counts": governance.get("severity_counts", {}),
            "finding_count": len(governance.get("findings", [])),
        },
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"status={report['status']} errors={len(errors)}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
