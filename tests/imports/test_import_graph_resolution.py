from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.import_graph import build_import_graph


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_python_src_layout_resolves_absolute_package_import_runtime_cycle(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "src" / "acme" / "__init__.py", ""),
        _write(repo / "src" / "acme" / "left.py", "from acme import right\n"),
        _write(repo / "src" / "acme" / "right.py", "from acme import left\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (edge.source, edge.target)
        for edge in snapshot.edges
        if edge.language == "python" and edge.runtime
    } >= {
        ("src/acme/left.py", "src/acme/right.py"),
        ("src/acme/right.py", "src/acme/left.py"),
    }
    assert any(
        cycle.language == "python"
        and cycle.runtime
        and cycle.members == ("src/acme/left.py", "src/acme/right.py")
        for cycle in snapshot.cycles
    )


def test_python_monorepo_src_roots_resolve_cross_package_cycle_and_local_missing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "packages" / "a" / "src" / "acme_a" / "__init__.py", ""),
        _write(
            repo / "packages" / "a" / "src" / "acme_a" / "left.py",
            "from acme_b import right\nimport requests\n",
        ),
        _write(
            repo / "packages" / "a" / "src" / "acme_a" / "missing.py",
            "import acme_b.absent\n",
        ),
        _write(repo / "packages" / "b" / "src" / "acme_b" / "__init__.py", ""),
        _write(
            repo / "packages" / "b" / "src" / "acme_b" / "right.py",
            "from acme_a import left\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (edge.source, edge.target)
        for edge in snapshot.edges
        if edge.language == "python" and edge.runtime
    } >= {
        (
            "packages/a/src/acme_a/left.py",
            "packages/b/src/acme_b/right.py",
        ),
        (
            "packages/b/src/acme_b/right.py",
            "packages/a/src/acme_a/left.py",
        ),
    }
    assert any(
        cycle.runtime
        and cycle.members
        == (
            "packages/a/src/acme_a/left.py",
            "packages/b/src/acme_b/right.py",
        )
        for cycle in snapshot.cycles
    )
    assert [item.message for item in snapshot.diagnostics] == [
        "Unable to resolve local import acme_b.absent"
    ]

    scoped = build_import_graph(repo, [files[1], files[2]])
    assert any(
        edge.source == "packages/a/src/acme_a/left.py"
        and edge.target == "packages/b/src/acme_b/right.py"
        for edge in scoped.edges
    )
    assert [item.message for item in scoped.diagnostics] == [
        "Unable to resolve local import acme_b.absent"
    ]


def test_python_package_init_resolves_outside_the_scoped_resolution_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app" / "services" / "quality" / "__init__.py", "ENABLED = True\n")
    from_consumer = _write(
        repo / "app" / "from_consumer.py",
        "from app.services import quality\n",
    )
    import_consumer = _write(
        repo / "app" / "import_consumer.py",
        "import app.services.quality\n",
    )
    symbol_consumer = _write(
        repo / "app" / "symbol_consumer.py",
        "from app.services.quality import QualityRuntime\n",
    )

    snapshot = build_import_graph(
        repo,
        [from_consumer, import_consumer, symbol_consumer],
    )

    assert {
        (edge.source, edge.target)
        for edge in snapshot.edges
        if edge.language == "python"
    } == {
        ("app/from_consumer.py", "app/services/quality/__init__.py"),
        ("app/import_consumer.py", "app/services/quality/__init__.py"),
        ("app/symbol_consumer.py", "app/services/quality/__init__.py"),
    }
    assert not snapshot.diagnostics


def test_python_filesystem_fallback_keeps_missing_and_namespace_packages_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app" / "services" / "namespace_only" / "runtime.py", "VALUE = 1\n")
    consumer = _write(
        repo / "app" / "consumer.py",
        "import app.services.namespace_only\n"
        "import app.services.absent\n",
    )

    snapshot = build_import_graph(repo, [consumer])

    assert not snapshot.edges
    assert {
        item.message for item in snapshot.diagnostics
    } == {
        "Unable to resolve local import app.services.absent",
        "Unable to resolve local import app.services.namespace_only",
    }
    assert all(item.blocking for item in snapshot.diagnostics)


