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


def test_python_literal_importlib_imports_form_runtime_cycle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "a.py",
            "import importlib\n\nvalue = importlib.import_module('b')\n",
        ),
        _write(
            repo / "b.py",
            "import importlib\n\nvalue = importlib.import_module('a')\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (edge.source, edge.target, edge.runtime)
        for edge in snapshot.edges
        if edge.language == "python"
    } == {("a.py", "b.py", True), ("b.py", "a.py", True)}
    assert any(
        cycle.language == "python"
        and cycle.runtime
        and cycle.members == ("a.py", "b.py")
        for cycle in snapshot.cycles
    )


def test_typescript_literal_dynamic_imports_form_runtime_cycle(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "a.ts", "export const a = import('./b')\n"),
        _write(repo / "b.ts", "export const b = import('./a')\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (edge.source, edge.target, edge.runtime)
        for edge in snapshot.edges
        if edge.language == "typescript"
    } == {("a.ts", "b.ts", True), ("b.ts", "a.ts", True)}
    assert any(
        cycle.language == "typescript"
        and cycle.runtime
        and cycle.members == ("a.ts", "b.ts")
        for cycle in snapshot.cycles
    )


def test_typescript_comments_do_not_create_import_edges_or_cycles(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "a.ts",
            "// require('./b')\n"
            "/*\n"
            "import './b'\n"
            "const deferred = import('./b')\n"
            "*/\n"
            "export const a = true\n",
        ),
        _write(
            repo / "b.ts",
            "// import './a'\n"
            "/* require('./a') */\n"
            "export const b = true\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert not snapshot.edges
    assert not snapshot.cycles


def test_typescript_scanner_preserves_reexports_and_ignores_import_text(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "const text = \"require('./value')\"\n"
            "const template = `import('./value')`\n"
            "export { value } from './value'\n",
        ),
        _write(repo / "value.ts", "export const value = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert [
        (edge.source, edge.target, edge.import_name, edge.runtime)
        for edge in snapshot.edges
    ] == [("entry.ts", "value.ts", "./value", True)]


def test_python_non_literal_dynamic_import_is_blocking_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = _write(
        repo / "entry.py",
        "import importlib\n\nmodule_name = 'plugin'\nplugin = importlib.import_module(module_name)\n",
    )

    snapshot = build_import_graph(repo, [source])

    assert not snapshot.edges
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("dynamic-import-incomplete", "entry.py", "python", True)]


def test_typescript_non_literal_dynamic_import_is_blocking_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = _write(
        repo / "entry.ts",
        "const moduleName = './plugin'\nexport const plugin = import(moduleName)\n",
    )

    snapshot = build_import_graph(repo, [source])

    assert not snapshot.edges
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("dynamic-import-incomplete", "entry.ts", "typescript", True)]


def test_dynamic_import_text_in_comments_and_strings_is_not_diagnostic(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.py",
            "# importlib.import_module(module_name)\n"
            "TEXT = 'importlib.import_module(module_name)'\n",
        ),
        _write(
            repo / "entry.ts",
            "// import(moduleName)\n"
            "const text = 'import(moduleName)'\n"
            "const template = `import(moduleName)`\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert not snapshot.edges
    assert not snapshot.diagnostics


def test_static_type_import_after_value_export_stays_type_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "export const value = 1\nimport type { B } from './types'\n",
        ),
        _write(repo / "types.ts", "export type B = string\n"),
    ]

    snapshot = build_import_graph(repo, files)

    edge = next(item for item in snapshot.edges if item.source == "entry.ts")
    assert edge.target == "types.ts"
    assert edge.runtime is False


def test_prefixed_and_inline_type_reexports_stay_type_only(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "prefixed.ts",
            "export const value = 1\nexport type { B } from './types'\n",
        ),
        _write(repo / "inline.ts", "export { type B } from './types'\n"),
        _write(repo / "types.ts", "export type B = string\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime)
        for item in snapshot.edges
    } == {
        ("inline.ts", "types.ts", False),
        ("prefixed.ts", "types.ts", False),
    }


def test_typescript_template_interpolations_preserve_runtime_imports(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "const moduleName = './dynamic'\n"
            "export const unresolved = `${(() => import(moduleName))()}`\n"
            "export const loaded = `${(() => ({ value: import('./plugin'), marker: '}' }))()}`\n"
            "export const required = `${[')', require('./required')][1]}`\n"
            "export const nested = `${`inner ${import('./nested')}`}`\n"
            "export const text = `import(ignoredName) require('./ignored')`\n",
        ),
        _write(repo / "nested.ts", "export const nested = true\n"),
        _write(repo / "plugin.ts", "export const plugin = true\n"),
        _write(repo / "required.ts", "export const required = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime)
        for item in snapshot.edges
    } == {
        ("entry.ts", "nested.ts", True),
        ("entry.ts", "plugin.ts", True),
        ("entry.ts", "required.ts", True),
    }
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("dynamic-import-incomplete", "entry.ts", "typescript", True)]


