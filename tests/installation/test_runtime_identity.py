from __future__ import annotations

import json

from router_support.runtime_identity import runtime_identity


def _skill_root(tmp_path):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "skill-version.json").write_text(
        json.dumps(
            {
                "skill_version": "0.4.0",
                "reuse_engine_api_version": 2,
                "architecture_governance_api_version": 2,
                "bundle_schema_compatibility": [1],
                "report_schema_version": 3,
                "typed_finding_schema_version": 1,
                "gate_policy_version": 1,
                "change_flow_api_version": 1,
                "authorization_api_version": 1,
            }
        ),
        encoding="utf-8",
    )
    (root / "SKILL.md").write_text("---\nname: sample\ndescription: sample\n---\n", encoding="utf-8")
    return root


def test_runtime_identity_contains_all_cache_and_report_versions(tmp_path) -> None:
    identity = runtime_identity(_skill_root(tmp_path))

    assert identity["skill_version"] == "0.4.0"
    assert identity["typed_finding_schema_version"] == 1
    assert identity["gate_policy_version"] == 1
    assert identity["change_flow_api_version"] == 1
    assert identity["authorization_api_version"] == 1
    assert len(identity["installed_payload_digest"]) == 64
    assert len(identity["identity_digest"]) == 64


def test_runtime_identity_uses_install_manifest_payload_hashes(tmp_path) -> None:
    root = _skill_root(tmp_path)
    manifest = {
        "manifest_schema_version": 3,
        "skill_version": "0.4.0",
        "files": {"SKILL.md": "a" * 64, "skill-version.json": "b" * 64},
    }
    (root / ".installation-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    first = runtime_identity(root)
    (root / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    second = runtime_identity(root)

    assert first["installed_payload_digest"] == second["installed_payload_digest"]
    assert first["installed_payload_source"] == "installation_manifest"


def test_source_payload_change_invalidates_identity(tmp_path) -> None:
    root = _skill_root(tmp_path)
    first = runtime_identity(root)
    (root / "SKILL.md").write_text("changed\n", encoding="utf-8")
    second = runtime_identity(root)

    assert first["installed_payload_digest"] != second["installed_payload_digest"]
    assert first["identity_digest"] != second["identity_digest"]
