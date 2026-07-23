from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("script", ["check_deps.py", "check_public_api.py"])
def test_invalid_comparison_commit_is_blocking_without_baseline(
    tmp_path: Path,
    script: str,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.test")
    _git(repo, "config", "user.name", "PCR Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")

    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / script),
            "--repo",
            str(repo),
            "--comparison-commit",
            "definitely-not-a-commit",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(result.stdout)
    provenance = [
        finding
        for finding in report["findings"]
        if finding.get("rule") == "architecture-baseline-provenance"
    ]
    assert result.returncode != 0
    assert report["status"] == "fail"
    assert report["blocking"] is True
    assert provenance[0]["diagnostic_code"] == (
        "architecture_baseline_provenance_incomplete"
    )
    assert provenance[0]["evidence_complete"] is False
