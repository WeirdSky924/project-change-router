from __future__ import annotations

import fnmatch
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any


def _normalized_path(value: str) -> str:
    normalized = str(value).replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def scoped_owner_modules(
    owner_modules: Sequence[str],
    changed_paths: Sequence[str],
) -> list[str]:
    """Return only owner roots represented by an explicit change scope."""

    roots = [_normalized_path(root) for root in owner_modules]
    paths = [_normalized_path(path) for path in changed_paths]
    if not paths:
        return roots
    return [
        root
        for root in roots
        if any(path == root or path.startswith(root + "/") for path in paths)
    ]


def glob_match(patterns: Iterable[str], value: str) -> bool:
    normalized = _normalized_path(value)
    for pattern in patterns:
        normalized_pattern = _normalized_path(pattern)
        if fnmatch.fnmatchcase(normalized, normalized_pattern):
            return True
        if normalized_pattern.endswith("/**"):
            root = normalized_pattern[:-3].rstrip("/")
            if normalized == root or normalized.startswith(root + "/"):
                return True
    return False


def selected_test_binding_ids(
    bindings: Sequence[Mapping[str, Any]],
    action: str,
    changed_paths: Sequence[str],
    *,
    path_matches: Callable[[Sequence[str], str], bool],
) -> list[str]:
    """Select action and path-scoped test bindings without widening the route."""

    selected: list[str] = []
    for binding in bindings:
        if action not in binding.get("when_actions", []):
            continue
        patterns = list(binding.get("when_changed_paths", []))
        if changed_paths and patterns and not any(
            path_matches(patterns, path) for path in changed_paths
        ):
            continue
        binding_id = str(binding.get("id") or "")
        if binding_id:
            selected.append(binding_id)
    return list(dict.fromkeys(selected))


def required_checks_for(
    capability: Any,
    action: str,
    bundle: Mapping[str, Any],
    changed_paths: Sequence[str] | None = None,
) -> list[str]:
    del bundle
    checks = [
        "check-reuse",
        "check-deps",
        "check-public-api",
        "check-structure",
        "check-index-freshness",
    ]
    if capability:
        checks.extend(
            selected_test_binding_ids(
                capability.test_bindings,
                action,
                changed_paths or [],
                path_matches=glob_match,
            )
        )
    return list(dict.fromkeys(checks))


__all__ = ["glob_match", "required_checks_for", "scoped_owner_modules"]
