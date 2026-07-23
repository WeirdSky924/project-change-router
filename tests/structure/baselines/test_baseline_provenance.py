from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.structure_guardrails import gather_structure_findings


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
    _git(repo, "config", "user.name", "Baseline Provenance Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _central_rule(source_commit: str, source: str) -> dict[str, object]:
    line_count = len(source.splitlines())
    method_count = source.count("    def ")
    return {
        "id": "DATA-001-gateway",
        "kind": "python-class-remove-only",
        "path": "app/database/postgres.py",
        "symbol": "Gateway",
        "source_commit": source_commit,
        "owner": "database-runtime",
        "exit_stage": "G2",
        "max_file_lines": line_count,
        "max_methods": method_count,
        "max_public_methods": method_count,
    }


def _function_rule(
    baseline_id: str,
    source_commit: str,
    source: str,
) -> dict[str, object]:
    line_count = len(source.splitlines())
    return {
        "id": baseline_id,
        "kind": "python-function-remove-only",
        "path": "app/api/app.py",
        "symbol": "create_app",
        "source_commit": source_commit,
        "owner": "api-composition",
        "exit_stage": "G2",
        "max_file_lines": line_count,
        "max_symbol_lines": line_count,
        "max_nested_functions": 0,
        "max_decorated_handlers": 0,
    }


def _bundle(*, central: list[dict[str, object]] = (), forbidden: list[dict[str, object]] = ()) -> dict[str, object]:
    return {
        "config": {"source_commit": None},
        "change_rules": {
            "central_growth_baseline": list(central),
            "forbidden_implementation_roots": list(forbidden),
        },
    }


def test_central_baseline_cannot_use_feature_head_as_source_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    base_source = "class Gateway:\n    def execute(self):\n        return None\n"
    current_source = (
        base_source
        + "\n    def save_domain_record(self):\n        return None\n"
    )
    _write(repo / "app/database/postgres.py", base_source)
    base = _commit(repo, "baseline gateway")
    _write(repo / "app/database/postgres.py", current_source)
    feature = _commit(repo, "grow gateway")

    findings = gather_structure_findings(
        repo,
        _bundle(central=[_central_rule(feature, current_source)]),
        comparison_commit=base,
    )

    diagnostic = next(
        item
        for item in findings
        if item.get("diagnostic_code") == "baseline_source_commit_untrusted"
    )
    assert diagnostic["severity"] == "P0"
    assert diagnostic["blocking"] is True
    assert diagnostic["source_commit"] == feature
    assert diagnostic["comparison_commit"] == base


def test_forbidden_root_cannot_use_feature_head_as_source_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "README.md", "baseline\n")
    base = _commit(repo, "baseline repository")
    _write(repo / "legacy/providers/new_runtime.py", "class Runtime:\n    pass\n")
    feature = _commit(repo, "add forbidden runtime")
    rule = {
        "id": "EXEC-001-legacy-root",
        "path": "legacy/providers",
        "source_commit": feature,
        "owner": "provider-runtime",
        "exit_stage": "G2",
    }

    findings = gather_structure_findings(
        repo,
        _bundle(forbidden=[rule]),
        comparison_commit=base,
    )

    diagnostic = next(
        item
        for item in findings
        if item.get("diagnostic_code") == "baseline_source_commit_untrusted"
    )
    assert diagnostic["severity"] == "P0"
    assert diagnostic["blocking"] is True


