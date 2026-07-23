from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.structure_guardrails import (
    find_python_class_forbidden_source_terms,
    gather_structure_findings,
    measure_python_class,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _python_lines(count: int) -> str:
    return "VALUE = 1\n" + "# baseline\n" * (count - 1)


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


BASELINE_SOURCE = """\
class Gateway:
    def execute(self):
        return None

    async def fetch_one(self):
        return None

    def save_quality_rule(self):
        return None

    def _quality_params(self):
        return None
"""


def _bundle() -> dict:
    return {
        "change_rules": {
            "central_growth_baseline": [
                {
                    "id": "DATA-001-gateway",
                    "kind": "python-class-remove-only",
                    "path": "app/database/postgres.py",
                    "symbol": "Gateway",
                    "source_commit": "baseline-commit",
                    "owner": "database-gateway-runtime",
                    "exit_stage": "G2",
                    "max_file_lines": 12,
                    "max_methods": 4,
                    "max_public_methods": 3,
                    "tracked_members": ["save_quality_rule", "_quality_params"],
                    "max_tracked_members_present": 2,
                }
            ],
            "forbidden_implementation_roots": [
                {
                    "id": "DATA-001-second-repository-root",
                    "path": "app/repositories",
                    "owner": "quality-engine",
                    "exit_stage": "permanent",
                }
            ],
        }
    }


def test_measure_python_class_counts_direct_methods() -> None:
    measurement = measure_python_class(BASELINE_SOURCE, "Gateway")

    assert measurement["method_names"] == {
        "execute",
        "fetch_one",
        "save_quality_rule",
        "_quality_params",
    }
    assert measurement["method_count"] == 4
    assert measurement["public_method_count"] == 3


@pytest.mark.parametrize(
    ("baseline_lines", "current_lines", "threshold"),
    [(799, 800, 800), (1171, 1201, 1200)],
)
def test_changed_code_file_threshold_crossing_is_blocking(
    tmp_path: Path,
    baseline_lines: int,
    current_lines: int,
    threshold: int,
) -> None:
    repo = tmp_path / "repo"
    path = "app/services/workflow/postgres_service.py"
    _write(repo / path, _python_lines(current_lines))
    bundle = {
        "config": {"source_commit": "baseline-commit"},
        "change_rules": {},
    }

    findings = gather_structure_findings(
        repo,
        bundle,
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(
            baseline_lines
        ),
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["blocking"] is True
    assert crossing["source"] == path
    assert crossing["baseline_lines"] == baseline_lines
    assert crossing["current_lines"] == current_lines
    assert crossing["crossed_thresholds"] == [threshold]


def test_existing_size_debt_without_a_new_threshold_crossing_is_not_reported(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    path = "app/services/workflow/postgres_service.py"
    _write(repo / path, _python_lines(1201))
    bundle = {
        "config": {"source_commit": "baseline-commit"},
        "change_rules": {},
    }

    findings = gather_structure_findings(
        repo,
        bundle,
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(1200),
    )

    assert not any(
        item["rule"] == "code-file-size-threshold-crossing"
        for item in findings
    )


@pytest.mark.parametrize(
    "path",
    [
        "frontend/vite.config.cjs",
        "migrations/V99_structure_guard.sql",
        "frontend/index.html",
        "project-change-router/router-config.yaml",
        ".github/workflows/ci.yml",
        "audit/audit.config.toml",
        "project-change-router/schemas/route.schema.json",
        "prompts/instruction/function_example.md",
        "skills/core/skill_example.md",
        ".env.example",
        "requirements-dev.txt", "uv.lock",
    ],
)
def test_governed_code_bearing_path_threshold_crossing_is_blocking(
    tmp_path: Path,
    path: str,
) -> None:
    repo = tmp_path / "repo"
    _write(repo / path, _python_lines(800))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "baseline-commit"}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(799),
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["source"] == path
    assert crossing["crossed_thresholds"] == [800]


@pytest.mark.parametrize(
    "path",
    [
        "docs/design.md",
        "project-change-router/reports/route-example.json",
        "audit/reports/daily/example.json",
        "audit/state/master_audit_state.json",
        ".refactor_progress.json",
        "assets/example.svg", "runtime/process.lock",
    ],
)
def test_non_code_report_state_document_and_media_paths_are_excluded(
    tmp_path: Path,
    path: str,
) -> None:
    repo = tmp_path / "repo"
    _write(repo / path, _python_lines(1201))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "baseline-commit"}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: "",
    )

    assert not any(
        item["rule"] == "code-file-size-threshold-crossing"
        for item in findings
    )


