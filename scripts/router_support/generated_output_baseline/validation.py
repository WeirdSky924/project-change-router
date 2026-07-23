from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from router_support.generated_output_baseline.codec import (
    generated_output_rule_fingerprint,
)
from router_support.generated_output_baseline.model import (
    ARTIFACT_FIELDS,
    GENERATED_OUTPUT_MODE,
    GENERATOR_ID,
    PCR_BUNDLE_ARTIFACTS,
    RULE_FIELDS,
    finding,
)
from router_support.owner_identity import (
    owner_identity,
    owner_identity_is_valid,
    owner_is_unknown,
)
from router_support.profile_loader import CANONICAL_PROFILE_NAMES
from router_support.generated_output_baseline.contract import (
    sorted_diagnostic_keys,
)


def active_canonical_profile_source(repo_root: Path) -> str:
    sources = [
        name for name in CANONICAL_PROFILE_NAMES if (repo_root / name).is_file()
    ]
    if len(sources) != 1:
        raise ValueError(
            "generated output baseline requires exactly one canonical profile source"
        )
    return sources[0]


def _profile_has_stable_owner(
    profile: Mapping[str, Any],
    owner: object,
) -> bool:
    if not owner_identity_is_valid(owner) or owner_is_unknown(owner):
        return False
    capabilities = profile.get("capabilities", [])
    ownership = profile.get("capability_ownership", [])
    capability_records = [
        item
        for item in capabilities
        if isinstance(item, Mapping) and item.get("id") == owner
    ] if isinstance(capabilities, list) else []
    owner_records = [
        item
        for item in ownership
        if isinstance(item, Mapping) and item.get("target") == owner
    ] if isinstance(ownership, list) else []
    if len(capability_records) != 1 or len(owner_records) != 1:
        return False
    capability = capability_records[0]
    if capability.get("provisional") is True or (
        capability.get("status") != "stable"
        and capability.get("stage") not in {"stable", "governed-capability"}
    ):
        return False
    record = owner_records[0]
    primary = record.get("primary")
    primary_identity = owner_identity(primary)
    reviewers = record.get("reviewers")
    reviewer_ids = (
        [reviewer for reviewer in reviewers if isinstance(reviewer, str)]
        if isinstance(reviewers, list)
        else []
    )
    reviewer_identities = [owner_identity(reviewer) for reviewer in reviewer_ids]
    return (
        record.get("provisional") is not True
        and owner_identity_is_valid(primary)
        and not owner_is_unknown(primary)
        and isinstance(reviewers, list)
        and bool(reviewers)
        and len(reviewer_ids) == len(reviewers)
        and len(reviewer_identities) == len(set(reviewer_identities))
        and primary_identity not in reviewer_identities
        and all(
            owner_identity_is_valid(reviewer) and not owner_is_unknown(reviewer)
            for reviewer in reviewer_ids
        )
    )


