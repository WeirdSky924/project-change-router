from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.structure_guardrails import gather_structure_findings


def _write(path: Path, content: str = "VALUE = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _python_lines(count: int) -> str:
    return "VALUE = 1\n" + "# line\n" * (count - 1)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-growth@example.invalid")
    _git(repo, "config", "user.name", "Structure Growth Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("baseline_lines", "current_lines", "rule", "severity", "policy"),
    [
        (800, 801, "code-file-size-review-growth", "P1", "review"),
        (1201, 1202, "code-file-size-hard-growth", "P0", "hard_fail"),
    ],
)
def test_large_file_net_growth_is_blocking_inside_existing_bands(
    tmp_path: Path,
    baseline_lines: int,
    current_lines: int,
    rule: str,
    severity: str,
    policy: str,
) -> None:
    repo = tmp_path / "repo"
    path = "app/service.py"
    _write(repo / path, _python_lines(current_lines))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "baseline"}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(
            baseline_lines
        ),
    )

    growth = next(item for item in findings if item["rule"] == rule)
    assert growth["blocking"] is True
    assert growth["severity"] == severity
    assert growth["growth_policy"] == policy
    assert growth["baseline_lines"] == baseline_lines
    assert growth["current_lines"] == current_lines


@pytest.mark.parametrize("baseline_lines,current_lines", [(900, 899), (1202, 1201)])
def test_large_file_reduction_is_not_growth(
    tmp_path: Path,
    baseline_lines: int,
    current_lines: int,
) -> None:
    repo = tmp_path / "repo"
    path = "app/service.py"
    _write(repo / path, _python_lines(current_lines))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "baseline"}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(
            baseline_lines
        ),
    )

    assert not any("size" in item["rule"] and item["blocking"] for item in findings)


def test_missing_comparison_commit_blocks_old_bundle_in_non_git_repo(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    path = "app/legacy_service.py"
    _write(repo / path, _python_lines(1300))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": None}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
    )

    missing = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert missing["source"] == "<comparison-commit>"
    assert missing["blocking"] is True
    assert missing["completion_status"] == "incomplete"
    assert missing["evidence_complete"] is False


def test_explicit_comparison_commit_overrides_missing_bundle_source_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    path = "app/legacy_service.py"
    _write(repo / path, _python_lines(1301))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": None}, "change_rules": {}},
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(1300),
    )

    assert any(item["rule"] == "code-file-size-hard-growth" for item in findings)
    assert not any(item["source"] == "<comparison-commit>" for item in findings)


def test_cli_comparison_commit_detects_growth_in_clean_committed_head(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    path = "app/service.py"
    _write(repo / path, _python_lines(800))
    baseline = _commit(repo, "baseline")
    _write(repo / path, _python_lines(801))
    _commit(repo, "growth")
    assert _git(repo, "status", "--porcelain") == ""

    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_structure.py"),
            "--repo",
            str(repo),
            "--comparison-commit",
            baseline,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    assert report["comparison_commit"] == baseline
    assert any(
        item["rule"] == "code-file-size-review-growth"
        for item in report["findings"]
    )


def _directory_repo(tmp_path: Path, count: int, prefix: str = "item") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    _init_repo(repo)
    for index in range(count):
        _write(repo / "app" / "domain" / f"{prefix}_{index:02d}.py")
    return repo, _commit(repo, "baseline")


@pytest.mark.parametrize(
    ("baseline_count", "growth_kind"),
    [(24, "crossing"), (25, "growth")],
)
def test_immediate_directory_width_crossing_and_growth_are_blocking(
    tmp_path: Path,
    baseline_count: int,
    growth_kind: str,
) -> None:
    repo, baseline = _directory_repo(tmp_path, baseline_count)
    _write(repo / "app" / "domain" / f"added_{baseline_count:02d}.py")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )

    growth = next(
        item for item in findings if item["rule"] == "code-directory-width-growth"
    )
    assert growth["blocking"] is True
    assert growth["growth_kind"] == growth_kind
    assert growth["baseline_count"] == baseline_count
    assert growth["current_count"] == baseline_count + 1


