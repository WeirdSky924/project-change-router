#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import generate_feedback, record_manual_feedback, resolve_bundle_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate feedback proposals from route and guardrail reports.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--feedback-file", help="Optional JSON file with manual feedback to record.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional report output path.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve()
    bundle_root = resolve_bundle_root(repo_root)
    if args.feedback_file:
        payload = json.loads(Path(args.feedback_file).read_text(encoding="utf-8-sig"))
        report = record_manual_feedback(bundle_root, payload)
    else:
        report = generate_feedback(bundle_root)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        if args.feedback_file:
            print(f"feedback_id={report['feedback_id']} final_action={report['final_action']}")
        else:
            print(f"status={report['status']} proposals={len(report['proposals'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