def test_historical_central_baseline_remains_trusted_after_later_change(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = "class Gateway:\n    def execute(self):\n        return None\n"
    _write(repo / "app/database/postgres.py", source)
    base = _commit(repo, "baseline gateway")
    _write(repo / "README.md", "later feature\n")
    _commit(repo, "later feature")

    findings = gather_structure_findings(
        repo,
        _bundle(central=[_central_rule(base, source)]),
        comparison_commit=base,
    )

    assert not any(item["rule"] == "structure-baseline-diagnostic" for item in findings)


def test_central_baseline_cannot_raise_a_comparison_low_watermark(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    one_method = "class Gateway:\n    def execute(self):\n        return None\n"
    two_methods = (
        one_method
        + "\n    def save_domain_record(self):\n        return None\n"
    )
    path = _write(repo / "app/database/postgres.py", two_methods)
    original = _commit(repo, "original gateway debt")

    path.write_text(one_method, encoding="utf-8")
    comparison_rule = _central_rule(original, one_method)
    _write(
        repo / "project-change-router/references/change-rules.yaml",
        yaml.safe_dump(
            {"central_growth_baseline": [comparison_rule]},
            sort_keys=False,
        ),
    )
    comparison = _commit(repo, "lower central baseline")

    path.write_text(two_methods, encoding="utf-8")
    weakened_rule = _central_rule(original, two_methods)
    _commit(repo, "restore debt and raise baseline")

    findings = gather_structure_findings(
        repo,
        _bundle(central=[weakened_rule]),
        comparison_commit=comparison,
    )

    diagnostic = next(
        item
        for item in findings
        if item.get("diagnostic_code") == "central_baseline_weakening"
    )
    assert diagnostic["blocking"] is True
    assert diagnostic["weakened_fields"]["max_methods"] == {
        "comparison": 1,
        "current": 2,
    }


def test_central_baseline_id_churn_cannot_restore_function_low_watermark(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    original = (
        "def create_app():\n"
        "    app = object()\n"
        "    app.ready = True\n"
        "    return app\n"
    )
    reduced = "def create_app():\n    return object()\n"
    restored = (
        "def create_app():\n"
        "    app = object()\n"
        "    return app\n"
    )
    path = _write(repo / "app/api/app.py", original)
    source_commit = _commit(repo, "original composition root")

    path.write_text(reduced, encoding="utf-8")
    comparison_rule = _function_rule(
        "API-CENTRAL-OLD",
        source_commit,
        reduced,
    )
    _write(
        repo / "project-change-router/references/change-rules.yaml",
        yaml.safe_dump(
            {"central_growth_baseline": [comparison_rule]},
            sort_keys=False,
        ),
    )
    comparison = _commit(repo, "lower composition root baseline")

    path.write_text(restored, encoding="utf-8")
    current_rule = _function_rule(
        "API-CENTRAL-NEW",
        source_commit,
        original,
    )
    _commit(repo, "restore composition lines under renamed baseline")

    findings = gather_structure_findings(
        repo,
        _bundle(central=[current_rule]),
        comparison_commit=comparison,
    )

    diagnostic = next(
        item
        for item in findings
        if item.get("diagnostic_code") == "central_baseline_weakening"
    )
    assert diagnostic["baseline_id"] == "API-CENTRAL-NEW"
    assert diagnostic["weakened_fields"]["max_file_lines"] == {
        "comparison": 2,
        "current": 4,
    }
    assert diagnostic["weakened_fields"]["max_symbol_lines"] == {
        "comparison": 2,
        "current": 4,
    }


def test_comparison_central_baseline_duplicate_target_is_fail_closed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    source = "class Gateway:\n    def execute(self):\n        return None\n"
    _write(repo / "app/database/postgres.py", source)
    source_commit = _commit(repo, "baseline gateway")
    first = _central_rule(source_commit, source)
    second = {**first, "id": "DATA-001-gateway-duplicate"}
    _write(
        repo / "project-change-router/references/change-rules.yaml",
        yaml.safe_dump(
            {"central_growth_baseline": [first, second]},
            sort_keys=False,
        ),
    )
    comparison = _commit(repo, "conflicting central target records")

    findings = gather_structure_findings(
        repo,
        _bundle(central=[first]),
        comparison_commit=comparison,
    )

    diagnostic = next(
        item
        for item in findings
        if item.get("diagnostic_code")
        == "central_baseline_comparison_target_conflict"
    )
    assert diagnostic["blocking"] is True
    assert diagnostic["comparison_baseline_ids"] == [
        "DATA-001-gateway",
        "DATA-001-gateway-duplicate",
    ]


def test_comparison_membership_blocks_old_debt_replacement_at_same_count(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    execute = "class Gateway:\n    def execute(self):\n        return None\n"
    save = "class Gateway:\n    def save_domain_record(self):\n        return None\n"
    original_source = execute + "\n    def save_domain_record(self):\n        return None\n"
    path = _write(repo / "app/database/postgres.py", original_source)
    original = _commit(repo, "original two-method gateway")

    path.write_text(execute, encoding="utf-8")
    rule = _central_rule(original, execute)
    _write(
        repo / "project-change-router/references/change-rules.yaml",
        yaml.safe_dump({"central_growth_baseline": [rule]}, sort_keys=False),
    )
    comparison = _commit(repo, "remove legacy save method")

    path.write_text(save, encoding="utf-8")
    _commit(repo, "replace retained method with old debt")
    findings = gather_structure_findings(
        repo,
        _bundle(central=[rule]),
        comparison_commit=comparison,
    )

    growth = next(
        item for item in findings if item["rule"] == "central-class-member-growth"
    )
    assert growth["new_members"] == ["save_domain_record"]
