from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from router_support.freshness_checks import (
    StructureSnapshot,
    assess_index_freshness,
    build_structure_snapshot,
    repository_freshness_report,
)


CANONICAL_INPUT_PATHS = (
    "project-change-router/router-config.yaml",
    "project-change-router/references/capability-catalog.yaml",
    "project-change-router/references/module-map.yaml",
    "project-change-router/references/ownership.yaml",
    "project-change-router/references/change-rules.yaml",
    "project-change-router/references/path-to-capability-map.yaml",
    "project-change-router/references/exception-registry.yaml",
    "project-change-router/references/evaluation-set.yaml",
    "project-change-router/schemas/router-config.schema.json",
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.test")
    _git(repo, "config", "user.name", "PCR Test")


def _write_latest(repo: Path, snapshot: StructureSnapshot) -> None:
    _write(
        repo / "project-change-router/reports/index-rebuild/latest.json",
        json.dumps(
            {
                "source_commit": snapshot.source_commit,
                "structure_digest": snapshot.digest,
                "indexed_paths": list(snapshot.paths),
                "mapped_path_patterns": ["app/**"],
                "stale_entries": [],
                "diagnostics": [],
                "status": "pass",
            }
        ),
    )


def test_system_managed_label_does_not_cover_unverified_content() -> None:
    current = StructureSnapshot(
        source_commit="b" * 40,
        digest="digest",
        paths=("app/a.py",),
        diagnostics=(),
        ignored_patterns=("project-change-router/**",),
    )
    indexed = {
        "source_commit": "b" * 40,
        "structure_digest": "digest",
        "indexed_paths": ["app/a.py"],
        "mapped_path_patterns": ["app/**"],
        "stale_entries": [],
        "diagnostics": [],
        "status": "pass",
    }

    report = assess_index_freshness(
        current,
        indexed,
        changed_paths=[
            "project-change-router/references/exception-registry.yaml"
        ],
        system_path_patterns=["project-change-router/references/**"],
    )

    assert report["status"] == "fail"
    assert "system_managed_snapshot_coverage" in report["failure_reasons"]


@pytest.mark.parametrize("mutated_path", CANONICAL_INPUT_PATHS)
def test_ignored_canonical_bundle_input_requires_fresh_rebuild_evidence(
    tmp_path: Path,
    mutated_path: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app/a.py", "VALUE = 1\n")
    for path in CANONICAL_INPUT_PATHS:
        _write(repo / path, "version: 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    indexed = build_structure_snapshot(repo, ignored=())
    _write_latest(repo, indexed)

    baseline = repository_freshness_report(
        repo,
        repo / "project-change-router",
        ("project-change-router/**",),
        changed_paths=(),
    )
    assert baseline["status"] == "pass", baseline

    _write(repo / mutated_path, "version: 2\n")
    stale = repository_freshness_report(
        repo,
        repo / "project-change-router",
        ("project-change-router/**",),
        changed_paths=(),
    )

    assert stale["status"] == "fail"
    assert "structure_digest" in stale["failure_reasons"]
    assert mutated_path in stale["system_managed_changed_paths"]


def test_latest_report_remains_snapshot_exempt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app/a.py", "VALUE = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    indexed = build_structure_snapshot(repo, ignored=())
    _write_latest(repo, indexed)

    report = repository_freshness_report(
        repo,
        repo / "project-change-router",
        ("project-change-router/**",),
        changed_paths=(),
    )

    assert report["status"] == "pass", report
    assert report["system_managed_changed_paths"] == [
        "project-change-router/reports/index-rebuild/latest.json"
    ]