def test_python_import_module_alias_and_builtin_literals_create_edges(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.py",
            "from importlib import import_module as load\n\n"
            "first = load('plugin')\n"
            "second = __import__('required')\n",
        ),
        _write(repo / "plugin.py", "VALUE = 1\n"),
        _write(repo / "required.py", "VALUE = 2\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime)
        for item in snapshot.edges
    } == {
        ("entry.py", "plugin.py", True),
        ("entry.py", "required.py", True),
    }
    assert not snapshot.diagnostics


def test_python_import_module_and_builtin_non_literals_are_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "import_module_entry.py",
            "from importlib import import_module\n\n"
            "module_name = 'plugin'\n"
            "plugin = import_module(module_name)\n",
        ),
        _write(
            repo / "builtin_entry.py",
            "module_name = 'plugin'\nplugin = __import__(module_name)\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert not snapshot.edges
    assert {
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    } == {
        ("dynamic-import-incomplete", "builtin_entry.py", "python", True),
        ("dynamic-import-incomplete", "import_module_entry.py", "python", True),
    }


def test_typescript_regex_literals_do_not_create_import_evidence(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "const importPattern = /import(moduleName)/\n"
            "const requirePattern = /require(\".\\/plugin\")/\n"
            "const quotient = total / divisor\n"
            "export const loaded = total / import('./plugin')\n",
        ),
        _write(repo / "plugin.ts", "export const plugin = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert [
        (item.source, item.target, item.runtime) for item in snapshot.edges
    ] == [("entry.ts", "plugin.ts", True)]
    assert not snapshot.diagnostics


def test_ambiguous_typescript_slash_is_incomplete_not_import_evidence(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    source = _write(
        repo / "entry.ts",
        "const previous = condition\n/import(moduleName)/\n",
    )

    snapshot = build_import_graph(repo, [source])

    assert not snapshot.edges
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("typescript-lexical-scan-incomplete", "entry.ts", "typescript", True)]


def test_commonjs_dynamic_and_template_requires_are_complete_or_blocking(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.ts",
            "const moduleName = './plugin'\n"
            "export const direct = require(moduleName)\n"
            "export const interpolated = `${require(moduleName)}`\n"
            "export const literal = require(`./plugin`)\n"
            "export const dynamicTemplate = require(`./${moduleName}`)\n",
        ),
        _write(repo / "plugin.ts", "export const plugin = true\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert [
        (item.source, item.target, item.runtime) for item in snapshot.edges
    ] == [("entry.ts", "plugin.ts", True)]
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("dynamic-import-incomplete", "entry.ts", "typescript", True)]


def test_python_dynamic_import_prescan_and_shadowing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(
            repo / "entry.py",
            "def early():\n"
            "    return import_module('plugin')\n\n"
            "def module_alias():\n"
            "    return il.import_module('required')\n\n"
            "from importlib import import_module\n"
            "import importlib as il\n\n"
            "def parameter_shadow(import_module):\n"
            "    return import_module(module_name)\n\n"
            "def assignment_shadow():\n"
            "    import_module = lambda value: value\n"
            "    return import_module(module_name)\n",
        ),
        _write(repo / "plugin.py", "VALUE = 1\n"),
        _write(repo / "required.py", "VALUE = 2\n"),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.target, item.runtime) for item in snapshot.edges
    } == {
        ("entry.py", "plugin.py", True),
        ("entry.py", "required.py", True),
    }
    assert not snapshot.diagnostics


def test_python_all_literal_mutations_and_dynamic_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    literal = _write(
        repo / "literal.py",
        "__all__ = ['A'] + ('B',)\n"
        "__all__ += ['C']\n"
        "__all__.append('D')\n"
        "__all__.extend(('E', 'F'))\n",
    )
    dynamic = _write(
        repo / "dynamic.py",
        "__all__ = ['Known']\n__all__.extend(build_exports())\n",
    )

    snapshot = build_import_graph(repo, [literal, dynamic])

    assert {
        (item.source, item.symbol) for item in snapshot.exports
    } == {
        ("dynamic.py", "Known"),
        ("literal.py", "A"),
        ("literal.py", "B"),
        ("literal.py", "C"),
        ("literal.py", "D"),
        ("literal.py", "E"),
        ("literal.py", "F"),
    }
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("public-export-evidence-incomplete", "dynamic.py", "python", True)]


def test_commonjs_and_typescript_assignment_exports_are_governed(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    files = [
        _write(repo / "object.cjs", "const A = 1, B = 2\nmodule.exports = { A, B }\n"),
        _write(repo / "named.cjs", "const A = 1\nexports.A = A\n"),
        _write(repo / "assignment.ts", "const value = 1\nexport = value\n"),
        _write(repo / "dynamic.cjs", "module.exports = buildExports()\nexports[name] = 1\n"),
        _write(
            repo / "reads.cjs",
            "const same = module.exports === other\nconst value = exports[name]\n",
        ),
    ]

    snapshot = build_import_graph(repo, files)

    assert {
        (item.source, item.symbol) for item in snapshot.exports
    } == {
        ("assignment.ts", "default"),
        ("named.cjs", "A"),
        ("object.cjs", "A"),
        ("object.cjs", "B"),
    }
    assert [
        (item.code, item.path, item.language, item.blocking)
        for item in snapshot.diagnostics
    ] == [("public-export-evidence-incomplete", "dynamic.cjs", "typescript", True)]
