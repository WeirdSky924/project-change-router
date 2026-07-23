from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from router_support.generated_output_baseline.model import PCR_BUNDLE_ARTIFACTS
from router_support.generated_output_baseline.verification import (
    verify_generated_output_baseline,
)
from router_support.generated_output_baseline.write_policy import (
    GeneratedOutputWritePolicy,
    generated_output_write_policy,
)


@dataclass(frozen=True)
class GeneratedOutputWriteDecision:
    policy: GeneratedOutputWritePolicy
    write_allowed: bool
    preserve_bundle_keys: frozenset[str]
    findings: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]


class GeneratedOutputWriteBlocked(RuntimeError):
    pass


def assess_generated_output_write(
    repo_root: Path,
    profile: Mapping[str, Any],
    expected_bundle: Mapping[str, Mapping[str, Any]] | None,
    *,
    initialization_fingerprint: str | None = None,
    rebuild_error: str | None = None,
    comparison_commit: str | None = None,
    enforce_provenance: bool = True,
) -> GeneratedOutputWriteDecision:
    policy = generated_output_write_policy(repo_root, profile)
    if not policy.protected:
        return GeneratedOutputWriteDecision(
            policy=policy,
            write_allowed=True,
            preserve_bundle_keys=frozenset(),
            findings=(),
            evidence=(),
        )

    findings = list(policy.findings)
    evidence: tuple[dict[str, Any], ...] = ()
    verified_paths: frozenset[str] = frozenset()
    if policy.current_state == "declared":
        verification = verify_generated_output_baseline(
            repo_root,
            profile,
            expected_bundle,
            comparison_commit=comparison_commit or policy.comparison_commit,
            enforce_provenance=enforce_provenance,
            initialization_fingerprint=initialization_fingerprint,
            rebuild_error=rebuild_error,
        )
        findings.extend(verification.findings)
        evidence = verification.evidence
        verified_paths = verification.verified_paths
    expected_paths = frozenset(PCR_BUNDLE_ARTIFACTS.values())
    write_allowed = not findings and verified_paths == expected_paths
    return GeneratedOutputWriteDecision(
        policy=policy,
        write_allowed=write_allowed,
        preserve_bundle_keys=frozenset(PCR_BUNDLE_ARTIFACTS),
        findings=tuple(findings),
        evidence=evidence,
    )


def assert_bootstrap_write_allowed(
    repo_root: Path,
    profile: Mapping[str, Any],
) -> None:
    policy = generated_output_write_policy(repo_root, profile)
    if policy.protected:
        raise GeneratedOutputWriteBlocked(
            "generated output pin protects the existing router references; "
            "use the verified rebuild flow or commit an explicit lifecycle removal"
        )
