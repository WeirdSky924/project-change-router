from __future__ import annotations

import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.import_graph import build_import_graph


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_for_await_body_regex_does_not_create_dynamic_import_edges(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "async function consume(items) {\n"
            "  for await (const item of items) /import('./ghost')/.test(item)\n"
            "}\n",
        ),
        _write(repo / "ghost.ts", "export const ghost = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert not snapshot.edges
    assert not snapshot.diagnostics


@pytest.mark.parametrize(
    ("keyword", "header"),
    (
        ("if", "if (second)"),
        ("for", "for (const item of items)"),
        ("for-await", "for await (const item of items)"),
        ("while", "while (second)"),
        ("with", "with (context)"),
    ),
)
def test_else_control_body_regex_does_not_create_dynamic_import_edges(
    tmp_path: Path,
    keyword: str,
    header: str,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            f"if (first) {{}} else {header} "
            f"/import('./ghost-{keyword}')/.test(value)\n",
        ),
        _write(
            repo / f"ghost-{keyword}.ts",
            "export const ghost = true\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert not snapshot.edges
    assert not snapshot.diagnostics


def test_keyword_properties_preserve_real_dynamic_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    keywords = (
        "await",
        "case",
        "delete",
        "do",
        "else",
        "in",
        "instanceof",
        "new",
        "of",
        "return",
        "throw",
        "typeof",
        "void",
        "yield",
    )
    files = [
        _write(
            repo / "entry.ts",
            "".join(
                f"export const value{index} = obj.{keyword} / "
                f"import('./dep-{keyword}') / divisor\n"
                for index, keyword in enumerate(keywords)
            ),
        ),
        *[
            _write(
                repo / f"dep-{keyword}.ts",
                f"export const value = {index}\n",
            )
            for index, keyword in enumerate(keywords)
        ],
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime) for item in snapshot.edges
    } == {
        ("entry.ts", f"dep-{keyword}.ts", True)
        for keyword in keywords
    }
    assert not snapshot.diagnostics


def test_control_keyword_methods_preserve_real_dynamic_imports(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    keywords = ("catch", "for", "if", "switch", "while", "with")
    files = [
        _write(
            repo / "entry.ts",
            "".join(
                f"export const value{index} = obj.{keyword}() / "
                f"import('./dep-{keyword}') / divisor\n"
                for index, keyword in enumerate(keywords)
            )
            + "export const optional = obj?.if() / "
            "import('./dep-optional') / divisor\n",
        ),
        *[
            _write(
                repo / f"dep-{keyword}.ts",
                f"export const value = {index}\n",
            )
            for index, keyword in enumerate(keywords)
        ],
        _write(repo / "dep-optional.ts", "export const value = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime) for item in snapshot.edges
    } == {
        *(('entry.ts', f'dep-{keyword}.ts', True) for keyword in keywords),
        ("entry.ts", "dep-optional.ts", True),
    }
    assert not snapshot.diagnostics
