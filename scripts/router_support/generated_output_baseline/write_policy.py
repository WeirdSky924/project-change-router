from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from router_support.generated_output_baseline.codec import strict_yaml
from router_support.generated_output_baseline.model import finding
from router_support.profile_loader import CANONICAL_PROFILE_NAMES
from router_support.structure_growth import resolve_git_commit


@dataclass(frozen=True)
class GeneratedOutputWritePolicy:
    current_state: str
    committed_state: str
    comparison_commit: str | None
    protected: bool
    findings: tuple[dict[str, Any], ...]


def generated_output_declaration_state(profile: Mapping[str, Any]) -> str:
    guardrails = profile.get("guardrails")
    if guardrails is None:
        return "absent"
    if not isinstance(guardrails, Mapping):
        return "guardrails_invalid"
    if "generated_output_baseline" not in guardrails:
        return "absent"
    value = guardrails["generated_output_baseline"]
    if isinstance(value, list) and not value:
        return "disabled"
    return "declared"


def generated_output_baseline_is_declared(
    profile: Mapping[str, Any],
) -> bool:
    return generated_output_declaration_state(profile) == "declared"


def _committed_profile(
    repo_root: Path,
) -> tuple[Mapping[str, Any], str | None, list[dict[str, Any]]]:
    try:
        comparison_commit = resolve_git_commit(repo_root, "HEAD")
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
        return {}, None, []
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
        return {}, comparison_commit, [finding(
            "generated_output_committed_profile_unreadable",
            "HEAD",
            "The committed canonical profile could not be inspected safely.",
            error=source_result.stderr.strip() or source_result.stdout.strip(),
        )]
    sources = [
        line.strip()
        for line in source_result.stdout.splitlines()
        if line.strip()
    ]
    if not sources:
        return {}, comparison_commit, []
    if len(sources) != 1:
        return {}, comparison_commit, [finding(
            "generated_output_committed_profile_ambiguous",
            "HEAD",
            "The committed revision contains multiple canonical profile sources.",
            profile_sources=sources,
        )]
    result = subprocess.run(
        ["git", "show", f"{comparison_commit}:{sources[0]}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        return {}, comparison_commit, [finding(
            "generated_output_committed_profile_unreadable",
            sources[0],
            "The committed canonical profile could not be loaded safely.",
            error=result.stderr.strip() or result.stdout.strip(),
        )]
    try:
        profile = strict_yaml(result.stdout)
    except (TypeError, ValueError, yaml.YAMLError) as exc:
        return {}, comparison_commit, [finding(
            "generated_output_committed_profile_unreadable",
            sources[0],
            "The committed canonical profile is malformed.",
            error=str(exc),
        )]
    return profile, comparison_commit, []


def generated_output_write_policy(
    repo_root: Path,
    current_profile: Mapping[str, Any],
) -> GeneratedOutputWritePolicy:
    current_state = generated_output_declaration_state(current_profile)
    committed, comparison_commit, findings = _committed_profile(repo_root)
    committed_state = generated_output_declaration_state(committed)
    committed_unknown = bool(findings)
    protected = (
        current_state == "declared"
        or committed_state == "declared"
        or committed_unknown
    )
    if committed_state == "declared" and current_state != "declared":
        findings.append(finding(
            "generated_output_baseline_removal_not_committed",
            "profile.guardrails.generated_output_baseline",
            "The committed generated-output pin remains active until its lifecycle removal is committed.",
            current_state=current_state,
            committed_state=committed_state,
        ))
    return GeneratedOutputWritePolicy(
        current_state=current_state,
        committed_state=committed_state,
        comparison_commit=comparison_commit,
        protected=protected,
        findings=tuple(findings),
    )
