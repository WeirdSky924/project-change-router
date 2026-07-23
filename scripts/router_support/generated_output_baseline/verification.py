from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Mapping

import yaml

from router_support.generated_output_baseline.codec import (
    canonical_text_digest,
    expected_text,
    semantic_digest,
    strict_yaml,
)
from router_support.generated_output_baseline.contract import (
    expected_artifact_source_commit,
)
from router_support.generated_output_baseline.model import (
    GeneratedOutputVerification,
    PCR_BUNDLE_ARTIFACTS,
    finding,
)
from router_support.generated_output_baseline.provenance import (
    provenance_findings,
    resolve_full_immutable_sha,
)
from router_support.generated_output_baseline.validation import (
    validate_generated_output_rules,
)
from router_support.structure_growth import (
    git_commit_is_ancestor,
)


def _source_commit_match_mode(
    repo_root: Path,
    *,
    rule_source_commit: str,
    pinned_artifact_source_commit: object,
    actual_source_commit: object,
    rebuilt_source_commit: str | None,
) -> str:
    if pinned_artifact_source_commit is None:
        return (
            "null"
            if actual_source_commit is None and rebuilt_source_commit is None
            else "mismatch"
        )
    if (
        not isinstance(pinned_artifact_source_commit, str)
        or not isinstance(actual_source_commit, str)
        or actual_source_commit != pinned_artifact_source_commit
        or not isinstance(rebuilt_source_commit, str)
    ):
        return "mismatch"
    if (
        pinned_artifact_source_commit == rule_source_commit
        and pinned_artifact_source_commit == rebuilt_source_commit
    ):
        return "pinned_exact"
    try:
        pinned = resolve_full_immutable_sha(
            repo_root,
            pinned_artifact_source_commit,
            field="pinned artifact source_commit",
        )
        rule_source = resolve_full_immutable_sha(
            repo_root,
            rule_source_commit,
            field="rule source_commit",
        )
        rebuilt = resolve_full_immutable_sha(
            repo_root,
            rebuilt_source_commit,
            field="rebuilt artifact source_commit",
        )
        if (
            git_commit_is_ancestor(repo_root, pinned, rule_source)
            and git_commit_is_ancestor(repo_root, pinned, rebuilt)
        ):
            return "pinned_ancestor_rebuild"
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        ValueError,
    ):
        pass
    return "mismatch"


