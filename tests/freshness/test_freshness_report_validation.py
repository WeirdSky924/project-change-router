from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cli_reports_invalid_latest_json_without_traceback(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app/a.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        "capabilities: []\n",
        encoding="utf-8",
    )
    bundle_root = repo / "project-change-router"
    bundle_root.mkdir()
    (bundle_root / "router-config.yaml").write_text(
        "ignore_paths: []\n",
        encoding="utf-8",
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    _git(repo, "config", "user.name", "PCR Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture")
    latest = bundle_root / "reports/index-rebuild/latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text("{invalid-json\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "check_index_freshness.py"),
            "--repo",
            str(repo),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert "indexed_snapshot_diagnostics" in report["failure_reasons"]
    indexed_diagnostics = next(
        check
        for check in report["checks"]
        if check["name"] == "indexed_snapshot_diagnostics"
    )["details"]["diagnostics"]
    assert any(
        item.startswith("latest-report-error:")
        for item in indexed_diagnostics
    )
    assert "Traceback" not in result.stderr