def test_executable_without_suffix_is_governed(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    path = "scripts/rebuild-check"
    executable = _write(repo / path, _python_lines(800))
    executable.chmod(0o755)

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": "baseline-commit"}, "change_rules": {}},
        changed_path_loader=lambda _repo: (path,),
        file_baseline_loader=lambda _repo, _commit, _path: _python_lines(799),
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["source"] == path


def test_new_untracked_sql_crosses_both_thresholds(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / "README.md", "baseline\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    source_commit = _git(repo, "rev-parse", "HEAD")
    path = "migrations/V99_structure_guard.sql"
    _write(repo / path, _python_lines(1201))

    findings = gather_structure_findings(
        repo,
        {"config": {"source_commit": source_commit}, "change_rules": {}},
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["baseline_path"] is None
    assert crossing["crossed_thresholds"] == [800, 1200]


def test_clean_committed_threshold_crossing_is_blocking(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = "app/services/workflow/postgres_service.py"

    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / path, _python_lines(1171))
    _git(repo, "add", path)
    _git(repo, "commit", "-m", "baseline")
    source_commit = _git(repo, "rev-parse", "HEAD")

    _write(repo / path, _python_lines(1201))
    _git(repo, "add", path)
    _git(repo, "commit", "-m", "cross threshold")
    assert _git(repo, "status", "--porcelain") == ""

    findings = gather_structure_findings(
        repo,
        {
            "config": {"source_commit": source_commit},
            "change_rules": {},
        },
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["source"] == path
    assert crossing["baseline_lines"] == 1171
    assert crossing["current_lines"] == 1201
    assert crossing["crossed_thresholds"] == [1200]


def test_clean_rename_growth_uses_the_original_baseline_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = "app/services/workflow/postgres_service.py"
    new_path = "app/services/workflow/persistence_service.py"
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / old_path, _python_lines(799))
    _git(repo, "add", old_path)
    _git(repo, "commit", "-m", "baseline")
    source_commit = _git(repo, "rev-parse", "HEAD")

    _git(repo, "mv", old_path, new_path)
    _write(repo / new_path, _python_lines(800))
    _git(repo, "add", new_path)
    _git(repo, "commit", "-m", "rename and cross threshold")

    findings = gather_structure_findings(
        repo,
        {
            "config": {"source_commit": source_commit},
            "change_rules": {},
        },
    )

    crossing = next(
        item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    )
    assert crossing["source"] == new_path
    assert crossing["baseline_path"] == old_path
    assert crossing["baseline_lines"] == 799
    assert crossing["current_lines"] == 800


def test_missing_committed_baseline_is_a_blocking_diagnostic(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / "app/service.py", _python_lines(10))
    _git(repo, "add", "app/service.py")
    _git(repo, "commit", "-m", "current")

    findings = gather_structure_findings(
        repo,
        {
            "config": {"source_commit": "missing-baseline-commit"},
            "change_rules": {},
        },
    )

    diagnostic = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["blocking"] is True
    assert diagnostic["source"] == "<git-changes>"


def test_added_untracked_and_deleted_files_keep_source_aware_baselines(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    deleted_path = "app/deleted.py"
    added_path = "app/added.py"
    untracked_path = "app/untracked.py"
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / deleted_path, "BASELINE = 1\n" + "# old\n" * 1200)
    _git(repo, "add", deleted_path)
    _git(repo, "commit", "-m", "baseline")
    source_commit = _git(repo, "rev-parse", "HEAD")

    (repo / deleted_path).unlink()
    _write(repo / added_path, "ADDED = 1\n" + "# new\n" * 799)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "delete and add")
    _write(repo / untracked_path, "UNTRACKED = 1\n" + "# fresh\n" * 799)

    findings = gather_structure_findings(
        repo,
        {
            "config": {"source_commit": source_commit},
            "change_rules": {},
        },
    )

    crossings = {
        item["source"]: item
        for item in findings
        if item["rule"] == "code-file-size-threshold-crossing"
    }
    assert set(crossings) == {added_path, untracked_path}
    assert crossings[added_path]["baseline_path"] is None
    assert crossings[untracked_path]["baseline_path"] is None
    assert deleted_path not in crossings


def test_clean_pure_rename_does_not_create_size_growth(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    old_path = "app/old_service.py"
    new_path = "app/new_service.py"
    _git(repo, "init")
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")
    _write(repo / old_path, _python_lines(1201))
    _git(repo, "add", old_path)
    _git(repo, "commit", "-m", "baseline")
    source_commit = _git(repo, "rev-parse", "HEAD")

    _git(repo, "mv", old_path, new_path)
    _git(repo, "commit", "-m", "rename")
    findings = gather_structure_findings(
        repo,
        {
            "config": {"source_commit": source_commit},
            "change_rules": {},
        },
    )

    assert not any(
        item["rule"] == "code-file-size-threshold-crossing"
        for item in findings
    )


def test_remove_only_baseline_allows_method_removal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "app/database/postgres.py",
        "class Gateway:\n"
        "    def execute(self):\n"
        "        return None\n\n"
        "    async def fetch_one(self):\n"
        "        return None\n",
    )

    findings = gather_structure_findings(
        repo,
        _bundle(),
        comparison_commit="baseline-commit",
        changed_path_loader=lambda _repo: (),
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    assert findings == []


def test_remove_only_baseline_blocks_new_member_even_when_counts_do_not_grow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "app/database/postgres.py",
        "class Gateway:\n"
        "    def execute(self):\n"
        "        return None\n\n"
        "    def new_domain_write(self):\n"
        "        return None\n",
    )

    findings = gather_structure_findings(
        repo,
        _bundle(),
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    growth = next(item for item in findings if item["rule"] == "central-class-member-growth")
    assert growth["blocking"] is True
    assert growth["new_members"] == ["new_domain_write"]


def test_remove_only_baseline_blocks_forbidden_domain_source_in_existing_member(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "app/database/postgres.py",
        "class Gateway:\n"
        "    def execute(self):\n"
        "        table = 'foreshadow' + 'ings'\n"
        "        codec_field = 'hook_' + 'type'\n"
        "        return f'SELECT {codec_field} FROM {table}'\n",
    )
    bundle = _bundle()
    bundle["change_rules"]["central_growth_baseline"][0][
        "forbidden_source_terms"
    ] = ["foreshadowings", "hook_type", "_foreshadowing_params"]

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    residual = next(
        item for item in findings if item["rule"] == "central-forbidden-source-term"
    )
    assert residual["blocking"] is True
    assert residual["matched_terms"] == ["foreshadowings", "hook_type"]


def test_forbidden_source_terms_do_not_join_unrelated_python_tokens() -> None:
    source = """\
class Gateway:
    def execute(self, data):
        prompt_template = data.get("prompt_template")
        self._save(prompt_template)
"""

    assert find_python_class_forbidden_source_terms(
        source,
        "Gateway",
        ["prompt_templates"],
    ) == []


def test_exclusive_source_owner_blocks_static_sql_outside_canonical_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = (
        "app/services/agent_runtime/skill_catalog_persistence/postgres_adapter.py"
    )
    _write(repo / "app/database/postgres.py", BASELINE_SOURCE)
    _write(
        repo / canonical_path,
        'SKILL_SQL = "INSERT INTO skills (id) VALUES (:id)"\n',
    )
    _write(
        repo / "app/services/rogue_skill_store.py",
        'SKILL_SQL = "SELECT * FROM skills ORDER BY id"\n'
        'ASSIGNMENT_SQL = "DELETE FROM skill_assignments WHERE skill_id = :id"\n',
    )
    bundle = _bundle()
    bundle["change_rules"]["exclusive_source_owners"] = [
        {
            "id": "DATA-001-skill-catalog-sql-owner",
            "root": "app",
            "path_pattern": "app/**/*.py",
            "owner": "shared-agent-runtime",
            "allowed_paths": [canonical_path],
            "forbidden_source_patterns": [
                r"\b(?:select\b.*?\bfrom|insert\s+into|update|delete\s+from)\s+skills\b",
                r"\b(?:select\b.*?\bfrom|insert\s+into|update|delete\s+from)\s+skill_assignments\b",
            ],
        }
    ]

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    duplicate = next(
        item for item in findings if item["rule"] == "exclusive-source-owner"
    )
    assert duplicate["blocking"] is True
    assert duplicate["source"] == "app/services/rogue_skill_store.py"
    assert len(duplicate["matched_patterns"]) == 2
    assert duplicate["allowed_paths"] == [canonical_path]
    assert not any(item["source"] == canonical_path for item in findings)


def test_exclusive_source_owner_blocks_concatenated_and_fstring_sql(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = (
        "app/services/agent_runtime/skill_catalog_persistence/postgres_adapter.py"
    )
    _write(repo / "app/database/postgres.py", BASELINE_SOURCE)
    _write(repo / canonical_path, 'SQL = "SELECT * FROM skills"\n')
    _write(
        repo / "app/services/rogue_skill_store.py",
        'SKILL_SQL = "SELECT * FROM " + "skills"\n'
        'ASSIGNMENT_SQL = f"DELETE FROM skill_assignments WHERE skill_id = {skill_id}"\n',
    )
    bundle = _bundle()
    bundle["change_rules"]["exclusive_source_owners"] = [
        {
            "id": "DATA-001-skill-catalog-sql-owner",
            "root": "app",
            "path_pattern": "app/**/*.py",
            "owner": "shared-agent-runtime",
            "allowed_paths": [canonical_path],
            "forbidden_source_patterns": [
                r"\bselect\b.*?\bfrom\s+skills\b",
                r"\bdelete\s+from\s+skill_assignments\b",
            ],
        }
    ]

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    duplicate = next(
        item for item in findings if item["rule"] == "exclusive-source-owner"
    )
    assert duplicate["source"] == "app/services/rogue_skill_store.py"
    assert len(duplicate["matched_patterns"]) == 2


def test_exclusive_source_owner_diagnostic_keeps_the_current_scan_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = (
        "app/services/agent_runtime/skill_catalog_persistence/postgres_adapter.py"
    )
    first_path = _write(repo / "app/a_valid.py", "VALUE = 'safe'\n")
    failing_path = _write(repo / "app/z_invalid.py", "VALUE = 'safe'\n")
    _write(repo / canonical_path, 'SQL = "SELECT * FROM skills"\n')
    bundle = _bundle()
    bundle["change_rules"]["exclusive_source_owners"] = [
        {
            "id": "DATA-001-skill-catalog-sql-owner",
            "root": "app",
            "path_pattern": "app/**/*.py",
            "owner": "shared-agent-runtime",
            "allowed_paths": [canonical_path],
            "forbidden_source_patterns": [r"\bselect\b.*?\bfrom\s+skills\b"],
        }
    ]
    original_relative_to = Path.relative_to

    def fail_one_root_check(path: Path, *other: object, **kwargs: object) -> Path:
        if path == failing_path and other == (repo / "app",):
            raise ValueError("injected root check failure")
        return original_relative_to(path, *other, **kwargs)

    monkeypatch.setattr(Path, "relative_to", fail_one_root_check)

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    diagnostic = next(
        item
        for item in findings
        if item["message"] == "Exclusive source owner scan failed."
    )
    assert diagnostic["source"] == failing_path.relative_to(repo).as_posix()
    assert diagnostic["source"] != first_path.relative_to(repo).as_posix()


def test_tracked_central_debt_can_be_driven_to_zero(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app/database/postgres.py", BASELINE_SOURCE)
    bundle = _bundle()
    bundle["change_rules"]["central_growth_baseline"][0]["max_tracked_members_present"] = 0

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    debt = next(item for item in findings if item["rule"] == "central-tracked-member-debt")
    assert debt["present_members"] == ["_quality_params", "save_quality_rule"]


def test_tracked_central_debt_blocks_same_count_member_reintroduction(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "app/database/postgres.py",
        "class Gateway:\n"
        "    def execute(self):\n"
        "        return None\n\n"
        "    async def fetch_one(self):\n"
        "        return None\n\n"
        "    def _quality_params(self):\n"
        "        return None\n",
    )
    baseline = _bundle()["change_rules"]["central_growth_baseline"][0]
    baseline["max_tracked_members_present"] = 1
    baseline["allowed_tracked_members_present"] = ["save_quality_rule"]
    bundle = {"change_rules": {"central_growth_baseline": [baseline]}}

    findings = gather_structure_findings(
        repo,
        bundle,
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )

    reintroduction = next(
        item
        for item in findings
        if item["rule"] == "central-tracked-member-reintroduction"
    )
    assert reintroduction["unexpected_present_members"] == ["_quality_params"]
    assert reintroduction["allowed_present_members"] == ["save_quality_rule"]


def test_profile_structure_guardrails_flow_into_change_rules() -> None:
    profile = {
        "guardrails": {
            "central_growth_baseline": [{"id": "gateway"}],
            "forbidden_implementation_roots": [{"id": "second-root"}],
            "exclusive_source_owners": [{"id": "skill-sql"}],
        }
    }

    rules = router_core.build_change_rules([], profile, "structured")

    assert rules["central_growth_baseline"] == [{"id": "gateway"}]
    assert rules["forbidden_implementation_roots"] == [{"id": "second-root"}]
    assert rules["exclusive_source_owners"] == [{"id": "skill-sql"}]
    assert "check-structure" in router_core.required_checks_for(None, "extend", {"change_rules": rules})


def test_rebuild_refreshes_stale_structure_rule_collections_from_profile() -> None:
    from router_support.structure_guardrails import refresh_profile_structure_guardrails

    existing = {
        "dependency_rules": [{"id": "preserved"}],
        "dependency_priority": {"quality-engine": 3},
        "central_growth_baseline": [{"id": "gateway", "max_methods": 373}],
        "forbidden_implementation_roots": [{"id": "old-root"}],
    }
    generated = {
        "dependency_priority": {
            "quality-engine": 3,
            "villain-conflict": 4,
        },
        "central_growth_baseline": [{"id": "gateway", "max_methods": 362}],
        "forbidden_implementation_roots": [{"id": "quality-second-root"}],
    }

    refreshed = refresh_profile_structure_guardrails(existing, generated)

    assert refreshed["dependency_rules"] == [{"id": "preserved"}]
    assert refreshed["dependency_priority"] == {
        "quality-engine": 3,
        "villain-conflict": 4,
    }
    assert refreshed["central_growth_baseline"] == [
        {"id": "gateway", "max_methods": 362}
    ]
    assert refreshed["forbidden_implementation_roots"] == [
        {"id": "quality-second-root"}
    ]


def test_router_bundle_build_uses_profile_structure_guardrail_refresh() -> None:
    source = inspect.getsource(router_core.build_router_bundle)

    assert "refresh_profile_structure_guardrails(" in source
