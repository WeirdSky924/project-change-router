from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.generated_output_baseline import (
    make_pinned_generated_output_baseline,
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def create_real_router_repo(
    tmp_path: Path,
    *,
    object_format: str | None = None,
) -> Path:
    repo = tmp_path / "repo"
    service = repo / "services" / "payments" / "service.py"
    service.parent.mkdir(parents=True)
    service.write_text("def charge():\n    return True\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        """profile_id: generated-output-real-bundle
capabilities:
  - id: payment-core
    name: Payment Core
    status: stable
    stage: stable
    path_patterns: ["services/payments/**"]
    keywords: ["payment", "charge"]
    aliases: ["payments"]
    route_defaults:
      preferred_action: reuse
capability_ownership:
  - target: payment-core
    primary: payments-maintainers
    reviewers: [payments-reviewers]
ownership_rules:
  - path_patterns: ["services/payments/**"]
    owner: payments-maintainers
""",
        encoding="utf-8",
    )
    init_args = ["init"]
    if object_format:
        init_args.append(f"--object-format={object_format}")
    git(repo, *init_args)
    git(repo, "config", "user.email", "pcr-tests@example.invalid")
    git(repo, "config", "user.name", "PCR Tests")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial router source")
    return repo


def build_and_write_bundle(repo: Path) -> dict[str, Any]:
    bundle = router_core.build_write_ready_router_bundle(repo)
    router_core.write_bundle(repo / "project-change-router", bundle)
    return bundle


def make_real_rule(
    repo: Path,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    return make_pinned_generated_output_baseline(
        repo,
        bundle,
        baseline_id="PCR-GEN-REAL-001",
        source_commit=git(repo, "rev-parse", "HEAD"),
        owner="payment-core",
        reason="Pin the reviewed real generator output contract.",
        exit_stage="PCR-GEN-CANONICAL-INPUTS",
        exit_condition="Remove after canonical inputs converge.",
        initialization_authorization="Explicit test authorization.",
    )


def profile_with_rule(repo: Path, rule: dict[str, Any]) -> dict[str, Any]:
    profile = yaml.safe_load(
        (repo / ".project-change-router.yaml").read_text(encoding="utf-8")
    )
    profile["guardrails"] = {"generated_output_baseline": [rule]}
    return profile
