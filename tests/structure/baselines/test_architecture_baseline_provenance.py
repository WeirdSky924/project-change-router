from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.architecture_baseline import (
    filter_architecture_baseline_by_provenance,
    finding_fingerprint,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


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
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "provenance@example.invalid")
    _git(repo, "config", "user.name", "Architecture Provenance Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _write_bundle(
    repo: Path,
    modules: list[router_core.ModuleEntry],
    baseline: list[dict[str, object]],
) -> None:
    router_core.write_bundle(
        repo / "project-change-router",
        {
            "config": {"generated_at": "2026-07-23T00:00:00Z", "ignore_paths": []},
            "capability_catalog": {"capabilities": []},
            "module_map": {"modules": [module.to_dict() for module in modules]},
            "ownership": {"owners": []},
            "change_rules": {"architecture_baseline": baseline},
            "path_to_capability_map": {"path_index": []},
            "exception_registry": {"exceptions": []},
            "evaluation_set": {"cases": []},
        },
    )


def _run(script: str, repo: Path, comparison: str) -> tuple[int, dict[str, object]]:
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / script),
            "--repo",
            str(repo),
            "--comparison-commit",
            comparison,
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def _dependency_fixture(repo: Path) -> tuple[list[router_core.ModuleEntry], dict[str, object], Path]:
    _write(repo / "app/__init__.py", "")
    _write(repo / "app/api/__init__.py", "")
    _write(repo / "app/api/routes/__init__.py", "")
    _write(repo / "app/api/routes/plots.py", "VALUE = 1\n")
    source = _write(
        repo / "app/services/plots/postgres_service.py",
        "from app.api.routes import plots\n",
    )
    modules = [
        router_core.ModuleEntry("module-api", "app/api", "interface", "api", "API"),
        router_core.ModuleEntry("module-plots", "app/services/plots", "adapter", "plots", "Plots"),
    ]
    identity = {
        "rule": "dependency-direction",
        "source": "app/services/plots/postgres_service.py",
        "target": "app/api/routes/plots.py",
    }
    return modules, identity, source


def test_dependency_cli_trusts_only_comparison_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    modules, identity, source = _dependency_fixture(repo)
    baseline = [{
        "id": "DEP-001",
        **identity,
        "owner": "plots",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(identity),
    }]
    _write_bundle(repo, modules, baseline)
    comparison = _commit(repo, "historical dependency baseline")
    _write(repo / "README.md", "later feature\n")
    _commit(repo, "later feature")

    existing_code, existing = _run("check_deps.py", repo, comparison)
    _write(repo / "app/api/routes/workflows.py", "VALUE = 2\n")
    source.write_text("from app.api.routes import workflows\n", encoding="utf-8")
    changed_code, changed = _run("check_deps.py", repo, comparison)

    assert existing_code == 0 and existing["status"] == "warn"
    assert existing["findings"][0]["baseline_status"] == "existing_debt"
    assert changed_code == 1 and changed["status"] == "fail"
    assert changed["findings"][0]["baseline_status"] == "new"


def test_dependency_cli_blocks_feature_added_matching_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    modules, identity, _source = _dependency_fixture(repo)
    _write_bundle(repo, modules, [])
    comparison = _commit(repo, "comparison without debt waiver")
    baseline = [{
        "id": "DEP-NEW",
        **identity,
        "owner": "plots",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(identity),
    }]
    _write_bundle(repo, modules, baseline)
    _commit(repo, "launder current dependency finding")

    returncode, report = _run("check_deps.py", repo, comparison)

    assert returncode == 1 and report["status"] == "fail"
    assert any(
        item.get("diagnostic_code") == "architecture_baseline_added_since_comparison"
        for item in report["findings"]
    )
    dependency = next(item for item in report["findings"] if item["rule"] == "dependency-direction")
    assert dependency["baseline_status"] == "new" and dependency["blocking"] is True


