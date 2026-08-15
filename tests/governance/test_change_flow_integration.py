from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import router_core

from router_support.change_flow import SAFE_ENVELOPE_FIELDS, compact_flow_output, run_change_flow


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    source = repo / "app/service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def execute():\n    return 'ok'\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    router_core.bootstrap_bundle(repo, write=True)
    return repo


def test_change_flow_persists_full_artifact_and_warm_cache(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    runtime = tmp_path / "runtime"

    first = run_change_flow(
        repo_root=repo,
        request_text="Extend the existing service execution result.",
        changed_paths=["app/service.py"],
        runtime_dir=str(runtime),
        timeout_seconds=20,
    )
    second = run_change_flow(
        repo_root=repo,
        request_text="Extend the existing service execution result.",
        changed_paths=["app/service.py"],
        runtime_dir=str(runtime),
        timeout_seconds=20,
    )
    compact = compact_flow_output(second, fields=["action"])

    assert Path(first["artifact_path"]).is_file()
    assert len(first["artifact_digest"]) == 64
    assert hashlib.sha256(Path(first["artifact_path"]).read_bytes()).hexdigest() == first[
        "artifact_digest"
    ]
    assert router_core.validate_against_schema(
        first,
        Path(__file__).resolve().parents[2]
        / "schemas"
        / "change-flow-report.schema.json",
    ) == []
    assert set(SAFE_ENVELOPE_FIELDS) <= set(compact)
    assert second["cache_summary"]["hits"] == 6
    assert second["incremental_summary"]["reused_node_count"] > 0
    assert second["authorization_request"]["state"] == "requested"
