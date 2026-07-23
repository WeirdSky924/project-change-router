from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from router_support.architecture_baseline import (
    classify_findings_against_baseline,
    finding_fingerprint,
    validate_architecture_baseline,
)
from router_support.import_source_scan import (
    JSX_SOURCE_SUFFIXES,
    python_all_exports,
    python_dynamic_bindings,
    scan_typescript_source,
)


PYTHON_SUFFIXES = {".py"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


@dataclass(frozen=True)
class ImportEdge:
    source: str
    target: str
    import_name: str
    language: str
    runtime: bool
    imported_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportCycle:
    language: str
    runtime: bool
    members: tuple[str, ...]


@dataclass(frozen=True)
class PublicExport:
    module: str
    source: str
    symbol: str
    language: str


@dataclass(frozen=True)
class GraphDiagnostic:
    code: str
    path: str
    language: str
    message: str
    blocking: bool = True


@dataclass(frozen=True)
class ImportGraphSnapshot:
    edges: tuple[ImportEdge, ...]
    cycles: tuple[ImportCycle, ...]
    exports: tuple[PublicExport, ...] = ()
    diagnostics: tuple[GraphDiagnostic, ...] = ()


def _relative(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _python_source_roots(repo_root: Path) -> tuple[Path, ...]:
    root = repo_root.resolve()
    manifests = ("pyproject.toml", "setup.py", "setup.cfg")
    def supported(candidate: Path) -> bool:
        return candidate.parent == root or any((candidate.parent / name).is_file() for name in manifests) or any((child / "__init__.py").is_file() for child in candidate.iterdir() if child.is_dir())
    roots = {root}
    roots.update(candidate.resolve() for pattern in ("src", "*/src", "*/*/src") for candidate in root.glob(pattern) if candidate.is_dir() and supported(candidate))
    return tuple(sorted(roots, key=lambda item: (len(item.parts), item.as_posix())))


def _python_module(repo_root: Path, path: Path, import_roots: Iterable[Path]) -> str:
    source_root = max((root for root in import_roots if root == path.parent or root in path.parents), key=lambda item: len(item.parts), default=repo_root.resolve())
    parts = list(path.resolve().relative_to(source_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_python_candidate(candidates: Iterable[str], modules: Mapping[str, Path], import_roots: Iterable[Path]) -> tuple[str, Path] | None:
    for candidate in candidates:
        target = modules.get(candidate)
        if target is None:
            relative = Path(*candidate.split("."))
            target = next((item for root in import_roots for item in ((root / relative).with_suffix(".py"), root / relative / "__init__.py") if item.is_file()), None)
        if target is not None:
            return candidate, target
    return None


def _is_type_checking_test(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING") or (
        isinstance(node, ast.Attribute)
        and node.attr == "TYPE_CHECKING"
        and isinstance(node.value, ast.Name)
        and node.value.id == "typing"
    )


@dataclass(frozen=True)
class _PythonDynamicScope:
    import_module_aliases: frozenset[str]
    importlib_aliases: frozenset[str]
    builtin_import_enabled: bool


class _PythonImportVisitor(ast.NodeVisitor):
    def __init__(self, repo_root: Path, path: Path, modules: Mapping[str, Path], import_roots: tuple[Path, ...], tree: ast.Module) -> None:
        self.repo_root = repo_root
        self.path = path
        self.modules = modules
        self.import_roots = import_roots
        source_module = _python_module(repo_root, path, import_roots)
        self.package = source_module.split(".") if path.name == "__init__.py" else source_module.split(".")[:-1]
        self.local_roots = {name.split(".", 1)[0] for name in modules} | {item.stem for root in import_roots for item in root.iterdir() if item.suffix == ".py" or item.is_dir()}
        bindings = python_dynamic_bindings(tree.body)
        self.dynamic_scopes = [
            _PythonDynamicScope(
                bindings.import_module_aliases,
                bindings.importlib_aliases,
                "__import__" not in bindings.bound,
            )
        ]
        self.runtime = True
        self.edges: list[ImportEdge] = []
        self.diagnostics: list[GraphDiagnostic] = []

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        previous = self.runtime
        if _is_type_checking_test(node.test):
            self.runtime = False
        for child in node.body:
            self.visit(child)
        self.runtime = previous
        for child in node.orelse:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record([alias.name], alias.name, (alias.name.rsplit(".", 1)[-1],), alias.name.split(".", 1)[0] in self.local_roots)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            keep = max(0, len(self.package) - node.level + 1)
            prefix = self.package[:keep]
            base = ".".join(prefix + ((node.module or "").split(".") if node.module else []))
        else:
            base = node.module or ""
        grouped: dict[Path, dict[str, object]] = {}
        unresolved = False
        for alias in node.names:
            candidate = ".".join(part for part in (base, alias.name) if part and alias.name != "*")
            candidates = [candidate, base] if candidate != base else [base]
            resolved = _resolve_python_candidate((item for item in candidates if item), self.modules, self.import_roots)
            if resolved is None:
                unresolved = unresolved or node.level > 0 or base.split(".", 1)[0] in self.local_roots
                continue
            _, target = resolved
            if target.resolve() == self.path.resolve():
                continue
            item = grouped.setdefault(target.resolve(), {"names": set(), "imports": set()})
            item["names"].add(alias.name)
            item["imports"].add(candidate or base)
        for target, item in grouped.items():
            self.edges.append(
                ImportEdge(
                    source=_relative(self.repo_root, self.path),
                    target=_relative(self.repo_root, target),
                    import_name=sorted(item["imports"])[0],
                    language="python",
                    runtime=self.runtime,
                    imported_symbols=tuple(sorted(item["names"])),
                )
            )
        if unresolved:
            self._unresolved(base or ".")

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for child in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]:
            if child is not None:
                self.visit(child)
        bindings = python_dynamic_bindings(node.body, node.args)
        parent = self.dynamic_scopes[-1]
        self.dynamic_scopes.append(
            _PythonDynamicScope(
                frozenset(parent.import_module_aliases - bindings.bound)
                | bindings.import_module_aliases,
                frozenset(parent.importlib_aliases - bindings.bound)
                | bindings.importlib_aliases,
                parent.builtin_import_enabled and "__import__" not in bindings.bound,
            )
        )
        for child in node.body:
            self.visit(child)
        self.dynamic_scopes.pop()

    visit_FunctionDef = _visit_function
    visit_AsyncFunctionDef = _visit_function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for child in [*node.args.defaults, *node.args.kw_defaults]:
            if child is not None:
                self.visit(child)
        bindings = python_dynamic_bindings((), node.args)
        parent = self.dynamic_scopes[-1]
        self.dynamic_scopes.append(
            _PythonDynamicScope(
                frozenset(parent.import_module_aliases - bindings.bound),
                frozenset(parent.importlib_aliases - bindings.bound),
                parent.builtin_import_enabled and "__import__" not in bindings.bound,
            )
        )
        self.visit(node.body)
        self.dynamic_scopes.pop()

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        scope = self.dynamic_scopes[-1]
        is_import_module = (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in scope.importlib_aliases
            and function.attr == "import_module"
        ) or (
            isinstance(function, ast.Name)
            and (
                function.id in scope.import_module_aliases
                or (function.id == "__import__" and scope.builtin_import_enabled)
            )
        )
        if is_import_module:
            module = node.args[0] if node.args else None
            if isinstance(module, ast.Constant) and isinstance(module.value, str):
                name = module.value
                self._record([name], name, (), name.split(".", 1)[0] in self.local_roots)
            else:
                self.diagnostics.append(
                    GraphDiagnostic(
                        code="dynamic-import-incomplete",
                        path=_relative(self.repo_root, self.path),
                        language="python",
                        message="Unable to resolve non-literal dynamic import call",
                    )
                )
        self.generic_visit(node)

    def _record(
        self,
        candidates: list[str],
        import_name: str,
        symbols: tuple[str, ...],
        local: bool,
    ) -> None:
        resolved = _resolve_python_candidate(candidates, self.modules, self.import_roots)
        if resolved is None:
            if local:
                self._unresolved(import_name)
            return
        _, target = resolved
        if target.resolve() == self.path.resolve():
            return
        self.edges.append(
            ImportEdge(
                source=_relative(self.repo_root, self.path),
                target=_relative(self.repo_root, target),
                import_name=import_name,
                language="python",
                runtime=self.runtime,
                imported_symbols=symbols,
            )
        )

    def _unresolved(self, import_name: str) -> None:
        self.diagnostics.append(
            GraphDiagnostic(
                code="unresolved-local-import",
                path=_relative(self.repo_root, self.path),
                language="python",
                message=f"Unable to resolve local import {import_name}",
            )
        )


def _python_graph_items(repo_root: Path, path: Path, modules: Mapping[str, Path], import_roots: tuple[Path, ...]) -> tuple[list[ImportEdge], list[PublicExport], list[GraphDiagnostic]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [], [], [
            GraphDiagnostic(
                code="python-parse-error",
                path=_relative(repo_root, path),
                language="python",
                message=str(exc),
            )
        ]
    visitor = _PythonImportVisitor(repo_root, path, modules, import_roots, tree)
    visitor.visit(tree)
    module = _python_module(repo_root, path, import_roots)
    export_symbols, export_evidence_incomplete = python_all_exports(tree)
    exports = [
        PublicExport(module=module, source=_relative(repo_root, path), symbol=symbol, language="python")
        for symbol in export_symbols
    ]
    if export_evidence_incomplete:
        visitor.diagnostics.append(
            GraphDiagnostic(
                code="public-export-evidence-incomplete",
                path=_relative(repo_root, path),
                language="python",
                message="Unable to resolve all __all__ mutations",
            )
        )
    return visitor.edges, exports, visitor.diagnostics


@dataclass(frozen=True)
class _TypeScriptPathRule:
    pattern: str
    targets: tuple[str, ...]
    base_url: Path


def _resolve_typescript_base(base: Path, available: set[Path]) -> Path | None:
    if base.suffix and base.suffix.lower() not in TYPESCRIPT_SUFFIXES:
        return None
    candidates = [base] if base.suffix else []
    if not base.suffix:
        candidates.extend(base.with_suffix(suffix) for suffix in sorted(TYPESCRIPT_SUFFIXES))
        candidates.extend(base / f"index{suffix}" for suffix in sorted(TYPESCRIPT_SUFFIXES))
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in available:
            return resolved
    return None


def _ancestor_files(repo_root: Path, paths: Iterable[Path], name: str) -> set[Path]:
    candidates: set[Path] = set()
    root = repo_root.resolve()
    for path in paths:
        parent = path.resolve().parent
        while parent == root or root in parent.parents:
            candidate = parent / name
            if candidate.is_file():
                candidates.add(candidate)
            if parent == root:
                break
            parent = parent.parent
    return candidates


def _typescript_diagnostic(code: str, repo_root: Path, path: Path, message: str) -> GraphDiagnostic:
    return GraphDiagnostic(code, _relative(repo_root, path), "typescript", message)


def _typescript_path_rules(repo_root: Path, paths: Iterable[Path]) -> tuple[dict[Path, tuple[_TypeScriptPathRule, ...]], list[GraphDiagnostic]]:
    by_root: dict[Path, tuple[_TypeScriptPathRule, ...]] = {}
    diagnostics: list[GraphDiagnostic] = []
    for config_path in sorted(_ancestor_files(repo_root, paths, "tsconfig.json")):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            diagnostics.append(_typescript_diagnostic("typescript-config-parse-error", repo_root, config_path, str(exc)))
            continue
        if payload.get("extends"):
            diagnostics.append(_typescript_diagnostic("typescript-config-extends-incomplete", repo_root, config_path, "Inherited tsconfig paths are not resolved"))
        compiler = payload.get("compilerOptions")
        compiler = compiler if isinstance(compiler, dict) else {}
        raw_paths = compiler.get("paths")
        if raw_paths is None:
            by_root[config_path.parent.resolve()] = ()
            continue
        if not isinstance(raw_paths, dict):
            diagnostics.append(_typescript_diagnostic("typescript-paths-invalid", repo_root, config_path, "compilerOptions.paths must be an object"))
            continue
        base_url = compiler.get("baseUrl", ".")
        if not isinstance(base_url, str):
            base_url = "."
            diagnostics.append(_typescript_diagnostic("typescript-base-url-invalid", repo_root, config_path, "compilerOptions.baseUrl must be a string"))
        rules: list[_TypeScriptPathRule] = []
        for pattern, targets in raw_paths.items():
            if not isinstance(pattern, str) or pattern.count("*") > 1:
                diagnostics.append(_typescript_diagnostic("typescript-path-pattern-unsupported", repo_root, config_path, f"Unsupported tsconfig path pattern {pattern!r}"))
                continue
            if isinstance(targets, list) and all(isinstance(item, str) for item in targets):
                rules.append(_TypeScriptPathRule(pattern, tuple(targets), (config_path.parent / base_url).resolve()))
            else:
                diagnostics.append(_typescript_diagnostic("typescript-path-targets-invalid", repo_root, config_path, f"tsconfig path {pattern!r} must map to string targets"))
        by_root[config_path.parent.resolve()] = tuple(sorted(rules, key=lambda rule: (len(rule.pattern.partition("*")[0]), len(rule.pattern.partition("*")[2])), reverse=True))
    return by_root, diagnostics


def _workspace_packages(repo_root: Path, paths: Iterable[Path]) -> tuple[dict[str, tuple[Path, tuple[Path, ...]]], list[GraphDiagnostic]]:
    root = repo_root.resolve()
    manifests = _ancestor_files(root, paths, "package.json")
    root_manifest = root / "package.json"
    diagnostics: list[GraphDiagnostic] = []
    if root_manifest.is_file():
        manifests.add(root_manifest)
        try:
            root_payload = json.loads(root_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            diagnostics.append(_typescript_diagnostic("workspace-manifest-parse-error", root, root_manifest, str(exc)))
            root_payload = {}
        patterns = root_payload.get("workspaces", [])
        if isinstance(patterns, dict):
            patterns = patterns.get("packages", [])
        if isinstance(patterns, list):
            for pattern in patterns:
                if not isinstance(pattern, str) or pattern.startswith("!"):
                    continue
                manifests.update(
                    candidate / "package.json"
                    for candidate in root.glob(pattern)
                    if (candidate / "package.json").is_file()
                )
    packages: dict[str, tuple[Path, tuple[Path, ...]]] = {}
    for manifest in sorted(manifests):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            diagnostics.append(_typescript_diagnostic("workspace-manifest-parse-error", root, manifest, str(exc)))
            continue
        name = payload.get("name")
        if not isinstance(name, str) or not name:
            continue
        package_root = manifest.parent.resolve()
        entries: list[Path] = []
        exported = payload.get("exports")
        exported = exported.get(".") if isinstance(exported, dict) else exported
        if isinstance(exported, dict):
            entries.extend(
                package_root / value
                for key in ("import", "require", "default", "types")
                if isinstance((value := exported.get(key)), str)
            )
        elif isinstance(exported, str):
            entries.append(package_root / exported)
        entries.extend(
            package_root / value
            for key in ("module", "main", "types")
            if isinstance((value := payload.get(key)), str)
        )
        entries.extend((package_root / "src" / "index", package_root / "index"))
        packages[name] = (package_root, tuple(entries))
    return packages, diagnostics


def _path_pattern_capture(pattern: str, specifier: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern == specifier else None
    prefix, suffix = pattern.split("*", 1)
    if not specifier.startswith(prefix) or not specifier.endswith(suffix):
        return None
    return specifier[len(prefix) : len(specifier) - len(suffix) if suffix else None]


def _rules_for_path(path: Path, rules_by_root: Mapping[Path, tuple[_TypeScriptPathRule, ...]]) -> tuple[_TypeScriptPathRule, ...]:
    candidates = [root for root in rules_by_root if path == root or root in path.parents]
    return rules_by_root[max(candidates, key=lambda item: len(item.parts))] if candidates else ()


def _resolve_typescript_import(
    path: Path,
    specifier: str,
    available: set[Path],
    rules_by_root: Mapping[Path, tuple[_TypeScriptPathRule, ...]],
    workspaces: Mapping[str, tuple[Path, tuple[Path, ...]]],
) -> tuple[Path | None, str | None]:
    if specifier.startswith("."):
        suffix = Path(specifier).suffix.lower()
        if suffix not in {"", *TYPESCRIPT_SUFFIXES}:
            return None, None
        return _resolve_typescript_base(path.parent / specifier, available), "local"
    for rule in _rules_for_path(path, rules_by_root):
        capture = _path_pattern_capture(rule.pattern, specifier)
        if capture is None:
            continue
        for target in rule.targets:
            resolved = _resolve_typescript_base(rule.base_url / target.replace("*", capture), available)
            if resolved is not None:
                return resolved, "alias"
        return None, "alias"
    names = [name for name in workspaces if specifier == name or specifier.startswith(name + "/")]
    if not names:
        return None, None
    name = max(names, key=len)
    package_root, entries = workspaces[name]
    subpath = specifier[len(name) :].lstrip("/")
    candidates = (package_root / subpath, package_root / "src" / subpath) if subpath else entries
    for candidate in candidates:
        resolved = _resolve_typescript_base(candidate, available)
        if resolved is not None:
            return resolved, "workspace"
    return None, "workspace"


def _typescript_graph_items(
    repo_root: Path,
    path: Path,
    available: set[Path],
    rules_by_root: Mapping[Path, tuple[_TypeScriptPathRule, ...]],
    workspaces: Mapping[str, tuple[Path, tuple[Path, ...]]],
) -> tuple[list[ImportEdge], list[PublicExport], list[GraphDiagnostic]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [], [], [
            GraphDiagnostic(
                code="typescript-read-error",
                path=_relative(repo_root, path),
                language="typescript",
                message=str(exc),
            )
        ]
    edges: list[ImportEdge] = []
    diagnostics: list[GraphDiagnostic] = []
    scan = scan_typescript_source(
        source,
        allow_jsx=path.suffix.lower() in JSX_SOURCE_SUFFIXES,
    )
    if scan.incomplete_dynamic_imports:
        diagnostics.append(
            GraphDiagnostic(
                code="dynamic-import-incomplete",
                path=_relative(repo_root, path),
                language="typescript",
                message=(
                    "Unable to resolve "
                    f"{scan.incomplete_dynamic_imports} non-literal dynamic import call(s)"
                ),
            )
        )
    if scan.incomplete_lexical_regions:
        diagnostics.append(
            GraphDiagnostic(
                code="typescript-lexical-scan-incomplete",
                path=_relative(repo_root, path),
                language="typescript",
                message=(
                    "Unable to disambiguate "
                    f"{scan.incomplete_lexical_regions} slash-delimited region(s)"
                ),
            )
        )
    if scan.incomplete_public_exports:
        diagnostics.append(
            GraphDiagnostic(
                code="public-export-evidence-incomplete",
                path=_relative(repo_root, path),
                language="typescript",
                message="Unable to resolve all CommonJS public export mutations",
            )
        )
    for item in scan.imports:
        specifier = item.specifier
        target, resolution_kind = _resolve_typescript_import(
            path,
            specifier,
            available,
            rules_by_root,
            workspaces,
        )
        if target is None:
            diagnostic_code = {
                "local": "unresolved-local-import",
                "alias": "unresolved-typescript-alias",
                "workspace": "unresolved-workspace-import",
            }.get(resolution_kind or "")
            if diagnostic_code:
                diagnostics.append(
                    GraphDiagnostic(
                        code=diagnostic_code,
                        path=_relative(repo_root, path),
                        language="typescript",
                        message=f"Unable to resolve {resolution_kind} import {specifier}",
                    )
                )
            continue
        if target == path.resolve():
            continue
        edges.append(
            ImportEdge(
                source=_relative(repo_root, path),
                target=_relative(repo_root, target),
                import_name=specifier,
                language="typescript",
                runtime=item.runtime,
                imported_symbols=item.imported_symbols,
            )
        )
    module = _relative(repo_root, path.with_suffix(""))
    exports = [
        PublicExport(module=module, source=_relative(repo_root, path), symbol=symbol, language="typescript")
        for symbol in scan.exports
    ]
    return edges, exports, diagnostics


def _strongly_connected_components(edges: Iterable[ImportEdge]) -> list[tuple[str, ...]]:
    graph: dict[str, set[str]] = {}
    for edge in edges:
        graph.setdefault(edge.source, set()).add(edge.target)
        graph.setdefault(edge.target, set())
    index = 0
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = index
        lows[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in indexes:
                visit(target)
                lows[node] = min(lows[node], lows[target])
            elif target in active:
                lows[node] = min(lows[node], indexes[target])
        if lows[node] != indexes[node]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            active.remove(target)
            component.append(target)
            if target == node:
                break
        members = tuple(sorted(component))
        if len(members) > 1 or (members and members[0] in graph[members[0]]):
            components.append(members)

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted(set(components))


def build_import_graph(
    repo_root: Path,
    source_paths: Iterable[Path],
    *,
    resolution_paths: Iterable[Path] = (),
) -> ImportGraphSnapshot:
    root = repo_root.resolve()
    files = sorted({path.resolve() for path in source_paths if path.is_file()})
    python_files = [path for path in files if path.suffix.lower() in PYTHON_SUFFIXES]
    typescript_files = [path for path in files if path.suffix.lower() in TYPESCRIPT_SUFFIXES]
    resolution_files = sorted(
        set(files) | {path.resolve() for path in resolution_paths if path.is_file()}
    )
    python_roots = _python_source_roots(root)
    modules = {
        _python_module(root, path, python_roots): path
        for path in resolution_files
        if path.suffix.lower() in PYTHON_SUFFIXES
    }
    available_ts = {path for path in resolution_files if path.suffix.lower() in TYPESCRIPT_SUFFIXES}
    typescript_rules, typescript_diagnostics = _typescript_path_rules(root, available_ts) if available_ts else ({}, [])
    workspaces, workspace_diagnostics = _workspace_packages(root, available_ts) if available_ts else ({}, [])
    edges: list[ImportEdge] = []
    exports: list[PublicExport] = []
    diagnostics: list[GraphDiagnostic] = [*typescript_diagnostics, *workspace_diagnostics]
    for path in python_files:
        path_edges, path_exports, path_diagnostics = _python_graph_items(root, path, modules, python_roots)
        edges.extend(path_edges)
        exports.extend(path_exports)
        diagnostics.extend(path_diagnostics)
    for path in typescript_files:
        path_edges, path_exports, path_diagnostics = _typescript_graph_items(
            root,
            path,
            available_ts,
            typescript_rules,
            workspaces,
        )
        edges.extend(path_edges)
        exports.extend(path_exports)
        diagnostics.extend(path_diagnostics)
    edges = sorted(
        set(edges),
        key=lambda edge: (
            edge.language,
            edge.source,
            edge.target,
            edge.import_name,
            edge.runtime,
            edge.imported_symbols,
        ),
    )
    cycles: list[ImportCycle] = []
    for language in ("python", "typescript"):
        language_edges = [edge for edge in edges if edge.language == language]
        runtime_components = _strongly_connected_components(edge for edge in language_edges if edge.runtime)
        cycles.extend(ImportCycle(language, True, members) for members in runtime_components)
        runtime_sets = [set(members) for members in runtime_components]
        for members in _strongly_connected_components(language_edges):
            if any(runtime_members <= set(members) for runtime_members in runtime_sets):
                continue
            cycles.append(ImportCycle(language, False, members))
    return ImportGraphSnapshot(
        tuple(edges),
        tuple(sorted(cycles, key=lambda item: (item.language, not item.runtime, item.members))),
        tuple(sorted(set(exports), key=lambda item: (item.language, item.module, item.source, item.symbol))),
        tuple(sorted(set(diagnostics), key=lambda item: (item.language, item.path, item.code, item.message))),
    )
