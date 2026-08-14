from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any, Callable, Optional


JsonLoader = Callable[[Path], dict[str, Any]]

ROUTE_AUTHORIZATION_FIELDS = (
    "decision_id",
    "request_type",
    "request_summary",
    "changed_paths",
    "repo_stage",
    "action",
    "primary_capability",
    "secondary_capabilities",
    "review_required",
    "block_reason",
    "override_requirements",
    "allowed_write_paths",
    "forbidden_write_paths",
    "must_read_before_edit",
    "source_of_truths",
    "authorization_context",
)


def route_authorization_fingerprint(report: dict[str, Any]) -> str:
    payload = {
        field: report.get(field)
        for field in ROUTE_AUTHORIZATION_FIELDS
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def routing_truth_digest(bundle: dict[str, Any]) -> str:
    payload = {
        key: bundle.get(key, {})
        for key in (
            "config",
            "module_map",
            "capability_catalog",
            "ownership",
            "path_to_capability_map",
            "change_rules",
        )
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _route_report_for_decision(
    bundle_root: Path,
    decision_id: str,
    load_json: JsonLoader,
) -> Optional[dict[str, Any]]:
    reports_root = bundle_root / "reports"
    candidates = list(reports_root.glob("route-*.json"))
    candidates.extend((reports_root / "route-decisions").glob("*.json"))
    matches: list[dict[str, Any]] = []
    for report_path in dict.fromkeys(candidates):
        try:
            report = load_json(report_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if report.get("decision_id") == decision_id:
            matches.append(report)
    if len(matches) > 1:
        raise ValueError("structured authorization references an ambiguous route")
    return matches[0] if matches else None


def authorization_audit_fields(
    bundle_root: Path,
    feedback: dict[str, Any],
    load_json: JsonLoader,
) -> dict[str, Any]:
    raw_authorization_texts = feedback.get("authorization_texts", [])
    raw_allowed_paths = feedback.get("allowed_paths", [])
    if not isinstance(raw_authorization_texts, list):
        raise ValueError("authorization_texts must be a list")
    if not isinstance(raw_allowed_paths, list):
        raise ValueError("allowed_paths must be a list")
    authorization_texts = list(
        dict.fromkeys(str(item) for item in raw_authorization_texts if str(item))
    )
    allowed_paths: list[str] = []
    for item in raw_allowed_paths:
        normalized_path = str(item).replace("\\", "/")
        if (
            normalized_path.startswith("/")
            or re.match(r"^[a-zA-Z]:/", normalized_path)
            or ".." in normalized_path.split("/")
        ):
            raise ValueError("allowed_paths contains an unsafe authorization path")
        if normalized_path and normalized_path not in allowed_paths:
            allowed_paths.append(normalized_path)
    override_reason = str(feedback.get("override_reason", ""))
    expires_after = feedback.get("expires_after")
    structured_authorization = any(
        key in feedback
        for key in (
            "authorization_texts",
            "allowed_paths",
            "override_reason",
            "expires_after",
            "route_fingerprint",
        )
    )
    authorization_status = "not_authorization_evidence"
    override_consumed = False
    if structured_authorization:
        decision_id = feedback.get("decision_id")
        route_report = (
            _route_report_for_decision(bundle_root, str(decision_id), load_json)
            if decision_id
            else None
        )
        if route_report is None:
            raise ValueError("structured authorization must reference an existing route")
        routed_paths = route_report.get("changed_paths")
        if not isinstance(routed_paths, list) or not all(
            isinstance(path, str) for path in routed_paths
        ):
            raise ValueError("referenced route does not persist changed paths")
        if any(
            path.startswith("/")
            or re.match(r"^[a-zA-Z]:/", path)
            or ".." in path.replace("\\", "/").split("/")
            for path in routed_paths
        ):
            raise ValueError("referenced route contains an unsafe changed path")
        report_fingerprint = route_report.get("route_fingerprint")
        if not isinstance(report_fingerprint, str) or not re.fullmatch(
            r"[0-9a-f]{64}", report_fingerprint
        ):
            raise ValueError("referenced route is missing a valid route fingerprint")
        if route_authorization_fingerprint(route_report) != report_fingerprint:
            raise ValueError("referenced route fingerprint does not match its contents")
        provided_fingerprint = feedback.get("route_fingerprint")
        if provided_fingerprint != report_fingerprint:
            raise ValueError("authorization route fingerprint does not match the referenced route")
        authorization_context = route_report.get("authorization_context")
        if not isinstance(authorization_context, dict) or not all(
            isinstance(authorization_context.get(field), str)
            and authorization_context.get(field)
            for field in ("routing_truth_digest", "structure_digest")
        ):
            raise ValueError("referenced route lacks a complete authorization context")
        outside_paths = sorted(set(allowed_paths) - set(routed_paths))
        if outside_paths:
            raise ValueError(
                "authorization path is outside the routed changed paths: "
                + ", ".join(outside_paths)
            )
        requirements = route_report.get("override_requirements", [])
        required_texts = [
            item["required_text"]
            for item in requirements
            if isinstance(item, dict) and item.get("required_text")
        ]
        if any(text not in authorization_texts for text in required_texts):
            raise ValueError("missing required authorization text")
        if any(item.get("must_record_reason") for item in requirements):
            if not override_reason.strip():
                raise ValueError("override_reason is required by the referenced route")
        if any(item.get("scope") == "paths" for item in requirements):
            if not allowed_paths:
                raise ValueError("allowed_paths is required by the referenced route")
        required_expirations = {
            item.get("expires_after")
            for item in requirements
            if item.get("expires_after")
        }
        if required_expirations and not expires_after:
            raise ValueError("expires_after is required by the referenced route")
        if "current_task" in required_expirations and expires_after != "current_task":
            raise ValueError("expires_after exceeds the referenced route scope")
        if requirements:
            authorization_status = "consumed_for_route_only"
            override_consumed = True
        else:
            authorization_status = "matched_route_no_override_required"
    return {
        "authorization_texts": authorization_texts,
        "allowed_paths": allowed_paths,
        "override_reason": override_reason,
        "expires_after": expires_after,
        "route_fingerprint": feedback.get("route_fingerprint"),
        "authorization_status": authorization_status,
        "override_consumed": override_consumed,
    }
