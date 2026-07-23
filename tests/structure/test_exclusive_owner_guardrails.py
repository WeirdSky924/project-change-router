from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.structure_guardrails import gather_structure_findings


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _bundle(canonical_path: str) -> dict[str, object]:
    return {
        "config": {"source_commit": None},
        "change_rules": {
            "exclusive_source_owners": [
                {
                    "id": "EXEC-001-exclusive-token",
                    "root": "app",
                    "path_pattern": "app/**/*",
                    "owner": "provider-execution-gateway",
                    "allowed_paths": [canonical_path],
                    "forbidden_source_patterns": [r"\bexclusive_token\b"],
                }
            ]
        },
    }


@pytest.mark.parametrize("suffix", [".ts", ".tsx", ".js", ".jsx"])
def test_exclusive_owner_blocks_javascript_family_static_string_tokens(
    tmp_path: Path,
    suffix: str,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = f"app/canonical{suffix}"
    duplicate_path = f"app/duplicate{suffix}"
    _write(
        repo / canonical_path,
        'export const CANONICAL_TOKEN = "exclusive_token";\n',
    )
    _write(
        repo / duplicate_path,
        'export const DUPLICATE_TOKEN = "exclusive_token";\n',
    )

    findings = gather_structure_findings(
        repo,
        _bundle(canonical_path),
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (),
    )

    duplicate = next(
        item for item in findings if item["rule"] == "exclusive-source-owner"
    )
    assert duplicate["blocking"] is True
    assert duplicate["source"] == duplicate_path
    assert duplicate["allowed_paths"] == [canonical_path]


def test_javascript_comments_and_identifiers_do_not_match_exclusive_tokens(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = "app/canonical.ts"
    _write(
        repo / canonical_path,
        'export const CANONICAL_TOKEN = "exclusive_token";\n',
    )
    _write(
        repo / "app/consumer.ts",
        "const exclusive_token = resolveToken();\n"
        '// "exclusive_token" is documentation only.\n'
        "/* 'exclusive_token' remains a comment. */\n"
        'export const SAFE_VALUE = "ordinary";\n',
    )

    findings = gather_structure_findings(
        repo,
        _bundle(canonical_path),
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (),
    )

    assert not any(item["rule"] == "exclusive-source-owner" for item in findings)


@pytest.mark.parametrize(
    "source",
    [
        'export const DUPLICATE_TOKEN = "exclusive_" + "token";\n',
        'export const DUPLICATE_TOKEN = "exclusive_" /* gap */ + "token";\n',
        'export const DUPLICATE_TOKEN = "exclusive_" + ("token");\n',
        'export const DUPLICATE_TOKEN = ("exclusive_") + "token";\n',
        'export const DUPLICATE_TOKEN = `${use("exclusive_token")}`;\n',
    ],
)
def test_exclusive_owner_blocks_composed_javascript_static_strings(
    tmp_path: Path,
    source: str,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = "app/canonical.ts"
    duplicate_path = "app/duplicate.ts"
    _write(repo / canonical_path, 'export const TOKEN = "exclusive_token";\n')
    _write(repo / duplicate_path, source)

    findings = gather_structure_findings(
        repo,
        _bundle(canonical_path),
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (),
    )

    duplicate = next(
        item for item in findings if item["rule"] == "exclusive-source-owner"
    )
    assert duplicate["source"] == duplicate_path
    assert duplicate["blocking"] is True


def test_exclusive_owner_blocks_java_static_string_tokens(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    canonical_path = "app/Canonical.java"
    duplicate_path = "app/Duplicate.java"
    _write(
        repo / canonical_path,
        'final class Canonical { String token = "exclusive_token"; }\n',
    )
    _write(
        repo / duplicate_path,
        'final class Duplicate { String token = "exclusive_token"; }\n',
    )

    findings = gather_structure_findings(
        repo,
        _bundle(canonical_path),
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (),
    )

    duplicate = next(
        item for item in findings if item["rule"] == "exclusive-source-owner"
    )
    assert duplicate["source"] == duplicate_path
    assert duplicate["blocking"] is True


def test_exclusive_owner_unsupported_code_language_is_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    canonical_path = "app/canonical.ts"
    _write(repo / canonical_path, 'export const TOKEN = "exclusive_token";\n')
    _write(repo / "app/duplicate.go", 'const token = "exclusive_token"\n')

    findings = gather_structure_findings(
        repo,
        _bundle(canonical_path),
        comparison_commit="explicit-base",
        changed_path_loader=lambda _repo: (),
    )

    diagnostic = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["source"] == "app/duplicate.go"
    assert diagnostic["blocking"] is True
    assert diagnostic["evidence_complete"] is False
