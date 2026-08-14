from __future__ import annotations

import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_reuse import build_input_fingerprint  # noqa: E402
from reuse_runtime import runtime_root_for_repo  # noqa: E402
from router_support.evaluation_policy import evaluation_input_digest  # noqa: E402
from router_support.structure_guardrails import refresh_profile_structure_guardrails  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "PCR Test")
    _git(repo, "config", "user.email", "pcr@example.invalid")
    source = repo / "service.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "service.py")
    _git(repo, "commit", "-m", "baseline")
    return repo


def _bundle() -> dict[str, object]:
    return {
        "config": {"repo_id": "fixture", "ignore_patterns": []},
        "module_map": {"source_commit": "abc", "modules": []},
        "capability_catalog": {"source_commit": "abc", "capabilities": []},
        "path_to_capability_map": {"source_commit": "abc", "path_index": []},
        "change_rules": {},
        "evaluation_set": {"cases": []},
    }


def test_canonical_input_fingerprint_ignores_mtime_but_tracks_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = repo / "service.py"
    before = build_input_fingerprint(repo, _bundle(), ["service.py"], {})

    stat = source.stat()
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    after_touch = build_input_fingerprint(repo, _bundle(), ["service.py"], {})
    assert after_touch == before

    source.write_text("VALUE = 2\n", encoding="utf-8")
    after_content = build_input_fingerprint(repo, _bundle(), ["service.py"], {})
    assert after_content != before


def test_changed_path_input_fingerprint_ignores_unrelated_worktree_changes(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    before = build_input_fingerprint(repo, _bundle(), ["service.py"], {})

    (repo / "unrelated.txt").write_text("outside scan scope\n", encoding="utf-8")

    assert build_input_fingerprint(
        repo, _bundle(), ["service.py"], {}
    ) == before


def test_changed_path_input_fingerprint_tracks_actual_scan_sources(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    before = build_input_fingerprint(
        repo, _bundle(), ["service.py"], {}, "a" * 64
    )

    after = build_input_fingerprint(
        repo, _bundle(), ["service.py"], {}, "b" * 64
    )

    assert after != before


def test_canonical_input_fingerprint_tracks_delete_rename_and_bundle_truth(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    bundle = _bundle()
    before = build_input_fingerprint(repo, bundle, ["service.py"], {})

    changed_bundle = deepcopy(bundle)
    changed_bundle["capability_catalog"]["capabilities"] = [{"id": "new-owner"}]
    assert build_input_fingerprint(repo, changed_bundle, ["service.py"], {}) != before

    _git(repo, "mv", "service.py", "renamed.py")
    after_rename = build_input_fingerprint(repo, bundle, ["service.py", "renamed.py"], {})
    assert after_rename != before

    (repo / "renamed.py").unlink()
    after_delete = build_input_fingerprint(repo, bundle, ["renamed.py"], {})
    assert after_delete != after_rename


def test_full_scan_input_fingerprint_tracks_clean_head_content_change(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    bundle = _bundle()
    before = build_input_fingerprint(repo, bundle, [], {})

    (repo / "service.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "add", "service.py")
    _git(repo, "commit", "-m", "change service")
    after = build_input_fingerprint(repo, bundle, [], {})

    assert after != before


@pytest.mark.parametrize("configured", [".pcr-runtime", "runtime/cache"])
def test_runtime_root_rejects_repository_internal_relative_paths(tmp_path: Path, configured: str) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="outside the target repository"):
        runtime_root_for_repo(repo, _bundle(), configured)


def test_runtime_root_rejects_repository_internal_absolute_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    with pytest.raises(ValueError, match="outside the target repository"):
        runtime_root_for_repo(repo, _bundle(), str(repo / ".runtime"))


def test_evaluation_digest_ignores_operational_reuse_settings() -> None:
    baseline = _bundle()
    baseline["change_rules"] = {
        "dependency_priority": ["core"],
        "reuse_scan_scope": {"include_dependency_neighbors": True},
        "reuse_scan_budget": {"max_comparisons": 100},
        "reuse_scan_runtime": {"soft_timeout_seconds": 60},
        "reuse_scan_retention": {"canonical_max_count": 500},
    }
    operational = deepcopy(baseline)
    operational["change_rules"]["reuse_scan_budget"]["max_comparisons"] = 200
    operational["change_rules"]["reuse_scan_runtime"]["soft_timeout_seconds"] = 5
    operational["change_rules"]["reuse_scan_retention"]["canonical_max_count"] = 10
    assert evaluation_input_digest(operational) == evaluation_input_digest(baseline)

    semantic = deepcopy(baseline)
    semantic["change_rules"]["reuse_scan_scope"]["include_dependency_neighbors"] = False
    assert evaluation_input_digest(semantic) != evaluation_input_digest(baseline)


def test_profile_refresh_replaces_all_reuse_configuration_sections() -> None:
    existing = {
        "reuse_scan_scope": {"include_dependency_neighbors": False},
        "reuse_scan_budget": {"max_comparisons": 1},
        "reuse_scan_runtime": {"soft_timeout_seconds": 1},
        "reuse_scan_retention": {"canonical_max_count": 1},
    }
    generated = {
        "reuse_scan_scope": {"include_dependency_neighbors": True},
        "reuse_scan_budget": {"max_comparisons": 100},
        "reuse_scan_runtime": {"soft_timeout_seconds": 60},
        "reuse_scan_retention": {"canonical_max_count": 500},
    }
    refreshed = refresh_profile_structure_guardrails(existing, generated)
    for key, value in generated.items():
        assert refreshed[key] == value