def validate_generated_output_rules(
    profile: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
    canonical_source: str | None = None,
) -> list[dict[str, Any]]:
    guardrails = profile.get("guardrails", {})
    if not isinstance(guardrails, Mapping):
        return [finding(
            "generated_output_baseline_invalid",
            "profile.guardrails",
            "Profile guardrails must be a mapping.",
        )]
    raw_rules = guardrails.get("generated_output_baseline", [])
    if isinstance(raw_rules, list) and not raw_rules:
        return []
    if (
        not isinstance(raw_rules, list)
        or len(raw_rules) != 1
        or not isinstance(raw_rules[0], dict)
    ):
        return [finding(
            "generated_output_baseline_invalid",
            "profile.guardrails.generated_output_baseline",
            "Generated output baseline must contain exactly one mapping.",
        )]
    rule = raw_rules[0]
    rule_keys = tuple(rule)
    string_rule_keys = {key for key in rule_keys if isinstance(key, str)}
    if string_rule_keys != RULE_FIELDS or len(string_rule_keys) != len(rule_keys):
        findings = [finding(
            "generated_output_baseline_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output baseline fields do not match the closed contract.",
            missing_fields=sorted(RULE_FIELDS - string_rule_keys),
            unknown_fields=sorted_diagnostic_keys(
                [key for key in rule_keys if key not in RULE_FIELDS]
            ),
        )]
    else:
        findings = []
    if repo_root is not None and canonical_source is None:
        try:
            canonical_source = active_canonical_profile_source(repo_root)
        except ValueError as exc:
            findings.append(finding(
                "generated_output_baseline_invalid",
                str(rule.get("id") or "<missing-id>"),
                str(exc),
            ))
    required_strings = (
        "id",
        "source_commit",
        "owner",
        "reason",
        "exit_stage",
        "exit_condition",
        "initialization_authorization",
        "fingerprint",
    )
    missing = [
        field
        for field in required_strings
        if not isinstance(rule.get(field), str) or not str(rule[field]).strip()
    ]
    if missing:
        findings.append(finding(
            "generated_output_baseline_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output baseline has missing required metadata.",
            missing_fields=missing,
        ))
    rule_source_commit = rule.get("source_commit")
    sha_pattern = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
    if (
        not isinstance(rule_source_commit, str)
        or not sha_pattern.fullmatch(rule_source_commit)
    ):
        findings.append(finding(
            "generated_output_baseline_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output baseline provenance is malformed.",
            invalid_fields=["source_commit"],
        ))
    invalid_scalars = {
        field: rule.get(field)
        for field, expected in {
            "mode": GENERATED_OUTPUT_MODE,
            "generator_id": GENERATOR_ID,
        }.items()
        if rule.get(field) != expected
    }
    declared_source = rule.get("canonical_source")
    if declared_source not in CANONICAL_PROFILE_NAMES or (
        canonical_source is not None and declared_source != canonical_source
    ):
        invalid_scalars["canonical_source"] = declared_source
    if invalid_scalars:
        findings.append(finding(
            "generated_output_baseline_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output baseline uses an unsupported mode or source.",
            invalid_fields=invalid_scalars,
        ))
    if not _profile_has_stable_owner(profile, rule.get("owner")):
        findings.append(finding(
            "generated_output_baseline_owner_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output baseline requires one stable owner.",
        ))
    artifacts = rule.get("artifacts")
    keys = (
        [item.get("bundle_key") for item in artifacts if isinstance(item, dict)]
        if isinstance(artifacts, list)
        else []
    )
    if keys != list(PCR_BUNDLE_ARTIFACTS):
        findings.append(finding(
            "generated_output_baseline_invalid",
            str(rule.get("id") or "<missing-id>"),
            "Generated output artifacts must match the closed core bundle mapping in order.",
            artifact_keys=keys,
        ))
    digest_pattern = re.compile(r"^[0-9a-f]{64}$")
    for index, item in enumerate(artifacts if isinstance(artifacts, list) else []):
        if not isinstance(item, dict):
            continue
        item_keys = tuple(item)
        string_item_keys = {key for key in item_keys if isinstance(key, str)}
        if string_item_keys != ARTIFACT_FIELDS or len(string_item_keys) != len(item_keys):
            findings.append(finding(
                "generated_output_baseline_invalid",
                str(rule.get("id") or "<missing-id>"),
                "Generated output artifact fields do not match the closed contract.",
                artifact_index=index,
                missing_fields=sorted(ARTIFACT_FIELDS - string_item_keys),
                unknown_fields=sorted_diagnostic_keys(
                    [key for key in item_keys if key not in ARTIFACT_FIELDS]
                ),
            ))
        invalid = [
            field
            for field in ("semantic_digest", "canonical_text_digest")
            if not isinstance(item.get(field), str)
            or not digest_pattern.fullmatch(str(item[field]))
        ]
        artifact_source = item.get("source_commit")
        if artifact_source is not None and (
            not isinstance(artifact_source, str)
            or not sha_pattern.fullmatch(artifact_source)
        ):
            invalid.append("source_commit")
        if type(item.get("line_count")) is not int or item["line_count"] <= 0:
            invalid.append("line_count")
        if invalid:
            findings.append(finding(
                "generated_output_baseline_invalid",
                str(rule.get("id") or "<missing-id>"),
                "Generated output artifact metadata is malformed.",
                artifact_index=index,
                invalid_fields=invalid,
            ))
    fingerprint = rule.get("fingerprint")
    if isinstance(fingerprint, str):
        try:
            actual_fingerprint = generated_output_rule_fingerprint(rule)
        except (TypeError, ValueError) as exc:
            findings.append(finding(
                "generated_output_baseline_invalid",
                str(rule.get("id") or "<missing-id>"),
                "Generated output baseline contains a non-JSON scalar.",
                error=str(exc),
            ))
        else:
            if fingerprint != actual_fingerprint:
                findings.append(finding(
                    "generated_output_baseline_fingerprint_mismatch",
                    str(rule.get("id") or "<missing-id>"),
                    "Generated output baseline fingerprint does not match its exact rule.",
                ))
    return findings
