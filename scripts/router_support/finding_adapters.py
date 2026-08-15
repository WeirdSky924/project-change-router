from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from router_support.typed_findings import TypedFinding


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int))]
    return []


def _paths(raw: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in (
        "path",
        "source",
        "target",
        "source_file",
        "owner_path",
        "file",
        "paths",
        "unresolved_paths",
    ):
        values.extend(_strings(raw.get(key)))
    details = raw.get("details")
    if isinstance(details, Mapping):
        for key in ("path", "paths", "unresolved_paths", "unmapped"):
            values.extend(_strings(details.get(key)))
    return sorted(
        {
            value.replace("\\", "/").strip("/")
            for value in values
            if value and not value.startswith("<")
        }
    )


def _capabilities(raw: Mapping[str, Any]) -> list[str]:
    values = _strings(raw.get("capabilities"))
    values.extend(_strings(raw.get("capability")))
    return sorted(set(value for value in values if value))


def _finding_type(origin: str, rule: str, raw: Mapping[str, Any]) -> str:
    lowered = f"{rule} {raw.get('diagnostic_code', '')}".lower()
    existing_debt = (
        raw.get("baseline_status") == "existing_debt"
        and raw.get("blocking") is False
    )
    if existing_debt and (
        "dynamic" in lowered or "unresolved-import" in lowered
    ):
        return "historical_dynamic_import_debt"
    if "dynamic" in lowered or "unresolved-import" in lowered:
        return "dynamic_import_unknown"
    if "duplicate-owner" in lowered or "owner-conflict" in lowered:
        return "duplicate_owner"
    if "generated-output" in lowered or "pin" in lowered:
        return "generated_output_pin_invalid"
    if existing_debt and origin == "public_api":
        return "historical_public_api_debt"
    if origin == "public_api" or "public-api" in lowered or "private" in lowered:
        return "public_export_conflict"
    if origin == "reuse" and "duplicate" in lowered:
        channels = set(_strings(raw.get("channels")))
        return (
            "cross_capability_duplicate"
            if channels & {"cross_capability", "extended"}
            else "duplicate_implementation"
        )
    if origin == "reuse" and (
        "incomplete" in lowered or "scope" in lowered or "surface-missing" in lowered
    ):
        return "reuse_evidence_incomplete"
    if origin == "dependency":
        return "dependency_violation"
    if origin == "structure":
        return "structure_violation"
    if origin == "governance":
        return "governance_violation"
    return rule.replace("-", "_") or f"{origin}_finding"


def _invariant_class(origin: str, finding_type: str) -> str:
    if finding_type in {
        "duplicate_owner",
        "generated_output_pin_invalid",
        "public_export_conflict",
    }:
        return "always_global"
    if origin in {"dependency", "public_api", "freshness"}:
        return "closure_global"
    return "task_local"


def _intersects(route_paths: set[str], finding_paths: list[str]) -> bool:
    return any(
        left == right
        or left.startswith(f"{right.rstrip('/')}/")
        or right.startswith(f"{left.rstrip('/')}/")
        for left in route_paths
        for right in finding_paths
    )


def _relevance_trace(
    route_paths: set[str],
    finding_paths: list[str],
    route_capabilities: set[str],
    finding_capabilities: list[str],
    finding_type: str,
) -> list[str]:
    traces = [
        f"path:{route_path} -> path:{finding_path} -> finding:{finding_type}"
        for route_path in sorted(route_paths)
        for finding_path in finding_paths
        if _intersects({route_path}, [finding_path])
    ]
    traces.extend(
        f"capability:{capability} -> finding:{finding_type}"
        for capability in sorted(route_capabilities & set(finding_capabilities))
    )
    return traces


def adapt_check_report(
    origin: str,
    report: Mapping[str, Any],
    *,
    route_paths: Iterable[str],
    route_capabilities: Iterable[str],
    route_scope_paths: Iterable[str] = (),
) -> list[TypedFinding]:
    normalized_route_paths = {
        str(path).replace("\\", "/").strip("/") for path in route_paths if path
    }
    normalized_route_capabilities = {str(value) for value in route_capabilities if value}
    normalized_route_scope_paths = normalized_route_paths | {
        str(path).replace("\\", "/").strip("/")
        for path in route_scope_paths
        if path
    }
    completion = str(report.get("completion_status", "complete"))
    output_complete = bool(report.get("evidence_complete", completion == "complete"))
    findings: list[TypedFinding] = []
    raw_findings = report.get("findings", [])
    if not isinstance(raw_findings, list):
        raw_findings = []
    for raw_value in raw_findings:
        if not isinstance(raw_value, Mapping):
            continue
        raw = dict(raw_value)
        rule = str(raw.get("rule") or raw.get("diagnostic_code") or f"{origin}-finding")
        finding_paths = _paths(raw)
        capabilities = _capabilities(raw)
        finding_type = _finding_type(origin, rule, raw)
        invariant_class = _invariant_class(origin, finding_type)
        path_relevant = _intersects(normalized_route_scope_paths, finding_paths)
        capability_relevant = bool(
            set(capabilities) & normalized_route_capabilities
        )
        existing_debt = (
            raw.get("baseline_status") == "existing_debt"
            and raw.get("blocking") is False
        )
        if path_relevant or capability_relevant:
            relevance = "relevant"
            delta_state = (
                "baseline_unchanged" if existing_debt else "task_local_new"
            )
        elif finding_paths or capabilities:
            relevance = "unrelated"
            delta_state = (
                "baseline_unchanged" if existing_debt else "unknown"
            )
        else:
            relevance = "unknown"
            delta_state = "unknown"
        if finding_type == "dynamic_import_unknown":
            relevance = "unknown"
            delta_state = "unknown"
        evidence_status = (
            "complete"
            if output_complete
            else completion
            if completion in {"bounded", "incomplete", "stale", "invalid"}
            else "incomplete"
        )
        if finding_type == "dynamic_import_unknown":
            evidence_status = "incomplete"
        severity = str(raw.get("severity", "P2"))
        if severity not in {"P0", "P1", "P2", "P3", "info"}:
            severity = "P2"
        findings.append(
            TypedFinding.create(
                type=finding_type,
                severity=severity,
                invariant_class=invariant_class,
                origin=origin,
                delta_state=delta_state,
                task_relevance=relevance,
                evidence_status=evidence_status,
                policy_rule_id=f"CHECK-{origin.upper().replace('_', '-')}-{rule.upper()}",
                paths=finding_paths,
                capabilities=capabilities,
                relevance_trace=_relevance_trace(
                    normalized_route_scope_paths,
                    finding_paths,
                    normalized_route_capabilities,
                    capabilities,
                    finding_type,
                ),
                evidence=raw,
                message=str(raw.get("message", "")),
            )
        )
    if not output_complete and not findings:
        findings.append(
            TypedFinding.create(
                type=f"{origin}_evidence_incomplete",
                severity="P1",
                invariant_class=(
                    "closure_global" if origin in {"dependency", "public_api"} else "task_local"
                ),
                origin=origin,
                delta_state="unknown",
                task_relevance="unknown",
                evidence_status=(
                    completion
                    if completion in {"bounded", "incomplete", "stale", "invalid"}
                    else "incomplete"
                ),
                policy_rule_id=f"CHECK-{origin.upper().replace('_', '-')}-INCOMPLETE",
                paths=normalized_route_paths,
                capabilities=normalized_route_capabilities,
                evidence={"completion_status": completion},
                message=f"{origin} evidence is incomplete",
            )
        )
    return sorted(findings, key=lambda item: item.finding_id)