def test_existing_directory_and_prefix_debt_remain_visible_without_blocking(
    tmp_path: Path,
) -> None:
    repo, baseline = _directory_repo(tmp_path, 25, prefix="worker")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )

    directory_debt = next(
        item for item in findings if item["rule"] == "code-directory-width-debt"
    )
    prefix_debt = next(
        item for item in findings if item["rule"] == "same-prefix-sibling-debt"
    )
    assert directory_debt["blocking"] is False
    assert prefix_debt["blocking"] is False
    assert directory_debt["current_count"] == 25
    assert prefix_debt["prefix"] == "worker"
    assert prefix_debt["current_count"] == 25


def test_unchanged_executable_is_counted_in_both_directory_snapshots(
    tmp_path: Path,
) -> None:
    repo, _baseline = _directory_repo(tmp_path, 24)
    executable = _write(repo / "app" / "domain" / "runner", "#!/bin/sh\n")
    executable.chmod(0o755)
    baseline = _commit(repo, "add executable")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )

    assert not any(
        item["rule"] == "code-directory-width-growth" for item in findings
    )
    debt = next(
        item for item in findings if item["rule"] == "code-directory-width-debt"
    )
    assert debt["baseline_count"] == debt["current_count"] == 25


def test_subthreshold_directory_and_prefix_growth_is_not_reported(
    tmp_path: Path,
) -> None:
    repo, baseline = _directory_repo(tmp_path, 3, prefix="worker")
    _write(repo / "app" / "domain" / "worker_03.py")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )

    assert not any(
        item["rule"]
        in {
            "code-directory-width-growth",
            "code-directory-width-debt",
            "same-prefix-sibling-growth",
            "same-prefix-sibling-debt",
        }
        for item in findings
    )


@pytest.mark.parametrize(
    ("baseline_count", "growth_kind"),
    [(7, "crossing"), (8, "growth")],
)
def test_same_prefix_sibling_crossing_and_growth_are_blocking(
    tmp_path: Path,
    baseline_count: int,
    growth_kind: str,
) -> None:
    repo, baseline = _directory_repo(tmp_path, baseline_count, prefix="worker")
    _write(repo / "app" / "domain" / f"worker_{baseline_count:02d}.py")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )

    growth = next(
        item for item in findings if item["rule"] == "same-prefix-sibling-growth"
    )
    assert growth["blocking"] is True
    assert growth["growth_kind"] == growth_kind
    assert growth["prefix"] == "worker"
    assert growth["baseline_count"] == baseline_count
    assert growth["current_count"] == baseline_count + 1


def test_pure_rename_and_reduction_do_not_report_tree_growth(tmp_path: Path) -> None:
    repo, baseline = _directory_repo(tmp_path, 25, prefix="worker")
    _git(
        repo,
        "mv",
        "app/domain/worker_00.py",
        "app/domain/worker_zero.py",
    )

    renamed = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )
    assert not any(
        item["rule"] in {"code-directory-width-growth", "same-prefix-sibling-growth"}
        for item in renamed
    )

    (repo / "app" / "domain" / "worker_01.py").unlink()
    reduced = gather_structure_findings(
        repo,
        {"config": {"source_commit": "HEAD"}, "change_rules": {}},
        comparison_commit=baseline,
    )
    assert not any(
        item["rule"] in {"code-directory-width-growth", "same-prefix-sibling-growth"}
        for item in reduced
    )


def test_copied_large_file_does_not_inherit_source_size_baseline(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = _write(repo / "app/original.py", _python_lines(1300))
    baseline = _commit(repo, "baseline large source")
    original.write_text(_python_lines(1299), encoding="utf-8")
    _write(repo / "app/copied.py", _python_lines(1300))
    _git(repo, "add", "-A")

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": baseline}, "change_rules": {}},
        comparison_commit=baseline,
    )

    copied = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
        and item["source"] == "app/copied.py"
    )
    assert copied["baseline_path"] is None
    assert copied["baseline_lines"] == 0
    assert copied["crossed_thresholds"] == [800, 1200]


def test_ci_passes_a_fetched_event_base_to_structure_check() -> None:
    workflow = (SKILL_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "fetch-depth: 0" in workflow
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.before" in workflow
    assert 'git cat-file -e "$comparison_commit^{commit}"' in workflow
    assert '--comparison-commit "$PCR_COMPARISON_COMMIT"' in workflow
