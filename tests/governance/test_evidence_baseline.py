from __future__ import annotations

import json

import pytest

from router_support.evidence_baseline import (
    EvidenceBaselineStore,
    baseline_binding,
    classify_against_baseline,
)
from router_support.typed_findings import TypedFinding


def _binding(**overrides: str) -> dict[str, str]:
    values = {
        "commit": "a" * 40,
        "profile_digest": "b" * 64,
        "bundle_digest": "c" * 64,
        "structure_digest": "d" * 64,
        "indexed_paths_digest": "e" * 64,
        "tool_version": "0.4.0",
        "policy_version": "1",
        "evidence_digest": "f" * 64,
    }
    values.update(overrides)
    return baseline_binding(**values)


def _finding(line_count: int = 1300) -> TypedFinding:
    return TypedFinding.create(
        type="central_growth",
        severity="P1",
        invariant_class="always_global",
        origin="structure",
        delta_state="unknown",
        task_relevance="unrelated",
        evidence_status="complete",
        policy_rule_id="GATE-STRUCTURE-001",
        paths=["legacy/router.py"],
        capabilities=["legacy"],
        evidence={"line_count": line_count},
    )


def test_candidate_cannot_be_promoted_from_dirty_or_incomplete_evidence(
    tmp_path,
) -> None:
    store = EvidenceBaselineStore(tmp_path)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=False,
        evidence_complete=False,
    )

    with pytest.raises(ValueError, match="clean worktree"):
        store.promote(candidate["snapshot_fingerprint"], authority="user:accepted")


def test_explicit_promotion_binds_all_identity_fields(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )

    baseline = store.promote(
        candidate["snapshot_fingerprint"], authority="user:accepted"
    )
    persisted = json.loads(
        (tmp_path / "baselines" / "repo.json").read_text(encoding="utf-8")
    )

    assert baseline["state"] == "trusted_baseline"
    assert persisted["binding"] == _binding()
    assert persisted["promotion_authority"] == "user:accepted"


def test_identity_change_invalidates_trusted_baseline(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )
    store.promote(candidate["snapshot_fingerprint"], authority="ci:verified")

    loaded = store.load_trusted("repo", _binding(profile_digest="1" * 64))

    assert loaded is None


def test_unchanged_finding_requires_trusted_matching_baseline(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )
    baseline = store.promote(
        candidate["snapshot_fingerprint"], authority="user:accepted"
    )

    unchanged = classify_against_baseline([_finding()], baseline)
    expanded = classify_against_baseline([_finding(1500)], baseline)

    assert unchanged[0].delta_state == "baseline_unchanged"
    assert expanded[0].delta_state == "task_local_expanded"


def test_complete_snapshot_emits_resolved_baseline_findings(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )
    baseline = store.promote(
        candidate["snapshot_fingerprint"], authority="user:accepted"
    )

    resolved = classify_against_baseline([], baseline, evidence_complete=True)
    incomplete = classify_against_baseline([], baseline, evidence_complete=False)

    assert [item.delta_state for item in resolved] == ["resolved"]
    assert incomplete == []


def test_scope_binding_prevents_cross_task_baseline_reuse(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    first_binding = _binding(scope_digest="1" * 64)
    candidate = store.record_candidate(
        repo_id="repo",
        binding=first_binding,
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )
    store.promote(candidate["snapshot_fingerprint"], authority="ci:verified")

    assert store.load_trusted("repo", first_binding) is not None
    assert store.load_trusted(
        "repo", _binding(scope_digest="2" * 64)
    ) is None


def test_repromotion_preserves_superseded_baseline_history(tmp_path) -> None:
    store = EvidenceBaselineStore(tmp_path)
    first = store.record_candidate(
        repo_id="repo",
        binding=_binding(),
        findings=[_finding()],
        clean_worktree=True,
        evidence_complete=True,
    )
    store.promote(first["snapshot_fingerprint"], authority="ci:verified")
    second = store.record_candidate(
        repo_id="repo",
        binding=_binding(evidence_digest="0" * 64),
        findings=[_finding(1400)],
        clean_worktree=True,
        evidence_complete=True,
    )
    store.promote(second["snapshot_fingerprint"], authority="user:accepted")

    historical = json.loads(
        (
            tmp_path
            / "baselines"
            / "history"
            / f"{first['snapshot_fingerprint']}.json"
        ).read_text(encoding="utf-8")
    )
    assert historical["state"] == "superseded"
    assert historical["superseded_by"] == second["snapshot_fingerprint"]
