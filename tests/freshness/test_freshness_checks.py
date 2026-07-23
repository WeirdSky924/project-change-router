from __future__ import annotations

import json
import os
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
    collect_git_changed_paths,
    repository_freshness_report,
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


def _commit_all(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")


def test_structure_snapshot_uses_content_not_mtime_or_progress_reports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = _write(repo / "app" / "service.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(repo / ".claude" / "CLAUDE.md", "must not be read by Codex freshness\n")
    report = _write(repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json", "{}\n")
    plan = _write(repo / "docs" / "superpowers" / "plans" / "ACTIVE__test.md", "# Active\n")
    _commit_all(repo)

    initial = build_structure_snapshot(repo, ignored=())
    os.utime(source, None)
    after_mtime = build_structure_snapshot(repo, ignored=())
    report.write_text('{"status":"new"}\n', encoding="utf-8")
    plan.write_text("# Active\n\nProgress only.\n", encoding="utf-8")
    after_progress = build_structure_snapshot(repo, ignored=())
    source.write_text("VALUE = 2\n", encoding="utf-8")
    after_source = build_structure_snapshot(repo, ignored=())

    assert initial.source_commit == _git(repo, "rev-parse", "HEAD").stdout.strip()
    assert initial.digest == after_mtime.digest == after_progress.digest
    assert initial.paths == after_mtime.paths == after_progress.paths
    assert after_source.digest != initial.digest
    assert "project-change-router/reports/index-rebuild/latest.json" not in initial.paths
    assert "docs/superpowers/plans/ACTIVE__test.md" not in initial.paths
    assert ".claude/CLAUDE.md" not in initial.paths


@pytest.mark.parametrize(
    ("manifest_name", "initial_content", "updated_content"),
    [
        ("requirements.txt", "fastapi==1.0\n", "fastapi==2.0\n"),
        ("Dockerfile", "FROM python:3.12\n", "FROM python:3.13\n"),
        ("pom.xml", "<project><version>1</version></project>\n", "<project><version>2</version></project>\n"),
    ],
)
def test_structure_snapshot_tracks_manifest_changes_without_a_new_commit(
    tmp_path: Path,
    manifest_name: str,
    initial_content: str,
    updated_content: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    manifest = _write(repo / manifest_name, initial_content)
    _commit_all(repo)

    indexed = build_structure_snapshot(repo, ignored=())
    manifest.write_text(updated_content, encoding="utf-8")
    current = build_structure_snapshot(repo, ignored=())

    assert current.source_commit == indexed.source_commit
    assert manifest_name in indexed.paths == current.paths
    assert current.digest != indexed.digest


def test_structure_snapshot_tracks_extensionless_executable_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    executable = _write(repo / "bin" / "tool", "#!/bin/sh\necho one\n")
    executable.chmod(0o755)
    plain = _write(repo / "bin" / "note", "not executable\n")
    _commit_all(repo)

    indexed = build_structure_snapshot(repo, ignored=())
    executable.write_text("#!/bin/sh\necho two\n", encoding="utf-8")
    plain.write_text("still not executable\n", encoding="utf-8")
    current = build_structure_snapshot(repo, ignored=())
    report = assess_index_freshness(
        current,
        {
            "source_commit": indexed.source_commit,
            "structure_digest": indexed.digest,
            "indexed_paths": list(indexed.paths),
            "mapped_path_patterns": ["bin/**"],
            "stale_entries": [],
            "diagnostics": [],
            "status": "pass",
        },
        changed_paths=["bin/tool"],
    )

    assert indexed.paths == current.paths == ("bin/tool",)
    assert current.digest != indexed.digest
    assert report["status"] == "fail"
    assert report["failure_reasons"] == ["structure_digest"]


def test_structure_snapshot_uses_shared_json_report_exclusions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    progress = _write(repo / ".refactor_progress.json", '{"step": 1}\n')
    report = _write(repo / "audit" / "reports" / "latest.json", '{"run": 1}\n')
    governed = _write(
        repo / "docs" / "governance" / "rules.json",
        '{"rule": 1}\n',
    )
    _commit_all(repo)

    initial = build_structure_snapshot(repo, ignored=())
    progress.write_text('{"step": 2}\n', encoding="utf-8")
    report.write_text('{"run": 2}\n', encoding="utf-8")
    after_reports = build_structure_snapshot(repo, ignored=())
    governed.write_text('{"rule": 2}\n', encoding="utf-8")
    after_governance = build_structure_snapshot(repo, ignored=())

    assert initial.paths == ("docs/governance/rules.json",)
    assert after_reports.digest == initial.digest
    assert after_governance.digest != initial.digest


def test_global_ignore_pattern_cannot_hide_source_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = _write(repo / "app" / "service.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _commit_all(repo)

    indexed_snapshot = build_structure_snapshot(repo, ignored=("**",))
    source.write_text("VALUE = 2\n", encoding="utf-8")
    current_snapshot = build_structure_snapshot(repo, ignored=("**",))
    report = assess_index_freshness(
        current_snapshot,
        {
            "source_commit": indexed_snapshot.source_commit,
            "structure_digest": indexed_snapshot.digest,
            "indexed_paths": list(indexed_snapshot.paths),
            "mapped_path_patterns": ["app/**"],
            "stale_entries": [],
        },
        changed_paths=["app/service.py"],
    )

    assert report["status"] == "fail"
    assert "snapshot_diagnostics" in report["failure_reasons"]
    assert "unsafe-global-ignore-pattern:**" in report["diagnostics"]


def test_changed_path_excluded_by_user_ignore_is_blocking(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = _write(repo / "app" / "service.py", "VALUE = 1\n")
    _write(repo / "README.md", "# Visible structure\n")
    _commit_all(repo)

    indexed_snapshot = build_structure_snapshot(repo, ignored=("app/**",))
    source.write_text("VALUE = 2\n", encoding="utf-8")
    current_snapshot = build_structure_snapshot(repo, ignored=("app/**",))
    report = assess_index_freshness(
        current_snapshot,
        {
            "source_commit": indexed_snapshot.source_commit,
            "structure_digest": indexed_snapshot.digest,
            "indexed_paths": list(indexed_snapshot.paths),
            "mapped_path_patterns": ["app/**"],
            "stale_entries": [],
        },
        changed_paths=["app/service.py"],
    )

    assert report["status"] == "fail"
    assert "changed_path_snapshot_coverage" in report["failure_reasons"]
    assert report["excluded_changed_paths"] == ["app/service.py"]


def test_assessment_requires_matching_commit_digest_paths_and_clean_stale_entries() -> None:
    current = StructureSnapshot(
        source_commit="commit-a",
        digest="digest-a",
        paths=("app/a.py", ".project-change-router.yaml"),
        diagnostics=(),
    )
    indexed = {
        "source_commit": "commit-a",
        "structure_digest": "digest-a",
        "indexed_paths": [".project-change-router.yaml", "app/a.py"],
        "mapped_path_patterns": [".project-change-router.yaml", "app/**"],
        "stale_entries": [],
        "diagnostics": [],
        "status": "pass",
    }

    report = assess_index_freshness(current, indexed, changed_paths=["app/a.py"])

    assert report["status"] == "pass"
    assert report["unmapped_changed_paths"] == []
    assert all(check["passed"] for check in report["checks"])


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_commit", "commit-b", "source_commit"),
        ("structure_digest", "digest-b", "structure_digest"),
        ("indexed_paths", ["app/a.py"], "indexed_paths"),
        ("stale_entries", [{"path": "app/old.py"}], "stale_entries"),
    ],
)
def test_assessment_fails_each_stale_index_dimension(field: str, value: object, reason: str) -> None:
    current = StructureSnapshot("commit-a", "digest-a", ("app/a.py", ".project-change-router.yaml"), ())
    indexed = {
        "source_commit": "commit-a",
        "structure_digest": "digest-a",
        "indexed_paths": [".project-change-router.yaml", "app/a.py"],
        "mapped_path_patterns": [".project-change-router.yaml", "app/**"],
        "stale_entries": [],
    }
    indexed[field] = value

    report = assess_index_freshness(current, indexed, changed_paths=["app/a.py"])

    assert report["status"] == "fail"
    assert reason in report["failure_reasons"]


def test_assessment_fails_unmapped_changes_and_snapshot_diagnostics() -> None:
    current = StructureSnapshot("commit-a", "digest-a", ("app/a.py",), ("read-error:app/b.py",))
    indexed = {
        "source_commit": "commit-a",
        "structure_digest": "digest-a",
        "indexed_paths": ["app/a.py"],
        "mapped_path_patterns": ["app/**"],
        "stale_entries": [],
    }

    report = assess_index_freshness(current, indexed, changed_paths=["docs/unknown.md"])

    assert report["status"] == "fail"
    assert report["unmapped_changed_paths"] == ["docs/unknown.md"]
    assert "changed_path_coverage" in report["failure_reasons"]
    assert "snapshot_diagnostics" in report["failure_reasons"]


def test_collect_git_changed_paths_covers_all_worktree_states(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "staged.py", "old\n")
    _write(repo / "unstaged.py", "old\n")
    _write(repo / "deleted.py", "old\n")
    _commit_all(repo)
    _write(repo / "staged.py", "new\n")
    _git(repo, "add", "staged.py")
    _write(repo / "unstaged.py", "new\n")
    (repo / "deleted.py").unlink()
    _write(repo / "untracked.py", "new\n")

    assert collect_git_changed_paths(repo) == (
        "deleted.py",
        "staged.py",
        "unstaged.py",
        "untracked.py",
    )


def test_collect_git_changed_paths_merges_committed_and_worktree_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    committed = _write(repo / "committed.py", "old\n")
    _write(repo / "staged.py", "old\n")
    _write(repo / "unstaged.py", "old\n")
    _commit_all(repo)
    comparison_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    committed.write_text("new\n", encoding="utf-8")
    _write(repo / "committed-new.py", "new\n")
    _commit_all(repo)
    _write(repo / "staged.py", "new\n")
    _git(repo, "add", "staged.py")
    _write(repo / "unstaged.py", "new\n")
    _write(repo / "untracked.py", "new\n")

    assert collect_git_changed_paths(repo, comparison_commit) == (
        "committed-new.py",
        "committed.py",
        "staged.py",
        "unstaged.py",
        "untracked.py",
    )


def test_cli_accepts_repeated_changed_paths_and_fails_unmapped_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app" / "a.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(repo / "project-change-router" / "router-config.yaml", "ignore_paths: []\n")
    _commit_all(repo)
    snapshot = build_structure_snapshot(repo, ignored=())
    indexed = {
        "source_commit": snapshot.source_commit,
        "structure_digest": snapshot.digest,
        "indexed_paths": list(snapshot.paths),
        "mapped_path_patterns": [".project-change-router.yaml", "app/**", "project-change-router/**"],
        "stale_entries": [],
        "diagnostics": [],
        "status": "pass",
    }
    _write(
        repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json",
        json.dumps(indexed),
    )
    command = [
        sys.executable,
        str(SCRIPTS / "check_index_freshness.py"),
        "--repo",
        str(repo),
        "--format",
        "json",
    ]

    passed = subprocess.run(
        [*command, "--changed-path", "app/a.py", "--changed-path", ".project-change-router.yaml"],
        text=True,
        capture_output=True,
    )
    failed = subprocess.run(
        [*command, "--changed-path", "docs/unknown.md"],
        text=True,
        capture_output=True,
    )

    assert passed.returncode == 0, passed.stderr
    assert json.loads(passed.stdout)["changed_paths"] == [
        ".project-change-router.yaml",
        "app/a.py",
        "project-change-router/reports/index-rebuild/latest.json",
    ]
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["unmapped_changed_paths"] == ["docs/unknown.md"]


def test_cli_explicit_paths_cannot_hide_real_worktree_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app" / "a.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(repo / "project-change-router" / "router-config.yaml", "ignore_paths: []\n")
    _commit_all(repo)
    snapshot = build_structure_snapshot(repo, ignored=())
    _write(
        repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json",
        json.dumps(
            {
                "source_commit": snapshot.source_commit,
                "structure_digest": snapshot.digest,
                "indexed_paths": list(snapshot.paths),
                "mapped_path_patterns": ["app/**", "project-change-router/**"],
                "stale_entries": [],
                "diagnostics": [],
                "status": "pass",
            }
        ),
    )
    _write(repo / "outside" / "unmapped.py", "VALUE = 2\n")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--changed-path",
            "app/a.py",
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert "outside/unmapped.py" in report["changed_paths"]
    assert report["unmapped_changed_paths"] == ["outside/unmapped.py"]


def test_repository_explicit_paths_cannot_hide_real_worktree_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app/a.py", "VALUE = 1\n")
    _commit_all(repo)
    snapshot = build_structure_snapshot(repo, ignored=())
    bundle_root = repo / "project-change-router"
    _write(
        bundle_root / "reports/index-rebuild/latest.json",
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
    _write(repo / "outside/unmapped.py", "VALUE = 2\n")

    report = repository_freshness_report(
        repo,
        bundle_root,
        (),
        changed_paths=["app/a.py"],
    )

    assert report["status"] == "fail"
    assert "outside/unmapped.py" in report["changed_paths"]
    assert report["unmapped_changed_paths"] == ["outside/unmapped.py"]


def test_cli_accepts_ancestor_index_commit_with_identical_snapshot(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = _write(repo / "app" / "a.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(repo / "project-change-router" / "router-config.yaml", "ignore_paths: []\n")
    _commit_all(repo)
    indexed_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    source.write_text("VALUE = 2\n", encoding="utf-8")
    generated_snapshot = build_structure_snapshot(repo, ignored=())
    _write(
        repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json",
        json.dumps(
            {
                "source_commit": indexed_commit,
                "structure_digest": generated_snapshot.digest,
                "indexed_paths": list(generated_snapshot.paths),
                "mapped_path_patterns": ["app/**", "project-change-router/**"],
                "stale_entries": [],
                "diagnostics": [],
                "status": "pass",
            }
        ),
    )
    _commit_all(repo)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)
    source_check = next(
        check for check in report["checks"] if check["name"] == "source_commit"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert source_check["details"]["match_mode"] == "ancestor_exact_snapshot"

    latest_path = (
        repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json"
    )
    symbolic = json.loads(latest_path.read_text(encoding="utf-8"))
    symbolic["source_commit"] = "HEAD~1"
    latest_path.write_text(json.dumps(symbolic), encoding="utf-8")
    symbolic_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    symbolic_report = json.loads(symbolic_result.stdout)

    assert symbolic_result.returncode == 2
    assert "source_commit" in symbolic_report["failure_reasons"]


def test_system_managed_bundle_paths_are_visible_and_covered() -> None:
    config_path = "project-change-router/router-config.yaml"
    current = StructureSnapshot(
        source_commit="b" * 40,
        digest="digest",
        paths=("app/a.py", config_path),
        diagnostics=(),
    )
    indexed = {
        "source_commit": "b" * 40,
        "structure_digest": "digest",
        "indexed_paths": ["app/a.py", config_path],
        "mapped_path_patterns": ["app/**"],
        "stale_entries": [],
        "diagnostics": [],
        "status": "pass",
    }

    report = assess_index_freshness(
        current,
        indexed,
        changed_paths=[config_path],
        system_path_patterns=[config_path],
    )

    assert report["status"] == "pass"
    assert report["changed_paths"] == ["project-change-router/router-config.yaml"]
    assert report["system_managed_changed_paths"] == [
        "project-change-router/router-config.yaml"
    ]


@pytest.mark.parametrize(
    ("status", "diagnostics", "expected_reason"),
    (
        ("fail", [], "indexed_snapshot_status"),
        ("pass", ["parser-error"], "indexed_snapshot_diagnostics"),
    ),
)
def test_indexed_failure_evidence_is_blocking_even_at_exact_head(
    status: str,
    diagnostics: list[str],
    expected_reason: str,
) -> None:
    current = StructureSnapshot(
        source_commit="b" * 40,
        digest="digest",
        paths=("app/a.py",),
        diagnostics=(),
    )
    indexed = {
        "source_commit": "b" * 40,
        "structure_digest": "digest",
        "indexed_paths": ["app/a.py"],
        "mapped_path_patterns": ["app/**"],
        "stale_entries": [],
        "status": status,
        "diagnostics": diagnostics,
    }

    report = assess_index_freshness(current, indexed)

    assert report["status"] == "fail"
    assert expected_reason in report["failure_reasons"]


def test_cli_comparison_commit_fails_clean_committed_unmapped_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / ".gitignore", "project-change-router/reports/\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(repo / "app" / "a.py", "VALUE = 1\n")
    existing = _write(repo / "outside" / "existing.py", "VALUE = 1\n")
    _write(repo / "project-change-router" / "router-config.yaml", "ignore_paths: []\n")
    _commit_all(repo)
    comparison_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()
    existing.write_text("VALUE = 2\n", encoding="utf-8")
    _write(repo / "outside" / "new.py", "VALUE = 3\n")
    _commit_all(repo)
    snapshot = build_structure_snapshot(repo, ignored=())
    _write(
        repo / "project-change-router" / "reports" / "index-rebuild" / "latest.json",
        json.dumps(
            {
                "source_commit": snapshot.source_commit,
                "structure_digest": snapshot.digest,
                "indexed_paths": list(snapshot.paths),
                "mapped_path_patterns": [
                    ".project-change-router.yaml",
                    "app/**",
                    "project-change-router/**",
                ],
                "stale_entries": [],
                "diagnostics": [],
                "status": "pass",
            }
        ),
    )
    assert _git(repo, "status", "--porcelain").stdout == ""
    command = [
        sys.executable,
        str(SCRIPTS / "check_index_freshness.py"),
        "--repo",
        str(repo),
        "--comparison-commit",
        comparison_commit,
        "--format",
        "json",
    ]

    result = subprocess.run(command, text=True, capture_output=True)
    report = json.loads(result.stdout)

    assert result.returncode == 2, result.stderr
    assert report["failure_reasons"] == ["changed_path_coverage"]
    assert report["unmapped_changed_paths"] == [
        "outside/existing.py",
        "outside/new.py",
    ]


def test_index_report_schema_requires_freshness_truth_fields() -> None:
    schema_path = SKILL_ROOT / "schemas" / "index-rebuild-report.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = {
        "source_commit",
        "structure_digest",
        "indexed_paths",
        "mapped_path_patterns",
        "diagnostics",
        "stale_entries",
    }

    assert required <= set(schema["required"])
    source_schema = schema["properties"]["source_commit"]
    assert source_schema == {
        "oneOf": [
            {"type": "null"},
            {
                "type": "string",
                "pattern": "^[0-9a-f]{40}([0-9a-f]{24})?$",
            },
        ]
    }
    assert required <= set(schema["properties"])


@pytest.mark.parametrize("payload", ([], 1, "invalid", None))
def test_cli_rejects_non_object_latest_report_without_traceback(
    tmp_path: Path,
    payload: object,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app" / "a.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(
        repo / "project-change-router" / "router-config.yaml",
        "ignore_paths: []\n",
    )
    _commit_all(repo)
    _write(
        repo / "project-change-router/reports/index-rebuild/latest.json",
        json.dumps(payload),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert "indexed_snapshot_schema" in report["failure_reasons"]
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "field",
    ("indexed_paths", "mapped_path_patterns", "stale_entries", "diagnostics"),
)
def test_cli_rejects_non_array_latest_report_fields(
    tmp_path: Path,
    field: str,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "app" / "a.py", "VALUE = 1\n")
    _write(repo / ".project-change-router.yaml", "capabilities: []\n")
    _write(
        repo / "project-change-router" / "router-config.yaml",
        "ignore_paths: []\n",
    )
    _commit_all(repo)
    snapshot = build_structure_snapshot(repo, ignored=())
    indexed: dict[str, object] = {
        "source_commit": snapshot.source_commit,
        "structure_digest": snapshot.digest,
        "indexed_paths": list(snapshot.paths),
        "mapped_path_patterns": ["app/**", "project-change-router/**"],
        "stale_entries": [],
        "diagnostics": [],
        "status": "pass",
    }
    indexed[field] = 7
    _write(
        repo / "project-change-router/reports/index-rebuild/latest.json",
        json.dumps(indexed),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert result.returncode == 2
    assert "indexed_snapshot_schema" in report["failure_reasons"]
    assert "Traceback" not in result.stderr
