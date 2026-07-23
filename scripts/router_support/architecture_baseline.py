from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from router_support.owner_identity import owner_identity_is_valid, owner_is_unknown
from router_support.profile_loader import CANONICAL_PROFILE_NAMES, LEGACY_PROFILE_NAMES
from router_support.structure_growth import resolve_git_commit


IDENTITY_FIELDS = (
    "rule", "source", "source_file", "source_module", "target",
    "target_file", "target_module", "import", "language", "members",
    "module", "count", "diagnostic_code",
)
RULE_IDENTITY_FIELDS = {
    "dependency-direction": ("source", "target"),
    "runtime-cycle": ("language", "members"),
    "type-only-cycle": ("language", "members"),
    "public-api-bypass": ("source", "target", "import"),
    "public-export-count": ("module", "count"),
}
BASELINE_STRING_FIELDS = ("id", "rule", "owner", "exit_stage", "fingerprint")
TRACKED_CHANGE_RULES_PATH = "project-change-router/references/change-rules.yaml"


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity_value(item: Mapping[str, object], field: str) -> object:
    value = item.get(field)
    if field == "members" and isinstance(value, (list, tuple, set)):
        return tuple(sorted(value, key=repr))
    return value


def _valid_identity(field: str, value: object) -> bool:
    if field == "members":
        return (
            isinstance(value, (list, tuple, set))
            and bool(value)
            and all(_non_empty_string(member) for member in value)
            and len(value) == len(set(value))
        )
    if field == "count":
        return type(value) is int and value >= 0
    return _non_empty_string(value)


