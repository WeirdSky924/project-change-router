from __future__ import annotations

import json
import sys
import subprocess
import tempfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def create_sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample-repo"
    (repo / "backend" / "security").mkdir(parents=True)
    (repo / "backend" / "billing").mkdir(parents=True)
    (repo / "frontend").mkdir(parents=True)
    (repo / "pom.xml").write_text(
        """<project><modules><module>backend/security</module><module>backend/billing</module></modules></project>""",
        encoding="utf-8",
    )
    (repo / "backend" / "security" / "pom.xml").write_text(
        """<project><artifactId>security</artifactId><dependencies><dependency><artifactId>billing</artifactId></dependency></dependencies></project>""",
        encoding="utf-8",
    )
    (repo / "backend" / "billing" / "pom.xml").write_text(
        """<project><artifactId>billing</artifactId></project>""",
        encoding="utf-8",
    )
    (repo / "backend" / "security" / "TokenService.java").write_text(
        "package com.example.security; import com.saas.billing.InvoiceService; class TokenService {}",
        encoding="utf-8",
    )
    (repo / "backend" / "billing" / "InvoiceService.java").write_text(
        "package com.example.billing; class InvoiceService {}",
        encoding="utf-8",
    )
    return repo


def test_bootstrap_bundle(tmp_path: Path) -> None:
    repo = create_sample_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    assert bundle_root.exists()
    assert (bundle_root / "router-config.yaml").exists()
    assert bundle["capability_catalog"]["capabilities"]
    assert bundle["module_map"]["modules"]


def test_resolve_request_returns_route(tmp_path: Path) -> None:
    repo = create_sample_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Extend the existing billing payment flow with a new webhook rule",
        ["backend/billing/InvoiceService.java"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action in {"extend", "reuse", "review"}
    assert decision.primary_capability is not None
    assert decision.required_reads


def test_validate_bundle(tmp_path: Path) -> None:
    repo = create_sample_repo(tmp_path)
    router_core.bootstrap_bundle(repo, write=True)
    errors = router_core.validate_bundle_files(repo / "project-change-router")
    assert errors == []


def test_evaluation_runs(tmp_path: Path) -> None:
    repo = create_sample_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    summary = router_core.evaluate_bundle(bundle, repo)
    assert summary["case_count"] >= 1
    assert "top1_action_accuracy" in summary
