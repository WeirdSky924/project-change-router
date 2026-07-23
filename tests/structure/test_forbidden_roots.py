from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
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
    _git(repo, "config", "user.email", "structure-guard@example.invalid")
    _git(repo, "config", "user.name", "Structure Guard Test")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _bundle(source_commit: str | None) -> dict[str, object]:
    rule: dict[str, object] = {
        "id": "legacy-provider-root",
        "path": "legacy/providers",
        "owner": "provider-runtime",
        "exit_stage": "provider-migration",
    }
    if source_commit is not None:
        rule["source_commit"] = source_commit
    return {
        "config": {},
        "change_rules": {"forbidden_implementation_roots": [rule]},
    }


def _forbidden_findings(
    repo: Path,
    source_commit: str | None,
) -> list[dict[str, object]]:
    return [
        finding
        for finding in gather_structure_findings(
            repo,
            _bundle(source_commit),
            comparison_commit=_git(repo, "rev-parse", "HEAD"),
        )
        if finding["rule"]
        in {
            "forbidden-implementation-root",
            "forbidden-implementation-root-growth",
            "structure-baseline-diagnostic",
        }
    ]


def test_existing_forbidden_root_code_is_baselined_at_comparison_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "legacy/providers/adapter.py", "class LegacyAdapter:\n    pass\n")
    source_commit = _commit(repo, "baseline legacy adapter")

    assert _forbidden_findings(repo, source_commit) == []


def test_new_code_file_under_forbidden_root_is_blocking(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "legacy/providers/adapter.py", "class LegacyAdapter:\n    pass\n")
    source_commit = _commit(repo, "baseline legacy adapter")
    _write(repo / "legacy/providers/new_runtime.py", "class NewRuntime:\n    pass\n")
    _commit(repo, "add new runtime")

    findings = _forbidden_findings(repo, source_commit)

    added = next(
        finding
        for finding in findings
        if finding["rule"] == "forbidden-implementation-root"
    )
    assert added["blocking"] is True
    assert added["source"] == "legacy/providers/new_runtime.py"
    assert added["source_commit"] == source_commit
    assert added["baseline_path"] is None


def test_ignored_new_code_file_cannot_bypass_forbidden_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / ".gitignore", "legacy/providers/*.py\n")
    source_commit = _commit(repo, "baseline ignore rules")
    _write(repo / "legacy/providers/hidden_runtime.py", "class HiddenRuntime:\n    pass\n")

    findings = _forbidden_findings(repo, source_commit)

    added = next(
        finding
        for finding in findings
        if finding["rule"] == "forbidden-implementation-root"
    )
    assert added["blocking"] is True
    assert added["source"] == "legacy/providers/hidden_runtime.py"


def test_existing_forbidden_root_file_net_growth_is_blocking(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    path = repo / "legacy/providers/adapter.py"
    _write(path, "class LegacyAdapter:\n    pass\n")
    source_commit = _commit(repo, "baseline legacy adapter")
    _write(
        path,
        "class LegacyAdapter:\n"
        "    def execute(self):\n"
        "        return None\n",
    )

    findings = _forbidden_findings(repo, source_commit)

    growth = next(
        finding
        for finding in findings
        if finding["rule"] == "forbidden-implementation-root-growth"
    )
    assert growth["blocking"] is True
    assert growth["source"] == "legacy/providers/adapter.py"
    assert growth["baseline_lines"] == 2
    assert growth["current_lines"] == 3


def test_same_size_legacy_repair_does_not_create_growth_budget(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    path = repo / "legacy/providers/adapter.py"
    _write(path, "class LegacyAdapter:\n    pass\n")
    source_commit = _commit(repo, "baseline legacy adapter")
    _write(path, "class LegacyAdapter:\n    value = 1\n")

    assert _forbidden_findings(repo, source_commit) == []


def test_missing_forbidden_root_comparison_commit_is_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "legacy/providers/adapter.py", "class LegacyAdapter:\n    pass\n")
    _commit(repo, "current legacy adapter")

    findings = _forbidden_findings(repo, None)

    diagnostic = next(
        finding
        for finding in findings
        if finding["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["severity"] == "P0"
    assert diagnostic["blocking"] is True
    assert diagnostic["completion_status"] == "incomplete"
    assert diagnostic["evidence_complete"] is False
    assert diagnostic["missing_fields"] == ["source_commit"]


def test_unresolvable_forbidden_root_comparison_is_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "legacy/providers/adapter.py", "class LegacyAdapter:\n    pass\n")
    _commit(repo, "current legacy adapter")

    findings = _forbidden_findings(repo, "missing-comparison-commit")

    diagnostic = next(
        finding
        for finding in findings
        if finding["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["severity"] == "P0"
    assert diagnostic["blocking"] is True
    assert diagnostic["completion_status"] == "incomplete"
    assert diagnostic["evidence_complete"] is False
    assert "missing-comparison-commit" in str(diagnostic["error"])


def test_new_extensionless_executable_under_forbidden_root_is_blocking(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write(repo / "README.md", "baseline\n")
    source_commit = _commit(repo, "baseline repository")
    executable = _write(
        repo / "legacy/providers/launch-provider",
        "#!/bin/sh\nexec provider-runtime\n",
    )
    executable.chmod(0o755)

    findings = _forbidden_findings(repo, source_commit)

    added = next(
        finding
        for finding in findings
        if finding["rule"] == "forbidden-implementation-root"
    )
    assert added["source"] == "legacy/providers/launch-provider"
    assert added["blocking"] is True
