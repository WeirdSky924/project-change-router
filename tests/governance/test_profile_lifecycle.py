from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support import profile_loader


def _write_profile(path: Path, *, profile_id: str, capability_id: str) -> None:
    path.write_text(
        f"""
profile_id: {profile_id}
capabilities:
  - id: {capability_id}
    name: {capability_id}
    path_patterns: ["app/{capability_id}/**"]
evaluation:
  mode: curated
  cases:
    - id: {capability_id}-case
      request: Reuse {capability_id}.
      expected_action: reuse
      expected_capabilities: ["{capability_id}"]
      expected_modules: ["app/{capability_id}"]
      expected_reads: []
      changed_paths: ["app/{capability_id}"]
      risk_level: low
""".lstrip(),
        encoding="utf-8",
    )


def test_canonical_profile_is_the_only_active_source(tmp_path: Path) -> None:
    canonical = tmp_path / ".project-change-router.yaml"
    legacy = tmp_path / "project-change-router.profile.yaml"
    _write_profile(canonical, profile_id="canonical", capability_id="canonical-capability")
    _write_profile(legacy, profile_id="legacy", capability_id="legacy-capability")

    assert router_core.profile_candidates(tmp_path) == [canonical]
    profile = router_core.load_active_profile(tmp_path)
    assert profile["profile_id"] == "canonical"
    assert [item["id"] for item in profile["capabilities"]] == ["canonical-capability"]
    assert [item["id"] for item in profile["evaluation"]["cases"]] == ["canonical-capability-case"]


def test_legacy_profile_remains_a_compatibility_fallback(tmp_path: Path) -> None:
    legacy = tmp_path / "project-change-router.profile.yaml"
    _write_profile(legacy, profile_id="legacy", capability_id="legacy-capability")

    assert router_core.profile_candidates(tmp_path) == [legacy]
    assert router_core.load_active_profile(tmp_path)["profile_id"] == "legacy"


def test_duplicate_canonical_profile_sources_fail_closed(tmp_path: Path) -> None:
    yaml_profile = tmp_path / ".project-change-router.yaml"
    yml_profile = tmp_path / ".project-change-router.yml"
    _write_profile(yaml_profile, profile_id="yaml", capability_id="yaml-capability")
    _write_profile(yml_profile, profile_id="yml", capability_id="yml-capability")

    assert router_core.profile_candidates(tmp_path) == [yaml_profile, yml_profile]
    with pytest.raises(ValueError, match="multiple active profile sources"):
        router_core.load_active_profile(tmp_path)

    findings = router_core.profile_source_lifecycle_findings(tmp_path)
    assert findings[0]["severity"] == "P0"
    assert findings[0]["rule"] == "canonical-profile-source-conflict"
    assert findings[0]["details"]["sources"] == [
        ".project-change-router.yaml",
        ".project-change-router.yml",
    ]


def test_duplicate_legacy_profile_sources_fail_closed(tmp_path: Path) -> None:
    yaml_profile = tmp_path / "project-change-router.profile.yaml"
    yml_profile = tmp_path / "project-change-router.profile.yml"
    _write_profile(yaml_profile, profile_id="yaml", capability_id="yaml-capability")
    _write_profile(yml_profile, profile_id="yml", capability_id="yml-capability")

    with pytest.raises(ValueError, match="multiple active profile sources"):
        router_core.load_active_profile(tmp_path)

    findings = router_core.profile_source_lifecycle_findings(tmp_path)
    assert findings[0]["severity"] == "P0"
    assert findings[0]["rule"] == "legacy-profile-source-conflict"
    assert findings[0]["details"]["sources"] == [
        "project-change-router.profile.yaml",
        "project-change-router.profile.yml",
    ]


def test_skill_repo_name_profile_is_the_last_compatibility_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    repo_root = tmp_path / "workspaces" / "sample-repo"
    repo_root.mkdir(parents=True)
    skill_root = tmp_path / "skill-root"
    skill_profile = skill_root / "profiles" / f"{repo_root.name}.yaml"
    skill_profile.parent.mkdir(parents=True)
    _write_profile(
        skill_profile,
        profile_id="skill-fallback",
        capability_id="skill-capability",
    )
    monkeypatch.setattr(
        profile_loader,
        "__file__",
        str(skill_root / "scripts" / "router_support" / "profile_loader.py"),
    )

    assert router_core.profile_candidates(repo_root) == [skill_profile]
    assert router_core.load_active_profile(repo_root)["profile_id"] == "skill-fallback"

    legacy = repo_root / "project-change-router.profile.yaml"
    _write_profile(legacy, profile_id="legacy", capability_id="legacy-capability")
    assert router_core.profile_candidates(repo_root) == [legacy]

    canonical = repo_root / ".project-change-router.yaml"
    _write_profile(
        canonical,
        profile_id="canonical",
        capability_id="canonical-capability",
    )
    assert router_core.profile_candidates(repo_root) == [canonical]