def test_commonjs_require_and_modern_js_suffixes_form_runtime_edges(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "src" / "left.cjs",
            "const { right } = require('./right')\nmodule.exports = { left: right }\n",
        ),
        _write(
            repo / "src" / "right.cjs",
            "const left = require('./left.cjs')\nmodule.exports = { right: left }\n",
        ),
        _write(repo / "src" / "entry.mjs", "import { left } from './left.cjs'\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert any(
        edge.source == "src/entry.mjs"
        and edge.target == "src/left.cjs"
        and edge.runtime
        for edge in snapshot.edges
    )
    assert any(
        cycle.language == "typescript"
        and cycle.runtime
        and cycle.members == ("src/left.cjs", "src/right.cjs")
        for cycle in snapshot.cycles
    )


def test_tsconfig_paths_resolve_edges_and_report_unresolved_aliases(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "tsconfig.json",
        """{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@core/*": ["src/core/*"],
      "@missing/*": ["src/missing/*"]
    }
  }
}
""",
    )
    files = [
        _write(repo / "src" / "core" / "left.ts", "import { right } from '@core/right'\n"),
        _write(repo / "src" / "core" / "right.ts", "import { left } from '@core/left'\n"),
        _write(repo / "src" / "consumer.ts", "import { absent } from '@missing/absent'\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert any(
        cycle.runtime
        and cycle.members == ("src/core/left.ts", "src/core/right.ts")
        for cycle in snapshot.cycles
    )
    unresolved = [
        item
        for item in snapshot.diagnostics
        if item.code == "unresolved-typescript-alias"
    ]
    assert len(unresolved) == 1
    assert unresolved[0].path == "src/consumer.ts"
    assert unresolved[0].blocking is True


def test_tsconfig_paths_prefer_the_most_specific_matching_pattern(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "tsconfig.json",
        """{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"],
      "@/foo/*": ["packages/foo/src/*"]
    }
  }
}
""",
    )
    files = [
        _write(repo / "src" / "foo" / "value.ts", "export const broad = true\n"),
        _write(
            repo / "packages" / "foo" / "src" / "value.ts",
            "export const specific = true\n",
        ),
        _write(
            repo / "src" / "consumer.ts",
            "import { specific } from '@/foo/value'\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    edge = next(item for item in snapshot.edges if item.source == "src/consumer.ts")
    assert edge.target == "packages/foo/src/value.ts"


def test_workspace_package_import_resolves_or_reports_incomplete_evidence(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(
        repo / "package.json",
        '{"name":"workspace","private":true,"workspaces":["packages/*"]}\n',
    )
    _write(repo / "packages" / "billing" / "package.json", '{"name":"@acme/billing"}\n')
    _write(repo / "packages" / "missing" / "package.json", '{"name":"@acme/missing"}\n')
    files = [
        _write(repo / "packages" / "billing" / "src" / "index.ts", "export const charge = true\n"),
        _write(
            repo / "packages" / "checkout" / "src" / "index.ts",
            "import { charge } from '@acme/billing'\n"
            "import { absent } from '@acme/missing'\n"
            "export const checkout = charge && absent\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert any(
        edge.source == "packages/checkout/src/index.ts"
        and edge.target == "packages/billing/src/index.ts"
        and edge.import_name == "@acme/billing"
        for edge in snapshot.edges
    )
    unresolved = [
        item
        for item in snapshot.diagnostics
        if item.code == "unresolved-workspace-import"
    ]
    assert len(unresolved) == 1
    assert unresolved[0].path == "packages/checkout/src/index.ts"
    assert unresolved[0].blocking is True
