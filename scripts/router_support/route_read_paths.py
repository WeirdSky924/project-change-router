from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, Callable, Optional

from router_support.route_constraints import glob_match


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
