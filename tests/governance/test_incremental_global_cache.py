from __future__ import annotations

import subprocess

from router_support.incremental_evidence import (
    IncrementalEvidenceCache,
    build_capability_closure,
    build_evidence_input,
    update_incremental_snapshot,
)


def _bundle() -> dict:
    return {
        "config": {"repo_id": "sample"},
        "module_map": {
            "modules": [
                {"path": "app/api", "depends_on": ["app/core"]},
                {"path": "app/core", "depends_on": []},
            ]
        },
        "capability_catalog": {
            "capabilities": [
                {"id": "api", "owner_modules": ["app/api"]},
                {"id": "core", "owner_modules": ["app/core"]},
            ]
        },
        "path_to_capability_map": {
            "path_index": [
                {"path_pattern": "app/api/**", "capabilities": ["api"]},
                {"path_pattern": "app/core/**", "capabilities": ["core"]},
            ]
        },
        "ownership": {"owners": []},
        "change_rules": {},
    }


def test_capability_closure_is_forward_and_reverse() -> None:
    closure = build_capability_closure(_bundle(), {"api"})

    assert closure == {"api", "core"}


def test_cache_hit_requires_exact_runtime_and_evidence_input(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app").mkdir()
    source = repo / "app/core.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    evidence = build_evidence_input(
        repo,
        _bundle(),
        ["app/core.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
    )
    cache = IncrementalEvidenceCache(tmp_path / "runtime")
    cache.save("deps", evidence, {"status": "pass"})

    assert cache.load("deps", evidence)["status"] == "pass"
    changed_identity = {
        **evidence,
        "runtime_identity_digest": "c" * 64,
    }
    assert cache.load("deps", changed_identity) is None


def test_source_or_owner_change_invalidates_evidence_input(tmp_path) -> None:
    repo = tmp_path / "repo"
    source = repo / "app/core.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    before = build_evidence_input(
        repo,
        _bundle(),
        ["app/core.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
    )
    source.write_text("VALUE = 2\n", encoding="utf-8")
    after_source = build_evidence_input(
        repo,
        _bundle(),
        ["app/core.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
    )
    changed_bundle = _bundle()
    changed_bundle["ownership"]["owners"] = [
        {"scope": "capability", "target": "core", "primary": "core-team"}
    ]
    after_owner = build_evidence_input(
        repo,
        changed_bundle,
        ["app/core.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
    )

    assert before["input_digest"] != after_source["input_digest"]
    assert before["input_digest"] != after_owner["input_digest"]


def test_unrelated_worktree_change_does_not_invalidate_closure_input(tmp_path) -> None:
    repo = tmp_path / "repo"
    source = repo / "app/core/value.py"
    unrelated = repo / "docs/notes.md"
    source.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    unrelated.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=PCR Test",
            "-c",
            "user.email=pcr@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    before = build_evidence_input(
        repo,
        _bundle(),
        ["app/core/value.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
        route_capabilities=["core"],
    )
    unrelated.write_text("second\n", encoding="utf-8")
    after = build_evidence_input(
        repo,
        _bundle(),
        ["app/core/value.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
        route_capabilities=["core"],
    )

    assert before["closure_input_digest"] == after["closure_input_digest"]
    assert before["global_input_digest"] != after["global_input_digest"]


def test_incremental_snapshot_reports_reused_and_recomputed_nodes(tmp_path) -> None:
    repo = tmp_path / "repo"
    source = repo / "app/core.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    evidence = build_evidence_input(
        repo,
        _bundle(),
        ["app/core.py"],
        runtime_identity={"identity_digest": "a" * 64},
        structure_digest="b" * 64,
    )

    cold = update_incremental_snapshot(
        tmp_path / "runtime",
        repo_id="repo",
        bundle=_bundle(),
        evidence=evidence,
        route_capabilities=["api"],
    )
    warm = update_incremental_snapshot(
        tmp_path / "runtime",
        repo_id="repo",
        bundle=_bundle(),
        evidence=evidence,
        route_capabilities=["api"],
    )

    assert cold["recomputed_node_count"] == cold["node_count"]
    assert cold["recomputed_edge_count"] == cold["edge_count"]
    assert cold["affected_node_count"] == cold["node_count"]
    assert warm["reused_node_count"] == warm["node_count"]
    assert warm["reused_edge_count"] == warm["edge_count"]
    assert warm["affected_node_count"] == 0
    assert warm["route_capability_closure"] == ["api", "core"]
