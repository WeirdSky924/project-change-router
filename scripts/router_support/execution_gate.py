from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from router_support.typed_findings import TypedFinding, validate_typed_finding


GATE_POLICY_VERSION = 1

HARD_BLOCK_TYPES = frozenset(
    {
        "unindexed_path",
        "owner_unknown",
        "duplicate_owner",
        "canonical_root_unknown",
        "canonical_root_conflict",
        "public_export_conflict",
        "public_entry_unknown",
        "generated_output_pin_invalid",
        "lifecycle_change",
        "dynamic_import_unknown",
        "cross_capability_duplicate",
        "evaluation_policy_invalid",
        "high_risk_surface",
    }
)


def _as_finding(value: TypedFinding | dict[str, Any]) -> TypedFinding:
    if isinstance(value, TypedFinding):
        finding = value
    else:
        errors = validate_typed_finding(value)
        if errors:
            raise ValueError("invalid typed finding fields: " + ", ".join(errors))
        finding = TypedFinding(
            finding_id=value["finding_id"],
            type=value["type"],
            severity=value["severity"],
            invariant_class=value["invariant_class"],
            origin=value["origin"],
            delta_state=value["delta_state"],
            task_relevance=value["task_relevance"],
            evidence_status=value["evidence_status"],
            policy_rule_id=value["policy_rule_id"],
            evidence_digest=value["evidence_digest"],
            paths=tuple(value.get("paths", [])),
            capabilities=tuple(value.get("capabilities", [])),
            relevance_trace=tuple(value.get("relevance_trace", [])),
            evidence=dict(value.get("evidence", {})),
            message=str(value.get("message", "")),
            schema_version=int(value.get("schema_version", 1)),
        )
    errors = validate_typed_finding(finding.to_dict())
    if errors:
        raise ValueError("invalid typed finding fields: " + ", ".join(errors))
    return finding


def reduce_execution_gate(
    findings: Iterable[TypedFinding | dict[str, Any]],
    *,
    allowed_write_paths: Iterable[str],
    forbidden_write_paths: Iterable[str],
    required_commands: Iterable[str],
    output_complete: bool,
    authoritative: bool = True,
) -> dict[str, Any]:
    normalized = sorted((_as_finding(item) for item in findings), key=lambda x: x.finding_id)
    allowed = list(dict.fromkeys(str(path) for path in allowed_write_paths if str(path)))
    forbidden = list(dict.fromkeys(str(path) for path in forbidden_write_paths if str(path)))
    commands = list(dict.fromkeys(str(command) for command in required_commands if str(command)))
    matched_rules: list[str] = []
    decisive: list[TypedFinding] = []

    if not output_complete:
        matched_rules.append("GATE-OUTPUT-001")

    unknown = [
        item
        for item in normalized
        if item.task_relevance == "unknown"
        or item.delta_state == "unknown"
        or item.evidence_status != "complete"
    ]
    if not output_complete and not unknown:
        raise ValueError(
            "incomplete gate output requires a schema-valid typed finding"
        )
    if unknown:
        matched_rules.append("GATE-UNKNOWN-001")
        decisive.extend(unknown)

    hard = [item for item in normalized if item.type in HARD_BLOCK_TYPES]
    if hard:
        matched_rules.append("GATE-HARD-001")
        decisive.extend(hard)

    relevant_high = [
        item
        for item in normalized
        if item.task_relevance == "relevant" and item.severity in {"P0", "P1"}
    ]
    if relevant_high:
        matched_rules.append("GATE-RELEVANT-001")
        decisive.extend(relevant_high)

    unbaselined_high = [
        item
        for item in normalized
        if item.task_relevance == "unrelated"
        and item.delta_state in {"task_local_new", "task_local_expanded"}
        and item.severity in {"P0", "P1"}
    ]
    if unbaselined_high:
        matched_rules.append("GATE-DELTA-001")
        decisive.extend(unbaselined_high)

    if "**" in forbidden and allowed:
        matched_rules.append("GATE-ENVELOPE-001")

    if matched_rules:
        state = "blocked"
        reason = "blocking or incomplete route evidence remains"
    else:
        historical = [
            item
            for item in normalized
            if item.task_relevance == "unrelated"
            and item.delta_state in {
                "baseline_unchanged",
                "baseline_reduced",
                "resolved",
            }
            and item.evidence_status == "complete"
        ]
        only_historical = bool(normalized) and len(historical) == len(normalized)
        if only_historical:
            if allowed and commands:
                state = "conditional"
                matched_rules.append("GATE-CONDITIONAL-001")
                decisive.extend(historical)
                reason = "only proven unrelated or non-expanding baseline debt remains"
            else:
                state = "blocked"
                matched_rules.append("GATE-CONDITIONAL-ENVELOPE-001")
                decisive.extend(historical)
                reason = "conditional evidence lacks a write envelope or prerequisite command"
        else:
            state = "pass"
            matched_rules.append("GATE-PASS-001")
            reason = "relevant evidence is complete and no blocking finding remains"

    decisive_ids = sorted({item.finding_id for item in decisive})
    return {
        "state": state,
        "blocking": state == "blocked",
        "conditional": state == "conditional",
        "authoritative": authoritative,
        "gate_policy_version": GATE_POLICY_VERSION,
        "policy_rule_ids": list(dict.fromkeys(matched_rules)),
        "decisive_finding_ids": decisive_ids,
        "unknown_evidence": [
            item.finding_id
            for item in normalized
            if item.task_relevance == "unknown"
            or item.delta_state == "unknown"
            or item.evidence_status != "complete"
        ],
        "proposed_allowed_write_paths": allowed,
        "proposed_forbidden_write_paths": forbidden,
        "allowed_write_paths": [] if state == "blocked" else allowed,
        "forbidden_write_paths": (
            list(dict.fromkeys([*forbidden, "**"])) if state == "blocked" else forbidden
        ),
        "required_commands": commands,
        "reason": reason,
    }


def shadow_gate_comparison(
    *, legacy_state: str, new_gate: dict[str, Any]
) -> dict[str, Any]:
    rank = {"pass": 0, "conditional": 1, "blocked": 2}
    new_state = str(new_gate.get("state", "blocked"))
    if legacy_state not in rank or new_state not in rank:
        raise ValueError("shadow gate state must be pass, conditional, or blocked")
    precision_improvement = (
        legacy_state == "blocked"
        and new_state == "conditional"
        and "GATE-CONDITIONAL-001" in new_gate.get("policy_rule_ids", [])
        and not new_gate.get("unknown_evidence")
    )
    if precision_improvement:
        classification = "precision_improvement"
    elif rank[new_state] < rank[legacy_state]:
        classification = "less_safe"
    elif rank[new_state] > rank[legacy_state]:
        classification = "more_restrictive"
    else:
        classification = "equivalent"
    return {
        "legacy_state": legacy_state,
        "new_state": new_state,
        "classification": classification,
        "cutover_eligible": classification != "less_safe",
        "new_decisive_finding_ids": list(new_gate.get("decisive_finding_ids", [])),
    }
