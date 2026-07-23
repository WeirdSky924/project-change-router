from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.central_baseline import measure_python_function
from router_support.structure_guardrails import gather_structure_findings


BASE_SOURCE = """\
def create_app():
    app = build_app()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
"""


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
    _git(repo, "config", "user.email", "function-baseline@example.invalid")
    _git(repo, "config", "user.name", "Function Baseline Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _rule(source_commit: str) -> dict[str, object]:
    measurement = measure_python_function(BASE_SOURCE, "create_app")
    return {
        "id": "API-001-create-app",
        "kind": "python-function-remove-only",
        "path": "app/api/app.py",
        "symbol": "create_app",
        "source_commit": source_commit,
        "owner": "api-composition",
        "exit_stage": "G2",
        "max_file_lines": len(BASE_SOURCE.splitlines()),
        "max_symbol_lines": measurement["symbol_line_count"],
        "max_nested_functions": measurement["nested_function_count"],
        "max_decorated_handlers": measurement["decorated_handler_count"],
        "tracked_members": ["health"],
        "max_tracked_members_present": 1,
    }


def _findings(repo: Path, comparison: str, rule: dict[str, object]) -> list[dict[str, object]]:
    return gather_structure_findings(
        repo,
        {
            "config": {"source_commit": None},
            "change_rules": {"central_growth_baseline": [rule]},
        },
        comparison_commit=comparison,
    )


def test_measure_python_function_tracks_span_nested_defs_and_decorators() -> None:
    measurement = measure_python_function(BASE_SOURCE, "create_app")

    assert measurement["symbol_line_count"] == len(BASE_SOURCE.splitlines())
    assert measurement["nested_function_names"] == {"health"}
    assert measurement["nested_function_count"] == 1
    assert measurement["decorated_handler_count"] == 1


def test_function_baseline_blocks_new_decorated_handler(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    path = _write(repo / "app/api/app.py", BASE_SOURCE)
    comparison = _commit(repo, "baseline create_app")
    path.write_text(
        BASE_SOURCE.replace(
            "    return app\n",
            "    @app.post(\"/jobs\")\n"
            "    def create_job():\n"
            "        return {\"id\": 1}\n\n"
            "    return app\n",
        ),
        encoding="utf-8",
    )
    _commit(repo, "add central handler")

    findings = _findings(repo, comparison, _rule(comparison))

    handler = next(item for item in findings if item["rule"] == "central-function-handler-growth")
    assert handler["new_members"] == ["create_job"]
    growth = next(item for item in findings if item["rule"] == "central-file-growth")
    assert growth["exceeded"]["decorated_handlers"]["actual"] == 2


def test_function_baseline_blocks_same_count_handler_replacement(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    path = _write(repo / "app/api/app.py", BASE_SOURCE)
    comparison = _commit(repo, "baseline create_app")
    path.write_text(BASE_SOURCE.replace("health", "status"), encoding="utf-8")
    _commit(repo, "replace central handler")

    findings = _findings(repo, comparison, _rule(comparison))

    handler = next(item for item in findings if item["rule"] == "central-function-handler-growth")
    assert handler["new_members"] == ["status"]
