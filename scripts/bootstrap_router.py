#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from router_core import bootstrap_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a repository-local project-change-router bundle.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional JSON report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle = bootstrap_bundle(repo_root, write=True)
    report = {
        "status": "pass",
        "bundle_root": str(bundle["root"]),
        "capability_count": len(bundle["capability_catalog"]["capabilities"]),
        "module_count": len(bundle["module_map"]["modules"]),
        "evaluation_case_count": len(bundle["evaluation_set"]["cases"]),
    }
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"Bootstrapped bundle at {report['bundle_root']}")
        print(f"Capabilities: {report['capability_count']}")
        print(f"Modules: {report['module_count']}")
        print(f"Evaluation cases: {report['evaluation_case_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
