from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import router_core
from router_support.freshness_checks import build_structure_snapshot


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


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.test")
    _git(repo, "config", "user.name", "PCR Test")


def test_fresh_rebuild_maps_committed_github_workflow_change(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / ".gitignore", "project-change-router/\n")
    workflow = _write(
        repo / ".github/workflows/ci.yml",
        "name: ci\non: push\n",
    )
    base_commit = _commit(repo, "base")
    workflow.write_text("name: ci\non: [push, pull_request]\n", encoding="utf-8")
    _commit(repo, "change workflow")

    router_core.bootstrap_bundle(repo, write=True)
    rebuild = router_core.rebuild_index(repo, write_back=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            base_commit,
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    report = json.loads(result.stdout)

    assert rebuild["status"] == "pass"
    assert ".github/workflows/**" in rebuild["mapped_path_patterns"]
    assert result.returncode == 0, result.stderr
    assert report["changed_paths"] == [".github/workflows/ci.yml"]
    assert report["failure_reasons"] == []
    assert report["unmapped_changed_paths"] == []


def test_extensionless_jenkinsfile_changes_structure_digest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    jenkinsfile = _write(repo / "Jenkinsfile", "pipeline { agent any }\n")
    _commit(repo, "base")
    indexed = build_structure_snapshot(repo, ignored=())

    jenkinsfile.write_text(
        "pipeline { agent none }\n",
        encoding="utf-8",
    )
    current = build_structure_snapshot(repo, ignored=())

    assert "Jenkinsfile" in indexed.paths
    assert indexed.paths == current.paths
    assert indexed.digest != current.digest


def test_extensionless_ci_surface_descendant_changes_structure_digest(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    hook = _write(repo / ".buildkite/hooks/pre-command", "prepare one\n")
    _commit(repo, "base")
    indexed = build_structure_snapshot(repo, ignored=())

    hook.write_text("prepare two\n", encoding="utf-8")
    current = build_structure_snapshot(repo, ignored=())

    assert ".buildkite/hooks/pre-command" in indexed.paths
    assert indexed.paths == current.paths
    assert indexed.digest != current.digest
