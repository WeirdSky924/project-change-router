from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from router_support.owner_identity import (
    owner_identity as _owner_identity,
    owner_identity_is_valid as _owner_identity_is_valid,
    owner_is_unknown as _owner_is_unknown,
)

STABLE_STAGES = {"stable", "governed-capability"}


def _records(container: object, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(container, Mapping):
        return []
    value = container.get(key, [])
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _is_stable(capability: Mapping[str, Any]) -> bool:
    return str(capability.get("status", "")).lower() == "stable" or str(
        capability.get("stage", "")
    ).lower() in STABLE_STAGES


def contract_description(value: object) -> str:
    if isinstance(value, Mapping):
        for key in ("description", "constraint", "text", "name"):
            candidate = value.get(key)
            if candidate:
                return str(candidate)
        return ""
    return str(value or "")


def capability_owner_assessment(
    bundle: Mapping[str, Any], capability_id: str
) -> dict[str, Any]:
    records = [
        owner
        for owner in _records(bundle.get("ownership"), "owners")
        if owner.get("scope") == "capability"
        and str(owner.get("target") or "") == capability_id
    ]
    reasons: list[str] = []
    if len(records) != 1:
        reasons.append(
            "capability owner record missing"
            if not records
            else "duplicate capability owner records"
        )
    owner = records[0] if len(records) == 1 else {}
    primary = owner.get("primary")
    reviewers = owner.get("reviewers", [])
    reviewer_values = reviewers if isinstance(reviewers, list) else []
    if not _owner_identity_is_valid(primary):
        reasons.append("capability owner identity is invalid")
    elif owner.get("provisional") is True or _owner_is_unknown(primary):
        reasons.append("capability owner is unknown or provisional")
    if not isinstance(reviewers, list) or any(
        not _owner_identity_is_valid(reviewer) for reviewer in reviewer_values
    ):
        reasons.append("capability reviewer identity is invalid")
    primary_identity = _owner_identity(primary)
    distinct_reviewers = [
        reviewer
        for reviewer in reviewer_values
        if _owner_identity_is_valid(reviewer)
        and not _owner_is_unknown(reviewer)
        and _owner_identity(reviewer) != primary_identity
    ]
    if not distinct_reviewers:
        reasons.append("capability reviewer is missing or not distinct")
    return {
        "trusted": not reasons,
        "primary": primary,
        "reviewers": reviewer_values,
        "distinct_reviewers": distinct_reviewers,
        "reasons": reasons,
    }


def capabilities_owner_assessment(
    bundle: Mapping[str, Any], capability_ids: Iterable[str]
) -> dict[str, Any]:
    assessments = {
        capability_id: capability_owner_assessment(bundle, capability_id)
        for capability_id in dict.fromkeys(str(item) for item in capability_ids if item)
    }
    reasons = [
        f"{capability_id}: {reason}"
        for capability_id, assessment in assessments.items()
        if not assessment["trusted"]
        for reason in assessment["reasons"]
    ]
    return {
        "trusted": not reasons,
        "capabilities": assessments,
        "reasons": reasons,
    }


def _coverage_kind(case: Mapping[str, Any]) -> str:
    explicit = str(case.get("coverage_kind", "")).strip().lower()
    if explicit in {"positive", "boundary"}:
        return explicit
    return "boundary" if case.get("expected_action") == "review" else "positive"


_INCOMPLETE_CONTRACT_SIGNAL = re.compile(
    r"\b(?:partial|protocol[- ]only|incomplete)\b|"
    r"\b(?:[a-z0-9_-]+-)?(?:method|operation)\s+subset\b|"
    r"\bsubset\b[^.;\n]{0,80}\b(?:contract|protocol|operations?|methods?)\b|"
    r"\b(?:missing|absent|omitted)\b[^.;\n]{0,60}\b(?:operations?|methods?|members?)\b|"
    r"\b(?:operations?|methods?|members?)\b[^.;\n]{0,60}\b(?:missing|absent|omitted)\b"
)
_UNSAFE_CONTRACT_ACCEPTANCE = re.compile(
    r"\b(?:treat(?:ed|s|ing)?|accept(?:ed|s|ing)?|consider(?:ed|s|ing)?|"
    r"regard(?:ed|s|ing)?|allow(?:ed|s|ing)?|permit(?:ted|s|ting)?)\b"
    r"[^.;\n]{0,120}\b(?:success(?:ful(?:ly)?)?|valid|complete|usable|supported|sufficient)\b"
)
_MISSING_OPERATION_BYPASS = re.compile(
    r"\b(?:skip(?:s|ped|ping)?|ignor(?:e|es|ed|ing)|bypass(?:es|ed|ing)?|"
    r"omit(?:s|ted|ting)?|drop(?:s|ped|ping)?)\b"
)
_SECOND_OWNER_SIGNAL = re.compile(
    r"\b(?:second|parallel|additional|another|duplicate|extra|alternate)\b"
    r"[^.;\n]{0,100}?\b(?:repository|store)\b|"
    r"\b(?:repository|store)\b[^.;\n]{0,100}?"
    r"\b(?:alongside|beside|next\s+to|along\s+with|in\s+parallel\s+with)\b"
)
_ADDITIVE_SECOND_OWNER_ACTION = re.compile(
    r"\b(?:add(?:s|ed|ing)?|creat(?:e|es|ed|ing|ion)|introduc(?:e|es|ed|ing)|"
    r"establish(?:es|ed|ing)?|implement(?:s|ed|ing)?|build(?:s|ing)?|built|"
    r"make|makes|made|keep(?:s|ing)?|kept|retain(?:s|ed|ing)?|maintain(?:s|ed|ing)?|"
    r"leav(?:e|es|ing)|left|own(?:s|ed|ing)?)\b"
)
_OPERATING_SECOND_OWNER_ACTION = re.compile(
    r"\b(?:us(?:e|es|ed|ing)|run(?:s|ning)?|ran|operat(?:e|es|ed|ing)|"
    r"wir(?:e|es|ed|ing))\b"
)
_SECOND_OWNER_COEXISTENCE = re.compile(
    r"\b(?:alongside|beside|next\s+to|along\s+with|in\s+parallel\s+with)\b"
)
_PROTECTIVE_BOUNDARY_VERB = re.compile(
    r"\b(?:reject|prevent|block|forbid|disallow|prohibit|avoid|refus(?:e|es|ed|ing)|"
    r"deny|fail\s+(?:closed|fast))\b"
)
_NEGATED_BOUNDARY_ACTION = re.compile(
    r"\b(?:not|never|cannot|can't|must\s+not|should\s+not)\b[^.;\n]{0,48}$"
)
_PROTECTIVE_BOUNDARY_RESULT = re.compile(
    r"^[^.;\n]{0,56}\b(?:cannot\s+be\s+(?:introduced|added|created|accepted)|"
    r"must\s+(?:fail|be\s+(?:rejected|blocked|forbidden))|"
    r"should\s+be\s+(?:rejected|blocked|forbidden)|"
    r"(?:is|are)\s+(?:rejected|blocked|forbidden|invalid))\b"
)


def _boundary_context(normalized_request: str, start: int, end: int) -> tuple[str, str]:
    clause_start = max(
        normalized_request.rfind(".", 0, start),
        normalized_request.rfind(";", 0, start),
        normalized_request.rfind("\n", 0, start),
    )
    clause_ends = [
        position
        for marker in (".", ";", "\n")
        if (position := normalized_request.find(marker, end)) >= 0
    ]
    clause_end = min(clause_ends, default=len(normalized_request))
    clause = normalized_request[clause_start + 1 : clause_end]
    offset = clause_start + 1
    return clause[: max(0, start - offset)], clause[max(0, end - offset) :]


def _match_is_protective(normalized_request: str, start: int, end: int) -> bool:
    prefix, suffix = _boundary_context(normalized_request, start, end)
    protective_matches = list(_PROTECTIVE_BOUNDARY_VERB.finditer(prefix))
    if protective_matches:
        after_protective = prefix[protective_matches[-1].end() :]
        if not re.search(r"\b(?:but|however|yet)\b", after_protective):
            return True
    return bool(
        _NEGATED_BOUNDARY_ACTION.search(prefix)
        or _PROTECTIVE_BOUNDARY_RESULT.search(suffix)
    )


def _declares_incomplete_contract_boundary(patterns: list[str]) -> bool:
    for raw_pattern in patterns:
        pattern = " ".join(str(raw_pattern).lower().split())
        incomplete = _INCOMPLETE_CONTRACT_SIGNAL.search(pattern)
        contract_surface = any(
            marker in pattern
            for marker in ("contract", "protocol", "dispatch", "operation", "method")
        )
        unsafe_result = bool(
            _UNSAFE_CONTRACT_ACCEPTANCE.search(pattern)
            or _MISSING_OPERATION_BYPASS.search(pattern)
            or "dynamic" in pattern
        )
        if incomplete and contract_surface and unsafe_result:
            return True
    return False


def _request_accepts_incomplete_contract(normalized_request: str) -> bool:
    unsafe_matches = [
        *_UNSAFE_CONTRACT_ACCEPTANCE.finditer(normalized_request),
        *_MISSING_OPERATION_BYPASS.finditer(normalized_request),
    ]
    for match in unsafe_matches:
        if _match_is_protective(normalized_request, match.start(), match.end()):
            continue
        prefix, suffix = _boundary_context(normalized_request, match.start(), match.end())
        clause = prefix + " " + match.group() + " " + suffix
        if _INCOMPLETE_CONTRACT_SIGNAL.search(clause):
            return True
    return False


def _declares_second_owner_boundary(patterns: list[str]) -> bool:
    return any(
        _SECOND_OWNER_SIGNAL.search(" ".join(str(raw_pattern).lower().split()))
        for raw_pattern in patterns
    )


def _request_adds_second_owner(normalized_request: str) -> bool:
    for match in _SECOND_OWNER_SIGNAL.finditer(normalized_request):
        if _match_is_protective(normalized_request, match.start(), match.end()):
            continue
        prefix, suffix = _boundary_context(normalized_request, match.start(), match.end())
        clause = prefix + " " + match.group() + " " + suffix
        if _ADDITIVE_SECOND_OWNER_ACTION.search(clause) or (
            _OPERATING_SECOND_OWNER_ACTION.search(clause)
            and _SECOND_OWNER_COEXISTENCE.search(clause)
        ):
            return True
    return False


def matching_capability_contract_boundaries(
    positive_request_scope: str,
    forbidden_patterns: list[str],
    anti_patterns: list[str],
) -> list[str]:
    normalized_request = " ".join(positive_request_scope.lower().split())
    declared_patterns = [*forbidden_patterns, *anti_patterns]
    matches: list[str] = []
    if request_has_permanent_central_delegation(normalized_request):
        matches.append("permanent central delegation")
    if _declares_incomplete_contract_boundary(
        declared_patterns
    ) and _request_accepts_incomplete_contract(normalized_request):
        matches.append("incomplete contract accepted as successful")
    if _declares_second_owner_boundary(
        declared_patterns
    ) and _request_adds_second_owner(normalized_request):
        matches.append("second repository or store owner")
    for raw_pattern in declared_patterns:
        pattern = " ".join(str(raw_pattern).lower().split())
        if not pattern or any(marker in pattern for marker in ("/", "*", ".py")):
            continue
        if pattern in normalized_request:
            matches.append(str(raw_pattern))
    return list(dict.fromkeys(matches))


def request_has_permanent_central_delegation(positive_request_scope: str) -> bool:
    """Detect domain persistence retained behind a nominal repository boundary."""

    normalized = " ".join(positive_request_scope.lower().split())
    nominal_boundary = re.search(
        r"\b[a-z0-9_]*(?:repository|adapter|facade)\b",
        normalized,
    )
    central_database_owner = (
        r"(?:(?:global|central)?[a-z0-9_]*(?:postgres|database|sql)"
        r"[a-z0-9_]*gateway|(?:the\s+)?(?:global|central)\s+"
        r"(?:(?:postgres|database|sql)\s+)?gateway)"
    )
    retained_responsibility = re.search(
        r"\b(?:keep|retain|leave)\s+(?:all\s+)?[^.;\n]{0,120}"
        r"\b(?:sql|codecs?|crud|row\s+mappings?|domain\s+methods?|business\s+persistence)\b"
        rf"[^.;\n]{{0,100}}\b(?:in|inside|within)\s+{central_database_owner}\b",
        normalized,
    )
    permanent_domain_delegation = re.search(
        r"\b(?:permanent(?:ly)?|indefinite(?:ly)?)\b[^.;\n]{0,80}"
        r"\b(?:delegat(?:e|es|ed|ing)|forward(?:s|ed|ing)?|prox(?:y|ies|ied|ying))\b"
        r"[^.;\n]{0,100}\b(?:sql|codecs?|crud|row\s+mappings?|domain\s+methods?|business\s+persistence)\b"
        rf"[^.;\n]{{0,100}}\b(?:back\s+to|into|through)\s+{central_database_owner}\b",
        normalized,
    )
    return bool(nominal_boundary and (retained_responsibility or permanent_domain_delegation))


def build_governance_repair_suggestions(
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for finding in findings:
        rule = finding.get("rule")
        details = finding.get("details", {})
        if rule == "profile-capability-not-in-catalog":
            for capability in details.get("missing_capabilities", []):
                suggestions.append(
                    {
                        "kind": "profile_path_pattern_fix",
                        "target": capability,
                        "suggestion": "Fix path_patterns so this profile capability matches discovered modules, or remove the stale capability entry.",
                        "confidence": "high",
                    }
                )
        elif rule == "change-rule-references-unknown-capability":
            for capability in details.get("unknown_capabilities", []):
                suggestions.append(
                    {
                        "kind": "change_rules_reference_fix",
                        "target": capability,
                        "suggestion": "Remove this stale capability reference or add the missing capability before trusting routing rules.",
                        "confidence": "high",
                    }
                )
        elif rule == "path-map-references-unknown-capability":
            for capability in details.get("unknown_capabilities", []):
                suggestions.append(
                    {
                        "kind": "path_map_reference_fix",
                        "target": capability,
                        "suggestion": "Remove the stale path-map reference or restore the curated capability, then rebuild and revalidate the bundle.",
                        "confidence": "high",
                    }
                )
        elif rule == "catalog-has-unprofiled-capabilities":
            for capability in details.get("generated_capabilities", []):
                suggestions.append(
                    {
                        "kind": "promote_generated_capability",
                        "target": capability,
                        "suggestion": "If this boundary is real, add a profile capability with contracts, public_entries, ownership, lifecycle, and tests.",
                        "confidence": "medium",
                    }
                )
        elif rule in {
            "module-without-capability-path-index",
            "path-to-capability-map-missing",
        }:
            targets = details.get("uncovered_modules", []) or [
                "project-change-router/references/path-to-capability-map.yaml"
            ]
            for module in targets:
                suggestions.append(
                    {
                        "kind": "path_index_rebuild_or_owner_rule",
                        "target": module,
                        "suggestion": "Rebuild the bundle and add ownership/capability rules for uncovered stable module roots.",
                        "confidence": (
                            "high"
                            if rule == "path-to-capability-map-missing"
                            else "medium"
                        ),
                    }
                )
        elif rule in {
            "capability-root-owner-too-broad",
            "path-map-repository-wide-capability",
        }:
            for capability in details.get("capabilities", []) or [
                finding.get("target")
            ]:
                suggestions.append(
                    {
                        "kind": "narrow_capability_ownership",
                        "target": capability,
                        "suggestion": "Replace repo-root ownership with concrete owner_modules, public_entries, and path patterns such as migrations/**, app/<domain>/**, or explicit schema/test bindings.",
                        "confidence": "high",
                    }
                )
        elif rule in {
            "profile-capability-contracts-too-thin",
            "large-capability-contracts-too-thin",
        }:
            suggestions.append(
                {
                    "kind": "contract_completion",
                    "target": finding.get("target"),
                    "suggestion": "Add scope, boundary, cross-capability, and risk contracts. Keep each contract concrete and enforceable.",
                    "confidence": "high",
                }
            )
        elif rule == "large-capability-forbidden-density-too-low":
            suggestions.append(
                {
                    "kind": "forbidden_pattern_completion",
                    "target": finding.get("target"),
                    "suggestion": "Add forbidden patterns for duplicate implementation centers, bypassed public APIs, misplaced caches, and cross-layer writes.",
                    "confidence": "medium",
                }
            )
        elif rule == "dependency-priority-incomplete":
            suggestions.append(
                {
                    "kind": "dependency_priority_completion",
                    "target": "references/change-rules.yaml",
                    "suggestion": "Assign lower priority numbers to foundation/core capabilities and higher numbers to facade, adapter, and UI capabilities.",
                    "confidence": "high",
                }
            )
        elif rule == "profile-capability-without-evaluation-case":
            for capability in details.get("uncovered_capabilities", []):
                suggestions.append(
                    {
                        "kind": "evaluation_case_completion",
                        "target": capability,
                        "suggestion": "Add at least one positive route case and one boundary or review case for this capability.",
                        "confidence": "high",
                    }
                )
        elif rule == "deprecated-capability-migration-metadata-missing":
            suggestions.append(
                {
                    "kind": "lifecycle_metadata_completion",
                    "target": finding.get("target"),
                    "suggestion": "Add superseded_by, deprecation_date, migration_note, affected callers, and migration tests.",
                    "confidence": "high",
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for suggestion in suggestions:
        key = (str(suggestion.get("kind")), str(suggestion.get("target")))
        if key not in seen:
            seen.add(key)
            deduped.append(suggestion)
    return deduped[:50]


def assess_stable_capability_governance(bundle: Mapping[str, Any]) -> dict[str, list[str]]:
    capabilities = _records(bundle.get("capability_catalog"), "capabilities")
    stable = {
        str(capability.get("id")): capability
        for capability in capabilities
        if capability.get("id") and _is_stable(capability)
    }
    owners = {
        str(owner.get("target")): owner
        for owner in _records(bundle.get("ownership"), "owners")
        if owner.get("scope") == "capability" and owner.get("target")
    }

    missing_owner: list[str] = []
    provisional_or_unknown_owner: list[str] = []
    missing_distinct_reviewer: list[str] = []
    missing_lifecycle: list[str] = []
    missing_public_entries: list[str] = []
    missing_contracts: list[str] = []

    for capability_id, capability in stable.items():
        owner = owners.get(capability_id)
        if owner is None:
            missing_owner.append(capability_id)
        else:
            primary = owner.get("primary")
            reviewers = owner.get("reviewers", [])
            reviewer_values = reviewers if isinstance(reviewers, list) else []
            if owner.get("provisional") is True or _owner_is_unknown(primary):
                provisional_or_unknown_owner.append(capability_id)
            primary_identity = _owner_identity(primary)
            distinct_reviewers = [
                reviewer
                for reviewer in reviewer_values
                if not _owner_is_unknown(reviewer)
                and _owner_identity(reviewer) != primary_identity
            ]
            if not distinct_reviewers:
                missing_distinct_reviewer.append(capability_id)

        lifecycle = capability.get("lifecycle")
        if not isinstance(lifecycle, Mapping) or not lifecycle.get("definition_version"):
            missing_lifecycle.append(capability_id)
        if not capability.get("public_entries"):
            missing_public_entries.append(capability_id)
        if not capability.get("contracts"):
            missing_contracts.append(capability_id)

    positive: set[str] = set()
    boundary: set[str] = set()
    for case in _records(bundle.get("evaluation_set"), "cases"):
        capabilities_for_case = {
            str(capability_id)
            for capability_id in case.get("expected_capabilities", [])
            if capability_id
        }
        destination = positive if _coverage_kind(case) == "positive" else boundary
        destination.update(capabilities_for_case & stable.keys())

    return {
        "stable_capabilities": sorted(stable),
        "missing_owner": sorted(missing_owner),
        "provisional_or_unknown_owner": sorted(provisional_or_unknown_owner),
        "missing_distinct_reviewer": sorted(missing_distinct_reviewer),
        "missing_lifecycle": sorted(missing_lifecycle),
        "missing_public_entries": sorted(missing_public_entries),
        "missing_contracts": sorted(missing_contracts),
        "missing_positive_cases": sorted(stable.keys() - positive),
        "missing_boundary_cases": sorted(stable.keys() - boundary),
    }


GAP_FINDINGS = {
    "missing_owner": (
        "stable-capability-owner-missing",
        "Stable capabilities must have a capability-scoped owner record.",
        "Rebuild ownership from the canonical capability steward before automatic routing.",
    ),
    "provisional_or_unknown_owner": (
        "stable-capability-owner-untrusted",
        "Stable capabilities cannot use UNKNOWN, unassigned, or provisional owners.",
        "Assign a canonical capability steward and rebuild before automatic routing.",
    ),
    "missing_distinct_reviewer": (
        "stable-capability-reviewer-not-distinct",
        "Stable capability reviewers must exist and differ from the primary owner.",
        "Assign a distinct architecture reviewer for each stable capability.",
    ),
    "missing_lifecycle": (
        "stable-capability-lifecycle-missing",
        "Stable capabilities must declare lifecycle.definition_version.",
        "Add versioned lifecycle metadata through the canonical capability owner.",
    ),
    "missing_public_entries": (
        "stable-capability-public-entry-missing",
        "Stable capabilities must expose at least one governed public entry.",
        "Declare the real public entry before routing consumers to the capability.",
    ),
    "missing_contracts": (
        "stable-capability-contract-missing",
        "Stable capabilities must declare enforceable scope and boundary contracts.",
        "Add concrete scope, dependency, and risk contracts before automatic routing.",
    ),
    "missing_positive_cases": (
        "stable-capability-positive-case-missing",
        "Stable capabilities need a real in-boundary positive routing case.",
        "Add a real positive case; high-risk valid requests may remain review with coverage_kind=positive.",
    ),
    "missing_boundary_cases": (
        "stable-capability-boundary-case-missing",
        "Stable capabilities need a real boundary or review routing case.",
        "Add a focused forbidden, cross-owner, or lifecycle boundary regression case.",
    ),
}


def build_stable_capability_governance_findings(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    assessment = assess_stable_capability_governance(bundle)
    findings: list[dict[str, Any]] = []
    for key, (rule, message, recommendation) in GAP_FINDINGS.items():
        capabilities = assessment[key]
        if capabilities:
            findings.append(
                {
                    "severity": "P1",
                    "rule": rule,
                    "target": "references/capability-catalog.yaml",
                    "message": message,
                    "recommendation": recommendation,
                    "details": {"capabilities": capabilities},
                }
            )
    return findings