def test_public_cli_trusts_only_comparison_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    public_api = _write(repo / "app/shared/__init__.py", '__all__ = ["Stable"]\n')
    module = router_core.ModuleEntry(
        "module-shared", "app/shared", "shared-capability", "shared", "Shared", public_api="__init__.py"
    )
    identity = {"rule": "public-export-count", "module": "app.shared", "count": 1}
    baseline = [{
        "id": "PUBLIC-001",
        **identity,
        "owner": "shared",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(identity),
    }]
    _write_bundle(repo, [module], baseline)
    comparison = _commit(repo, "historical public baseline")
    _write(repo / "README.md", "later feature\n")
    _commit(repo, "later feature")

    existing_code, existing = _run("check_public_api.py", repo, comparison)
    public_api.write_text('__all__ = ["Stable", "Growth"]\n', encoding="utf-8")
    changed_code, changed = _run("check_public_api.py", repo, comparison)

    assert existing_code == 0 and existing["status"] == "warn"
    assert existing["findings"][0]["baseline_status"] == "existing_debt"
    assert changed_code == 1 and changed["status"] == "fail"
    assert changed["findings"][0]["baseline_status"] == "new"


def test_public_cli_accepts_same_change_low_watermark_tightening(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    public_api = _write(
        repo / "app/shared/__init__.py",
        '__all__ = ["A", "B", "C", "D"]\n',
    )
    module = router_core.ModuleEntry(
        "module-shared", "app/shared", "shared-capability", "shared", "Shared", public_api="__init__.py"
    )
    old_identity = {"rule": "public-export-count", "module": "app.shared", "count": 4}
    old_baseline = [{
        "id": "PUBLIC-RATCHET",
        **old_identity,
        "owner": "shared",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(old_identity),
    }]
    _write_bundle(repo, [module], old_baseline)
    comparison = _commit(repo, "public export high watermark")

    new_identity = {**old_identity, "count": 2}
    new_baseline = [{
        **old_baseline[0],
        "count": 2,
        "fingerprint": finding_fingerprint(new_identity),
    }]
    public_api.write_text('__all__ = ["A", "B"]\n', encoding="utf-8")
    _write_bundle(repo, [module], new_baseline)
    _commit(repo, "reduce exports and baseline together")

    returncode, report = _run("check_public_api.py", repo, comparison)

    assert returncode == 0 and report["status"] == "warn"
    export = next(item for item in report["findings"] if item["rule"] == "public-export-count")
    assert export["baseline_status"] == "existing_debt"
    assert export["blocking"] is False
    assert not any(item["rule"] == "architecture-baseline-provenance" for item in report["findings"])


def test_comparison_profile_can_prove_historical_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    identity = {"rule": "public-export-count", "module": "app.shared", "count": 1}
    baseline = {
        "id": "PUBLIC-PROFILE",
        **identity,
        "owner": "shared",
        "exit_stage": "G4",
        "fingerprint": finding_fingerprint(identity),
    }
    _write(
        repo / ".project-change-router.yaml",
        yaml.safe_dump(
            {"guardrails": {"architecture_baseline": [baseline]}},
            sort_keys=False,
        ),
    )
    comparison = _commit(repo, "profile baseline")
    _write(repo / "README.md", "later\n")
    _commit(repo, "later feature")

    trusted, diagnostics = filter_architecture_baseline_by_provenance(
        repo,
        [baseline],
        comparison,
    )

    assert trusted == [baseline]
    assert diagnostics == []

    for changed in (
        {**baseline, "owner": "different-owner"},
        {
            **baseline,
            "count": 2,
            "fingerprint": finding_fingerprint({**identity, "count": 2}),
        },
    ):
        rejected, findings = filter_architecture_baseline_by_provenance(
            repo,
            [changed],
            comparison,
        )
        assert rejected == []
        assert findings[0]["diagnostic_code"] == "architecture_baseline_changed_since_comparison"

    rejected, findings = filter_architecture_baseline_by_provenance(
        repo,
        [baseline],
        None,
    )
    assert rejected == []
    assert findings[0]["diagnostic_code"] == "architecture_baseline_provenance_incomplete"
