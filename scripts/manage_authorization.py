#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reuse_runtime import runtime_root_for_repo
from router_core import route_bundle_from_repo
from router_support.authorization_manifest import AuthorizationManifestStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create, grant, consume, or inspect task-bound PCR authorization manifests."
    )
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--runtime-dir", help="External PCR runtime directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    request = subparsers.add_parser("request")
    request.add_argument("--route-report", required=True)

    grant = subparsers.add_parser("grant")
    grant.add_argument("--request-id", required=True)
    grant.add_argument("--authorization-source", required=True)
    grant.add_argument(
        "--max-uses",
        type=int,
        default=1,
        help="Explicit bounded use count; defaults to one.",
    )
    grant.add_argument(
        "--expires-at",
        help="ISO-8601 expiry; defaults to 24 hours and cannot exceed 30 days.",
    )
    grant_group = grant.add_mutually_exclusive_group(required=True)
    grant_group.add_argument("--confirmation")
    grant_group.add_argument("--confirmation-file")

    consume = subparsers.add_parser("consume")
    consume.add_argument("--grant-id", required=True)
    consume.add_argument("--route-report", required=True)

    inspect = subparsers.add_parser("inspect")
    inspect.add_argument("--grant-id", required=True)
    return parser.parse_args()


def _report(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("route report must be an object")
    return value


def _context(document: dict) -> dict:
    route = document.get("route_report", document)
    request = document.get("authorization_request") or route.get(
        "authorization_request", {}
    )
    if isinstance(request.get("context"), dict):
        return dict(request["context"])
    gate = route.get("execution_gate", {})
    return {
        "route_fingerprint": route.get("route_fingerprint"),
        "pre_change_snapshot": request.get("pre_change_snapshot"),
        "task_id": route.get("decision_id", ""),
        "paths": route.get("changed_paths", []),
        "owner": request.get("owner", ""),
        "canonical_root": request.get("canonical_root", ""),
        "route": route.get("action", "review"),
        "mutation_envelope": {
            "allowed_write_paths": gate.get(
                "proposed_allowed_write_paths", route.get("allowed_write_paths", [])
            ),
            "forbidden_write_paths": gate.get(
                "proposed_forbidden_write_paths", route.get("forbidden_write_paths", [])
            ),
        },
    }


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    runtime_root = runtime_root_for_repo(repo_root, bundle, args.runtime_dir)
    store = AuthorizationManifestStore(runtime_root)

    if args.command == "request":
        result = store.create_request(_context(_report(args.route_report)))
    elif args.command == "grant":
        confirmation = args.confirmation or Path(args.confirmation_file).read_text(
            encoding="utf-8"
        )
        result = store.grant(
            args.request_id,
            authorization_source=args.authorization_source,
            confirmation=confirmation,
            max_uses=args.max_uses,
            expires_at=args.expires_at,
        )
    elif args.command == "consume":
        result = store.consume(args.grant_id, _context(_report(args.route_report)))
    else:
        result = store.get_grant(args.grant_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
