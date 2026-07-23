from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

import yaml

from router_support.generated_output_baseline.codec import (
    canonical_text_digest,
    expected_text,
    generated_output_rule_fingerprint,
    semantic_digest,
    strict_yaml,
)
from router_support.generated_output_baseline.contract import (
    expected_artifact_source_commit,
)
from router_support.generated_output_baseline.model import (
    GENERATED_OUTPUT_MODE,
    GENERATOR_ID,
    PCR_BUNDLE_ARTIFACTS,
    finding,
)
from router_support.generated_output_baseline.validation import (
    active_canonical_profile_source,
    validate_generated_output_rules,
)
from router_support.profile_loader import CANONICAL_PROFILE_NAMES
from router_support.structure_growth import (
    git_commit_is_ancestor,
    resolve_git_commit,
)


_FULL_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def resolve_full_immutable_sha(
    repo_root: Path,
    value: str,
    *,
    field: str,
) -> str:
    if not _FULL_SHA.fullmatch(value):
        raise ValueError(f"{field} must be a full immutable Git SHA")
    resolved = resolve_git_commit(repo_root, value)
    if resolved != value:
        raise ValueError(f"{field} must be a full immutable Git SHA")
    return resolved


def _artifact_record(
    repo_root: Path,
    bundle_key: str,
    expected_payload: Mapping[str, Any],
    source_commit: str,
) -> dict[str, Any]:
    relative_path = PCR_BUNDLE_ARTIFACTS[bundle_key]
    path = repo_root / relative_path
    raw_bytes = path.read_bytes()
    raw = raw_bytes.decode("utf-8")
    actual = strict_yaml(raw)
    expected_source_commit = expected_artifact_source_commit(expected_payload)
    if isinstance(expected_source_commit, str):
        resolve_full_immutable_sha(
            repo_root,
            expected_source_commit,
            field=f"{relative_path} source_commit",
        )
    if (
        isinstance(expected_source_commit, str)
        and expected_source_commit != source_commit
    ):
        pinned = resolve_git_commit(repo_root, expected_source_commit)
        initialization = resolve_git_commit(repo_root, source_commit)
        if not git_commit_is_ancestor(repo_root, pinned, initialization):
            raise ValueError(
                f"{relative_path} source_commit is not an ancestor of the initialization source"
            )
    if actual.get("source_commit") != expected_source_commit:
        raise ValueError(
            f"{relative_path} source_commit does not match the canonical rebuild"
        )
    canonical = expected_text(
        expected_payload,
        actual,
        bundle_key=bundle_key,
    )
    if raw_bytes != canonical.encode("utf-8"):
        raise ValueError(
            f"{relative_path} is not the canonical idempotent generator output"
        )
    return {
        "bundle_key": bundle_key,
        "source_commit": expected_source_commit,
        "semantic_digest": semantic_digest(actual, bundle_key=bundle_key),
        "canonical_text_digest": canonical_text_digest(
            actual,
            bundle_key=bundle_key,
        ),
        "line_count": len(raw.splitlines()),
    }


def make_pinned_generated_output_baseline(
    repo_root: Path,
    expected_bundle: Mapping[str, Mapping[str, Any]],
    *,
    baseline_id: str,
    source_commit: str,
    owner: str,
    reason: str,
    exit_stage: str,
    exit_condition: str,
    initialization_authorization: str,
) -> dict[str, Any]:
    resolve_full_immutable_sha(
        repo_root,
        source_commit,
        field="source_commit",
    )
    canonical_source = active_canonical_profile_source(repo_root)
    rule: dict[str, Any] = {
        "id": baseline_id,
        "mode": GENERATED_OUTPUT_MODE,
        "generator_id": GENERATOR_ID,
        "canonical_source": canonical_source,
        "source_commit": source_commit,
        "owner": owner,
        "reason": reason,
        "exit_stage": exit_stage,
        "exit_condition": exit_condition,
        "initialization_authorization": initialization_authorization,
        "artifacts": [
            _artifact_record(repo_root, key, expected_bundle[key], source_commit)
            for key in PCR_BUNDLE_ARTIFACTS
        ],
    }
    rule["fingerprint"] = generated_output_rule_fingerprint(rule)
    return rule


def _comparison_profile_rule(
    repo_root: Path,
    comparison_commit: str,
    canonical_source: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    source_result = subprocess.run(
        [
            "git",
            "ls-tree",
            "--name-only",
            comparison_commit,
            "--",
            *CANONICAL_PROFILE_NAMES,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if source_result.returncode != 0:
        raise ValueError(
            "comparison canonical profile sources cannot be inspected"
        )
    sources = [
        line.strip()
        for line in source_result.stdout.splitlines()
        if line.strip()
    ]
    if len(sources) != 1 or sources[0] != canonical_source:
        raise ValueError(
            "comparison commit must contain exactly the declared canonical profile source"
        )
    result = subprocess.run(
        ["git", "show", f"{comparison_commit}:{canonical_source}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return None
    payload = strict_yaml(result.stdout)
    guardrails = payload.get("guardrails", {})
    if not isinstance(guardrails, Mapping):
        raise ValueError("comparison profile guardrails must be a mapping")
    rules = guardrails.get("generated_output_baseline", [])
    if not rules:
        return None
    if (
        not isinstance(rules, list)
        or len(rules) != 1
        or not isinstance(rules[0], Mapping)
    ):
        raise ValueError(
            "comparison profile has an invalid generated output baseline"
        )
    return payload, rules[0]


def provenance_findings(
    repo_root: Path,
    rule: Mapping[str, Any],
    comparison_commit: str | None,
    initialization_fingerprint: str | None,
) -> list[dict[str, Any]]:
    baseline_id = str(rule.get("id") or "<missing-id>")
    revision = str(comparison_commit or "").strip()
    if not revision:
        return [finding(
            "generated_output_baseline_provenance_incomplete",
            baseline_id,
            "Generated output baseline requires a trusted comparison commit.",
        )]
    try:
        comparison = resolve_git_commit(repo_root, revision)
        source_value = str(rule.get("source_commit") or "")
        source = resolve_full_immutable_sha(
            repo_root,
            source_value,
            field="source_commit",
        )
        if not git_commit_is_ancestor(repo_root, source, comparison):
            raise RuntimeError(
                "baseline source commit is not an ancestor of comparison"
            )
        canonical_source = str(rule.get("canonical_source") or "")
        historical_entry = _comparison_profile_rule(
            repo_root,
            comparison,
            canonical_source,
        )
        if historical_entry is not None:
            historical_profile, historical = historical_entry
            if validate_generated_output_rules(
                historical_profile,
                canonical_source=canonical_source,
            ):
                raise ValueError(
                    "comparison profile generated output baseline is invalid"
                )
        else:
            historical = None
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        yaml.YAMLError,
        ValueError,
    ) as exc:
        return [finding(
            "generated_output_baseline_provenance_incomplete",
            baseline_id,
            "Generated output baseline provenance could not be verified.",
            error=str(exc),
        )]
    if historical is None:
        if (
            source != comparison
            or initialization_fingerprint != rule.get("fingerprint")
        ):
            return [finding(
                "generated_output_baseline_provenance_incomplete",
                baseline_id,
                "A new generated output baseline requires its exact fingerprint as an external initialization authorization at the trusted source commit.",
            )]
        return []
    if historical.get("fingerprint") != rule.get("fingerprint"):
        return [finding(
            "generated_output_baseline_changed_since_comparison",
            baseline_id,
            "Generated output baseline changed after the trusted comparison boundary.",
            comparison_commit=comparison,
        )]
    return []
