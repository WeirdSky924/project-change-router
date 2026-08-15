from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from router_support.route_constraints import glob_match


DOCUMENT_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".toml", ".xml", ".txt"}


def _valid_read_paths(entries: list[Any]) -> list[str]:
    return [
        str(entry).replace("\\", "/")
        for entry in entries
        if entry and not any(char.isspace() for char in str(entry))
    ]


def module_scoped_read_path(module_path: str, read_path: str) -> Optional[str]:
    module_root = str(module_path or ".").replace("\\", "/").rstrip("/") or "."
    candidate = str(read_path or "").replace("\\", "/").strip()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    if candidate.startswith("/"):
        return candidate
    known_file_suffixes = {
        "py", "md", "yaml", "yml", "json", "toml", "xml", "txt",
        "js", "ts", "tsx", "mjs", "cjs", "sh", "sql",
    }
    if (
        "/" not in candidate
        and candidate.rsplit(".", 1)[-1] not in known_file_suffixes
        and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", candidate)
    ):
        import_path = candidate.replace(".", "/")
        module_file = PurePosixPath(module_root)
        if module_file.suffix:
            module_import_path = str(
                module_file.parent
                if module_file.name == "__init__.py"
                else module_file.with_suffix("")
            )
            candidate = module_root if import_path == module_import_path else import_path
        else:
            candidate = (
                f"{import_path}/__init__.py"
                if import_path == module_root
                else import_path
            )
    base = module_root.rsplit("/", 1)[0] if PurePosixPath(module_root).suffix else module_root
    if (
        module_root == "."
        or candidate == module_root
        or candidate.startswith(f"{module_root}/")
        or (base != module_root and candidate.startswith(f"{base}/"))
    ):
        return candidate
    return f"{base}/{candidate.lstrip('/')}"


def build_required_read_paths(
    capability: Optional[Any],
    modules: list[Any],
    changed_paths: list[str],
    *,
    module_for_path: Callable[[str, list[Any]], Optional[Any]],
) -> list[str]:
    paths: list[str] = []
    if capability:
        lifecycle = capability.lifecycle or {}
        planned_root = lifecycle.get("canonical_root", {}).get("status") == "planned"
        bound_reads: list[str] = []
        for binding in lifecycle.get("required_read_bindings", []):
            patterns = list(binding.get("when_changed_paths", []))
            if patterns and any(
                glob_match(patterns, path) for path in changed_paths
            ):
                bound_reads.extend(
                    _valid_read_paths(list(binding.get("required_reads", [])))
                )
        if bound_reads:
            return list(dict.fromkeys(bound_reads))
        paths.extend(_valid_read_paths(list(lifecycle.get("required_reads", []))))
        if not planned_root:
            paths.extend(
                str(entry).replace("\\", "/")
                for entry in capability.public_entries[:4]
                if entry and not any(char.isspace() for char in str(entry))
            )
        for owner in capability.owner_modules:
            module = next((item for item in modules if item.path == owner), None)
            if module and module.status != "planned":
                if module.public_api:
                    public_read = module_scoped_read_path(module.path, module.public_api)
                    if public_read:
                        paths.append(public_read)
                for key in module.key_files[:2]:
                    key_read = module_scoped_read_path(module.path, key)
                    if key_read:
                        paths.append(key_read)
    for path in changed_paths[:2]:
        module = module_for_path(path, modules)
        if module and module.status != "planned" and module.public_api:
            public_read = module_scoped_read_path(module.path, module.public_api)
            if public_read:
                paths.append(public_read)
    dedup: list[str] = []
    for item in paths:
        normalized = item.replace("\\", "/")
        if normalized not in dedup:
            dedup.append(normalized)
    return dedup[:8]


def _source_symbols(path: Path, text: str) -> list[tuple[str, int]]:
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        return [
            (node.name, int(node.lineno))
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and not node.name.startswith("_")
        ]
    patterns = {
        ".js": r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)",
        ".mjs": r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)",
        ".cjs": r"^\s*(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)",
        ".ts": r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
        ".tsx": r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
        ".java": r"^\s*(?:public\s+)?(?:abstract\s+|final\s+)?(?:class|interface|enum|record)\s+([A-Za-z_$][\w$]*)",
    }
    pattern = patterns.get(path.suffix.lower())
    if not pattern:
        return []
    return [
        (match.group(1), line_number)
        for line_number, line in enumerate(text.splitlines(), start=1)
        if (match := re.search(pattern, line))
    ]


def _query_command(relative_path: str) -> str:
    escaped = relative_path.replace("'", "''")
    return (
        "rg -n '^(class|def|async def|export|public class|interface|type|enum|record)' "
        f"-- '{escaped}'"
    )


def build_precise_read_targets(
    repo_root: Path,
    read_paths: list[str],
) -> dict[str, list[dict[str, Any]]]:
    repo = Path(repo_root).resolve()
    must_read_targets: list[dict[str, Any]] = []
    inventory_targets: list[dict[str, Any]] = []
    unresolved_queries: list[dict[str, Any]] = []
    for raw in dict.fromkeys(read_paths):
        normalized = str(raw).replace("\\", "/").strip().strip("/")
        if not normalized:
            continue
        target = (repo / normalized).resolve()
        try:
            target.relative_to(repo)
        except ValueError:
            unresolved_queries.append(
                {
                    "path": normalized,
                    "command": f"Resolve repository-local path for '{normalized}'",
                    "reason": "required read resolves outside repository",
                }
            )
            continue
        if target.is_dir():
            inventory_targets.append(
                {
                    "path": normalized,
                    "reason": "inventory routed directory before selecting a file",
                }
            )
            continue
        if not target.is_file():
            must_read_targets.append(
                {
                    "path": normalized,
                    "symbol": None,
                    "content_digest": None,
                    "line_hint": None,
                    "reason": "routed required read",
                    "resolution_status": "unresolved",
                    "candidate_symbols": [],
                }
            )
            unresolved_queries.append(
                {
                    "path": normalized,
                    "command": f"rg --files | rg '{re.escape(normalized)}$'",
                    "reason": "required read path does not exist",
                }
            )
            continue
        content = target.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        symbols = _source_symbols(target, text)
        if len(symbols) == 1:
            symbol, line_hint = symbols[0]
            resolution_status = "resolved"
            candidates: list[str] = []
        elif target.suffix.lower() in DOCUMENT_SUFFIXES:
            symbol, line_hint = "$document", 1
            resolution_status = "resolved"
            candidates = []
        else:
            symbol, line_hint = None, None
            resolution_status = "unresolved"
            candidates = [name for name, _line in symbols]
            unresolved_queries.append(
                {
                    "path": normalized,
                    "command": _query_command(normalized),
                    "reason": "unique implementation symbol could not be proven",
                    "candidate_symbols": candidates,
                }
            )
        item: dict[str, Any] = {
            "path": normalized,
            "symbol": symbol,
            "content_digest": digest,
            "line_hint": line_hint,
            "reason": "routed required read",
            "resolution_status": resolution_status,
        }
        if resolution_status == "unresolved":
            item["candidate_symbols"] = candidates
        must_read_targets.append(item)
    return {
        "must_read_targets": must_read_targets,
        "inventory_targets": inventory_targets,
        "unresolved_queries": unresolved_queries,
    }