def verify_generated_output_baseline(
    repo_root: Path,
    profile: Mapping[str, Any],
    expected_bundle: Mapping[str, Mapping[str, Any]] | None,
    *,
    comparison_commit: str | None = None,
    enforce_provenance: bool = True,
    initialization_fingerprint: str | None = None,
    rebuild_error: str | None = None,
) -> GeneratedOutputVerification:
    guardrails = profile.get("guardrails", {})
    rules = (
        guardrails.get("generated_output_baseline", [])
        if isinstance(guardrails, Mapping)
        else []
    )
    if not isinstance(guardrails, Mapping):
        findings = validate_generated_output_rules(profile)
        return GeneratedOutputVerification(frozenset(), tuple(findings), ())
    if isinstance(rules, list) and not rules:
        return GeneratedOutputVerification(frozenset(), (), ())
    findings = validate_generated_output_rules(profile, repo_root=repo_root)
    if findings:
        return GeneratedOutputVerification(frozenset(), tuple(findings), ())
    rule = rules[0]
    if enforce_provenance:
        findings.extend(provenance_findings(
            repo_root,
            rule,
            comparison_commit,
            initialization_fingerprint,
        ))
    if expected_bundle is None:
        findings.append(finding(
            (
                "generated_output_rebuild_failed"
                if rebuild_error
                else "generated_output_verification_missing"
            ),
            str(rule["id"]),
            (
                "The no-write generated output rebuild failed."
                if rebuild_error
                else "Generated output verification requires a no-write rebuild payload."
            ),
            **({"error": rebuild_error} if rebuild_error else {}),
        ))
    missing_expected = [
        key
        for key in PCR_BUNDLE_ARTIFACTS
        if expected_bundle is not None and key not in expected_bundle
    ]
    if missing_expected:
        findings.append(finding(
            "generated_output_rebuild_failed",
            str(rule["id"]),
            "The no-write rebuild omitted core generated artifacts.",
            missing_bundle_keys=missing_expected,
        ))
    if findings:
        return GeneratedOutputVerification(frozenset(), tuple(findings), ())

    artifacts = {
        str(item["bundle_key"]): item
        for item in rule["artifacts"]
    }
    evidence: list[dict[str, Any]] = []
    for bundle_key, relative_path in PCR_BUNDLE_ARTIFACTS.items():
        path = repo_root / relative_path
        if not path.is_file():
            findings.append(finding(
                "generated_output_artifact_missing",
                relative_path,
                "A pinned generated output artifact is missing.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
            ))
            continue
        try:
            raw_bytes = path.read_bytes()
            raw = raw_bytes.decode("utf-8")
            actual = strict_yaml(raw)
            expected_payload = expected_bundle[bundle_key]  # type: ignore[index]
            rebuilt_source_commit = expected_artifact_source_commit(
                expected_payload
            )
        except (
            OSError,
            UnicodeError,
            KeyError,
            TypeError,
            ValueError,
            yaml.YAMLError,
        ) as exc:
            findings.append(finding(
                "generated_output_artifact_noncanonical",
                relative_path,
                "A generated output artifact cannot be read as canonical unique-key YAML.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
                error=str(exc),
            ))
            continue

        declared = artifacts[bundle_key]
        actual_source_commit = actual.get("source_commit")
        source_commit_match_mode = _source_commit_match_mode(
            repo_root,
            rule_source_commit=str(rule["source_commit"]),
            pinned_artifact_source_commit=declared.get("source_commit"),
            actual_source_commit=actual_source_commit,
            rebuilt_source_commit=rebuilt_source_commit,
        )
        if source_commit_match_mode == "mismatch":
            findings.append(finding(
                "generated_output_artifact_source_commit_mismatch",
                relative_path,
                "A generated output artifact does not retain the pinned source provenance or the rebuild source mode.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
                rule_source_commit=rule["source_commit"],
                pinned_artifact_source_commit=declared.get("source_commit"),
                rebuilt_source_commit=rebuilt_source_commit,
                actual_source_commit=actual_source_commit,
            ))
            continue
        try:
            canonical = expected_text(
                expected_payload,
                actual,
                bundle_key=bundle_key,
                normalize_source_commit=(
                    source_commit_match_mode == "pinned_ancestor_rebuild"
                ),
            )
            expected_bytes = canonical.encode("utf-8")
            expected = strict_yaml(canonical)
            actual_semantic = semantic_digest(actual, bundle_key=bundle_key)
            expected_semantic = semantic_digest(expected, bundle_key=bundle_key)
            actual_text = canonical_text_digest(actual, bundle_key=bundle_key)
            expected_text_digest = canonical_text_digest(
                expected,
                bundle_key=bundle_key,
            )
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            findings.append(finding(
                "generated_output_artifact_noncanonical",
                relative_path,
                "A generated output artifact contains a non-JSON scalar.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
                error=str(exc),
            ))
            continue
        actual_lines = len(raw.splitlines())
        if raw_bytes != expected_bytes:
            findings.append(finding(
                "generated_output_artifact_noncanonical",
                relative_path,
                "Generated output bytes differ from the canonical no-write rebuild.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
            ))
        if (
            actual_semantic != declared["semantic_digest"]
            or actual_text != declared["canonical_text_digest"]
            or actual_lines != declared["line_count"]
        ):
            findings.append(finding(
                "generated_output_artifact_digest_mismatch",
                relative_path,
                "Generated output no longer matches its pinned semantic, byte, or line snapshot.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
                expected_line_count=declared["line_count"],
                actual_line_count=actual_lines,
            ))
        if (
            expected_semantic != declared["semantic_digest"]
            or expected_text_digest != declared["canonical_text_digest"]
        ):
            findings.append(finding(
                "generated_output_artifact_not_idempotent",
                relative_path,
                "A no-write rebuild does not reproduce the pinned generated output.",
                baseline_id=rule["id"],
                bundle_key=bundle_key,
            ))
        evidence.append({
            "baseline_id": rule["id"],
            "bundle_key": bundle_key,
            "path": relative_path,
            "semantic_digest": actual_semantic,
            "canonical_text_digest": actual_text,
            "line_count": actual_lines,
            "source_commit": actual_source_commit,
            "rebuilt_source_commit": expected_payload.get("source_commit"),
            "source_commit_match_mode": source_commit_match_mode,
            "idempotent": raw_bytes == expected_bytes,
        })

    if findings:
        return GeneratedOutputVerification(
            frozenset(),
            tuple(findings),
            tuple(evidence),
        )
    return GeneratedOutputVerification(
        frozenset(PCR_BUNDLE_ARTIFACTS.values()),
        (),
        tuple(evidence),
    )