def test_concurrent_legacy_profile_is_lifecycle_debt(tmp_path: Path) -> None:
    canonical = tmp_path / ".project-change-router.yaml"
    legacy = tmp_path / "project-change-router.profile.yaml"
    _write_profile(canonical, profile_id="canonical", capability_id="canonical-capability")
    _write_profile(legacy, profile_id="legacy", capability_id="legacy-capability")

    findings = router_core.profile_source_lifecycle_findings(tmp_path)

    assert findings == [
        {
            "severity": "P1",
            "rule": "legacy-profile-lifecycle-debt",
            "target": "project-change-router.profile.yaml",
            "message": "A legacy profile exists beside the canonical profile but is not an active source.",
            "recommendation": "Migrate parity, update callers, record rollback metadata, and retire the legacy profile.",
            "details": {
                "active_source": ".project-change-router.yaml",
                "legacy_sources": ["project-change-router.profile.yaml"],
            },
        }
    ]

    legacy.unlink()

    assert router_core.profile_source_lifecycle_findings(tmp_path) == []


def test_implementation_state_list_requires_snapshot_replacement_marker(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / ".project-change-router.yaml"
    canonical.write_text(
        """
profile_id: canonical
capabilities:
  - id: observability-core
    lifecycle:
      implementation_state:
        - execution_trace_repository_verified
        - gateway_trace_methods_removed_verified
""".lstrip(),
        encoding="utf-8",
    )

    assert router_core.profile_source_lifecycle_findings(tmp_path) == [
        {
            "severity": "P1",
            "rule": "capability-lifecycle-list-merge-risk",
            "target": ".project-change-router.yaml",
            "message": (
                "Capability implementation_state lists require exact snapshot "
                "replacement to prevent stale generated lifecycle values."
            ),
            "recommendation": (
                "Set lifecycle.replace_snapshot_boundaries: true after recording "
                "the exact replacement lifecycle."
            ),
            "details": {
                "capability": "observability-core",
                "implementation_state": [
                    "execution_trace_repository_verified",
                    "gateway_trace_methods_removed_verified",
                ],
            },
        }
    ]

    canonical.write_text(
        canonical.read_text(encoding="utf-8").replace(
            "    lifecycle:\n",
            "    lifecycle:\n      replace_snapshot_boundaries: true\n",
        ),
        encoding="utf-8",
    )

    assert router_core.profile_source_lifecycle_findings(tmp_path) == []


def test_retired_profile_source_keeps_a_path_tombstone_without_a_module(tmp_path: Path) -> None:
    canonical = tmp_path / ".project-change-router.yaml"
    canonical.write_text("profile_id: canonical\n", encoding="utf-8")
    module = router_core.ModuleEntry(
        id="module-rebuild-governance-canonical-profile",
        path=".project-change-router.yaml",
        layer="governance",
        domain="rebuild-governance",
        purpose="Canonical PCR profile.",
        source_of_truth="curated",
        generated=False,
        owner="rebuild-governance",
    )
    capability = router_core.CapabilityEntry(
        id="rebuild-governance",
        name="Rebuild Governance",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=[".project-change-router.yaml"],
    )
    profile = {
        "profile_lifecycle": {
            "migrations": [
                {
                    "source": "project-change-router.profile.yaml",
                    "status": "retired",
                    "superseded_by": ".project-change-router.yaml",
                    "route_capability": "rebuild-governance",
                }
            ]
        }
    }

    path_map = router_core.build_path_to_capability_map(tmp_path, [capability], [module], profile)
    retired = next(
        item for item in path_map["path_index"] if item["path_pattern"] == "project-change-router.profile.yaml"
    )

    assert retired["capabilities"] == ["rebuild-governance"]
    assert retired["sources"] == ["profile_lifecycle.migrations"]
    assert retired["modules"] == []