def finding_fingerprint(item: Mapping[str, object]) -> str:
    raw_rule = item.get("rule")
    rule = raw_rule if isinstance(raw_rule, str) else ""
    fields = RULE_IDENTITY_FIELDS.get(rule)
    if fields is None:
        fields = tuple(field for field in IDENTITY_FIELDS if field in item and field != "rule")
    payload = {"rule": rule}
    for field in fields:
        payload[field] = _identity_value(item, field)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_text_or_none(repo_root: Path, commit: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if exists.returncode != 0:
        return None
    detail = result.stderr.strip() or result.stdout.strip() or "git show failed"
    raise RuntimeError(f"{path}: {detail}")


def _yaml_mapping(source: str, path: str) -> Mapping[str, object]:
    try:
        payload = yaml.safe_load(source) or {}
    except yaml.YAMLError as exc:
        raise RuntimeError(f"{path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"{path}: expected a mapping")
    return payload


def _guardrail_items(
    value: object,
    path: str,
    collection: str,
) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{path}: {collection} must be a list")
    return [
        dict(item)
        for item in value
        if isinstance(item, Mapping)
        and isinstance(item.get("id"), str)
    ]


def comparison_guardrail_items(
    repo_root: Path,
    commit: str,
    collection: str,
) -> dict[str, dict[str, object]]:
    profile_sources: list[tuple[str, str]] = []
    for names in (CANONICAL_PROFILE_NAMES, LEGACY_PROFILE_NAMES):
        profile_sources = [
            (path, source)
            for path in names
            if (source := _git_text_or_none(repo_root, commit, path)) is not None
        ]
        if profile_sources:
            break
    if len(profile_sources) > 1:
        raise RuntimeError("comparison commit has multiple active profile sources")

    items: list[dict[str, object]] = []
    if profile_sources:
        path, source = profile_sources[0]
        payload = _yaml_mapping(source, path)
        guardrails = payload.get("guardrails", {})
        if not isinstance(guardrails, Mapping):
            raise RuntimeError(f"{path}: guardrails must be a mapping")
        items.extend(
            _guardrail_items(
                guardrails.get(collection),
                path,
                collection,
            )
        )

    tracked = _git_text_or_none(repo_root, commit, TRACKED_CHANGE_RULES_PATH)
    if tracked is not None:
        payload = _yaml_mapping(tracked, TRACKED_CHANGE_RULES_PATH)
        items.extend(
            _guardrail_items(
                payload.get(collection),
                TRACKED_CHANGE_RULES_PATH,
                collection,
            )
        )
    by_id: dict[str, dict[str, object]] = {}
    for item in items:
        baseline_id = str(item["id"])
        existing = by_id.get(baseline_id)
        if existing is not None and existing != item:
            raise RuntimeError(f"comparison baseline id {baseline_id!r} has conflicting sources")
        by_id[baseline_id] = item
    return by_id


def _is_safe_public_export_tightening(
    comparison: Mapping[str, object],
    current: Mapping[str, object],
) -> bool:
    old_count = comparison.get("count")
    new_count = current.get("count")
    return (
        comparison.get("rule") == current.get("rule") == "public-export-count"
        and comparison.get("module") == current.get("module")
        and comparison.get("owner") == current.get("owner")
        and comparison.get("exit_stage") == current.get("exit_stage")
        and type(old_count) is int
        and type(new_count) is int
        and 0 <= new_count < old_count
        and current.get("fingerprint") == finding_fingerprint(current)
    )


def filter_architecture_baseline_by_provenance(
    repo_root: Path,
    baseline: Iterable[dict[str, object]],
    comparison_commit: str | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    items = list(baseline)
    revision = str(comparison_commit or "").strip()
    if not items and not revision:
        return [], []
    try:
        if not revision:
            raise RuntimeError("comparison commit is required")
        resolved = resolve_git_commit(repo_root, revision)
        if not items:
            return [], []
        comparison_items = comparison_guardrail_items(
            repo_root,
            resolved,
            "architecture_baseline",
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return [], [{
            "severity": "P0",
            "rule": "architecture-baseline-provenance",
            "source": "<comparison-commit>",
            "blocking": True,
            "baseline_status": "new",
            "diagnostic_code": "architecture_baseline_provenance_incomplete",
            "comparison_commit": revision or None,
            "completion_status": "incomplete",
            "evidence_complete": False,
            "message": f"Architecture baseline provenance could not be verified: {exc}",
        }]

    trusted: list[dict[str, object]] = []
    diagnostics: list[dict[str, object]] = []
    for item in items:
        baseline_id = item.get("id")
        fingerprint = item.get("fingerprint")
        comparison = comparison_items.get(baseline_id) if isinstance(baseline_id, str) else None
        metadata_matches = bool(
            comparison
            and comparison.get("rule") == item.get("rule")
            and comparison.get("owner") == item.get("owner")
            and comparison.get("exit_stage") == item.get("exit_stage")
        )
        exact = bool(
            metadata_matches
            and comparison.get("fingerprint") == fingerprint
        )
        if exact or (
            comparison is not None
            and _is_safe_public_export_tightening(comparison, item)
        ):
            trusted.append(item)
            continue
        changed = comparison is not None
        diagnostics.append({
            "severity": "P1",
            "rule": "architecture-baseline-provenance",
            "source": baseline_id if isinstance(baseline_id, str) else "<invalid-baseline-id>",
            "blocking": True,
            "baseline_status": "new",
            "diagnostic_code": (
                "architecture_baseline_changed_since_comparison"
                if changed
                else "architecture_baseline_added_since_comparison"
            ),
            "baseline_id": baseline_id,
            "fingerprint": fingerprint,
            "comparison_commit": resolved,
            "completion_status": "complete",
            "evidence_complete": True,
            "message": "Architecture baseline entries must predate the current comparison boundary",
        })
    return trusted, diagnostics


def _baseline_has_current(
    baseline: Mapping[str, object],
    current: Iterable[Mapping[str, object]],
) -> bool:
    if baseline.get("rule") == "public-export-count":
        return any(
            item.get("rule") == "public-export-count"
            and item.get("module") == baseline.get("module")
            for item in current
        )
    fingerprint = baseline.get("fingerprint")
    return any(finding_fingerprint(item) == fingerprint for item in current)


def validate_architecture_baseline(
    baseline: Iterable[dict[str, object]],
    current_findings: Iterable[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    items = list(baseline)
    current = None if current_findings is None else list(current_findings)
    valid_ids = [item.get("id") for item in items if _non_empty_string(item.get("id"))]
    valid_fingerprints = [
        item.get("fingerprint")
        for item in items
        if _non_empty_string(item.get("fingerprint"))
    ]
    errors: list[dict[str, object]] = []

    def add(index: int, item: Mapping[str, object], code: str, message: str, **details: object) -> None:
        errors.append({
            "code": code,
            "baseline_id": item.get("id"),
            "baseline_index": index,
            "message": message,
            **details,
        })

    for index, item in enumerate(items):
        for field in BASELINE_STRING_FIELDS:
            value = item.get(field)
            if value is not None and not isinstance(value, str):
                add(index, item, f"baseline_invalid_{field}_type", f"Baseline {field} must be a string")

        rule_value = item.get("rule")
        rule = rule_value if isinstance(rule_value, str) else ""
        required = RULE_IDENTITY_FIELDS.get(rule, ())
        if _non_empty_string(rule_value) and rule not in RULE_IDENTITY_FIELDS:
            add(
                index,
                item,
                "baseline_unsupported_rule",
                "This architecture finding rule cannot be baselined",
            )
        missing_identity = [
            field for field in required
            if item.get(field) is None or item.get(field) == "" or item.get(field) == ()
        ]
        invalid_identity = [
            field for field in required
            if field not in missing_identity and not _valid_identity(field, item.get(field))
        ]
        if not _non_empty_string(rule_value) or missing_identity:
            missing = missing_identity or ["rule"]
            add(index, item, "baseline_missing_identity", f"Missing identity fields: {', '.join(missing)}")
        if invalid_identity:
            add(
                index,
                item,
                "baseline_invalid_identity_type",
                "Baseline identity fields have invalid types",
                identity_fields=invalid_identity,
            )

        owner = item.get("owner")
        if not owner_identity_is_valid(owner):
            add(index, item, "baseline_missing_owner", "Baseline owner is required")
        elif owner_is_unknown(owner):
            add(index, item, "baseline_unknown_owner", "Baseline owner must be stable")
        exit_stage = item.get("exit_stage")
        if not _non_empty_string(exit_stage):
            add(index, item, "baseline_missing_exit_stage", "Baseline exit_stage is required")

        fingerprint = item.get("fingerprint")
        identity_is_valid = not missing_identity and not invalid_identity and _non_empty_string(rule_value)
        if fingerprint is None or fingerprint == "":
            add(index, item, "baseline_missing_fingerprint", "Baseline fingerprint is required")
        elif isinstance(fingerprint, str) and not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            add(index, item, "baseline_invalid_fingerprint", "Baseline fingerprint must be lowercase SHA-256")
        elif isinstance(fingerprint, str) and identity_is_valid and fingerprint != finding_fingerprint(item):
            add(index, item, "baseline_fingerprint_mismatch", "Baseline fingerprint does not match its identity")

        identity_values = [_identity_value(item, field) for field in required]
        if any(
            any(marker in value for marker in ("*", "?", "["))
            for identity in identity_values
            for value in (identity if isinstance(identity, tuple) else (identity,))
            if isinstance(value, str)
        ):
            add(index, item, "baseline_wildcard_identity", "Baseline identity cannot contain glob patterns")

        baseline_id = item.get("id")
        if not _non_empty_string(baseline_id):
            add(index, item, "baseline_missing_id", "Baseline id is required")
        elif isinstance(baseline_id, str) and valid_ids.count(baseline_id) > 1:
            add(index, item, "baseline_duplicate_id", "Baseline id must be unique")
        if isinstance(fingerprint, str) and valid_fingerprints.count(fingerprint) > 1:
            add(index, item, "baseline_duplicate_fingerprint", "Baseline fingerprint must be unique")
        if current is not None and identity_is_valid and isinstance(fingerprint, str) and not _baseline_has_current(item, current):
            add(index, item, "baseline_orphan", "Baseline no longer matches a current finding and must be removed")
    return sorted(errors, key=lambda item: (int(item["baseline_index"]), str(item["code"])))


def _matches_baseline(finding: Mapping[str, object], baseline: Mapping[str, object]) -> bool:
    if finding.get("rule") == baseline.get("rule") == "public-export-count":
        current_count = finding.get("count")
        maximum = baseline.get("count")
        return (
            finding.get("module") == baseline.get("module")
            and type(current_count) is int
            and type(maximum) is int
            and current_count <= maximum
        )
    return (
        baseline.get("fingerprint") == finding_fingerprint(finding)
        and baseline.get("rule") == finding.get("rule")
    )


def classify_findings_against_baseline(
    findings: Iterable[dict[str, object]],
    baseline: Iterable[dict[str, object]],
    *,
    governed_rules: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    finding_items = list(findings)
    baseline_items = list(baseline)
    scope = set(governed_rules) if governed_rules is not None else {
        item["rule"] for item in finding_items if isinstance(item.get("rule"), str)
    }
    scoped_baseline = [
        item for item in baseline_items
        if not isinstance(item.get("rule"), str) or item.get("rule") in scope
    ]
    errors = validate_architecture_baseline(scoped_baseline, finding_items)
    invalid_indexes = {int(item["baseline_index"]) for item in errors}
    valid_baseline = [
        item for index, item in enumerate(scoped_baseline) if index not in invalid_indexes
    ]
    classified: list[dict[str, object]] = []
    ratchet_diagnostics: list[dict[str, object]] = []
    for finding in finding_items:
        match = next((item for item in valid_baseline if _matches_baseline(finding, item)), None)
        result = dict(finding)
        if match is None:
            result.update(
                baseline_status="new",
                baseline_id=None,
                blocking=str(finding.get("severity", "P1")) in {"P0", "P1"},
            )
        else:
            result.update(
                baseline_status="existing_debt",
                baseline_id=match.get("id"),
                owner=match.get("owner"),
                exit_stage=match.get("exit_stage"),
                blocking=False,
            )
            if finding.get("rule") == "public-export-count" and finding.get("count") != match.get("count"):
                result.update(
                    baseline_update_required=True,
                    baseline_previous_count=match.get("count"),
                    recommended_action="lower_or_remove_architecture_baseline",
                )
                ratchet_diagnostics.append({
                    "severity": "P1",
                    "rule": "architecture-baseline-diagnostic",
                    "source": str(match.get("id")),
                    "blocking": True,
                    "baseline_status": "new",
                    "diagnostic_code": "baseline_ratchet_update_required",
                    "baseline_id": match.get("id"),
                    "current_count": finding.get("count"),
                    "baseline_count": match.get("count"),
                    "message": "Lower the public export baseline to the current count before accepting the reduction",
                })
        classified.append(result)
    for error in errors:
        baseline_id = error.get("baseline_id")
        classified.append({
            "severity": "P0",
            "rule": "architecture-baseline-diagnostic",
            "source": baseline_id if isinstance(baseline_id, str) else "<invalid-baseline-id>",
            "blocking": True,
            "baseline_status": "new",
            "diagnostic_code": error["code"],
            "baseline_id": baseline_id,
            "message": error["message"],
        })
    classified.extend(ratchet_diagnostics)
    return classified
