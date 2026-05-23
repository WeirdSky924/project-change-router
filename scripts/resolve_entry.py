#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from router_core import build_route_report, load_bundle, resolve_bundle_root, resolve_request, route_bundle_from_repo


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a routed code entry for a repository change request.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--request", help="Inline request text.")
    parser.add_argument("--request-file", help="Path to a file containing request text.")
    parser.add_argument("--changed-path", action="append", default=[], help="Repeatable changed path hints.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional route report output file.")
    args = parser.parse_args()

    if not args.request and not args.request_file:
        raise SystemExit("Either --request or --request-file is required.")
    request_text = args.request or Path(args.request_file).read_text(encoding="utf-8")
    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    decision = resolve_request(request_text, args.changed_path, bundle, resolve_bundle_root(repo_root))
    report = build_route_report(decision)
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"action={decision.action} confidence={decision.confidence} primary={decision.primary_capability}")
        for path in decision.required_reads:
            print(f"read: {path}")
    return 0 if not decision.review_required else 2


if __name__ == "__main__":
    raise SystemExit(main())
