from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


_WILDCARD = re.compile(r"[*?\[]")
_REPOSITORY_WIDE_PATTERNS = {"", ".", "*", "**", "**/*"}


@dataclass(frozen=True)
class RuntimeDependencyEdge:
    source: str
    target: str
    runtime: bool = True


@dataclass(frozen=True)
class ReuseScopeResolution:
    mode: str
    status: str
    completion_status: str
    evidence_complete: bool
    capability_ids: tuple[str, ...]
    direct_capability_ids: tuple[str, ...]
    dependency_capability_ids: tuple[str, ...]
    unresolved_paths: tuple[str, ...]
    sources: Mapping[str, tuple[str, ...]]
    ignored_broad_mappings: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[Mapping[str, Any] | str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "completion_status": self.completion_status,
            "evidence_complete": self.evidence_complete,
            "capability_ids": list(self.capability_ids),
            "direct_capability_ids": list(self.direct_capability_ids),
            "dependency_capability_ids": list(self.dependency_capability_ids),
            "unresolved_paths": list(self.unresolved_paths),
            "sources": {key: list(value) for key, value in self.sources.items()},
            "ignored_broad_mappings": [dict(value) for value in self.ignored_broad_mappings],
            "diagnostics": [dict(value) if isinstance(value, Mapping) else value for value in self.diagnostics],
        }


def _normalized_path(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def _pattern(entry: Mapping[str, Any]) -> str:
    return _normalized_path(
        entry.get("path_pattern", entry.get("pattern", entry.get("path", "")))
    )


def _capabilities(entry: Mapping[str, Any]) -> tuple[str, ...]:
    raw = entry.get("capabilities", entry.get("capability_ids", ()))
    if isinstance(raw, str):
        raw = (raw,)
    if not isinstance(raw, Iterable) or isinstance(raw, Mapping):
        return ()
    return tuple(sorted({str(value).strip() for value in raw if str(value).strip()}))


def _repository_wide(pattern: str) -> bool:
    return pattern in _REPOSITORY_WIDE_PATTERNS


def _matches(pattern: str, path: str) -> bool:
    if _repository_wide(pattern):
        return True
    if pattern.endswith("/**"):
        root = pattern[:-3].rstrip("/")
        if path == root or path.startswith(root + "/"):
            return True
    return fnmatch.fnmatchcase(path, pattern)


def _specificity(pattern: str) -> int:
    return len(_WILDCARD.sub("", pattern))


def _ignored_record(
    path: str,
    entry: Mapping[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "path_pattern": _pattern(entry),
        "capabilities": list(_capabilities(entry)),
        "source": source,
    }


def _explicit_exact_shared_owner(entry: Mapping[str, Any], path: str) -> bool:
    pattern = _pattern(entry)
    relationship = str(entry.get("relationship", "")).strip().lower()
    shared = bool(entry.get("shared_owner", entry.get("shared", False))) or relationship in {
        "shared",
        "exact-shared",
        "exact_shared",
    }
    return shared and not _WILDCARD.search(pattern) and pattern == path


def _select_mappings(
    path: str,
    entries: Iterable[Mapping[str, Any]],
    source: str,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[dict[str, Any], ...]]:
    candidates: list[tuple[int, bool, Mapping[str, Any]]] = []
    ignored: list[dict[str, Any]] = []
    for entry in entries:
        pattern = _pattern(entry)
        if not _capabilities(entry) or not _matches(pattern, path):
            continue
        if _repository_wide(pattern):
            ignored.append(_ignored_record(path, entry, source))
            continue
        exact = not _WILDCARD.search(pattern) and pattern == path
        candidates.append((_specificity(pattern), exact, entry))
    if not candidates:
        return (), tuple(ignored)
    exact_candidates = [item for item in candidates if item[1]]
    selected_pool = exact_candidates or candidates
    selected_score = max(item[0] for item in selected_pool)
    selected = tuple(item[2] for item in selected_pool if item[0] == selected_score)
    selected_ids = {id(entry) for entry in selected}
    ignored.extend(
        _ignored_record(path, entry, source)
        for _, _, entry in candidates
        if id(entry) not in selected_ids
    )
    return selected, tuple(ignored)


def _runtime_edge(value: RuntimeDependencyEdge | Mapping[str, Any]) -> RuntimeDependencyEdge | None:
    if isinstance(value, RuntimeDependencyEdge):
        return value
    source = str(value.get("source", value.get("source_capability", ""))).strip()
    target = str(value.get("target", value.get("target_capability", ""))).strip()
    if not source or not target:
        return None
    raw_runtime = value.get("runtime")
    if raw_runtime is None:
        runtime = not bool(value.get("type_only", False))
    elif isinstance(raw_runtime, str):
        runtime = raw_runtime.strip().lower() not in {"false", "no", "off", "0"}
    else:
        runtime = bool(raw_runtime)
    return RuntimeDependencyEdge(source, target, runtime)


def _normalized_diagnostics(
    diagnostics: Iterable[Mapping[str, Any] | str],
) -> tuple[Mapping[str, Any] | str, ...]:
    values: list[Mapping[str, Any] | str] = []
    for diagnostic in diagnostics:
        values.append(dict(diagnostic) if isinstance(diagnostic, Mapping) else str(diagnostic))
    return tuple(values)


def resolve_reuse_scope(
    *,
    changed_paths: Iterable[str],
    path_mappings: Iterable[Mapping[str, Any]],
    module_owners: Iterable[Mapping[str, Any]] = (),
    runtime_edges: Iterable[RuntimeDependencyEdge | Mapping[str, Any]] = (),
    diagnostics: Iterable[Mapping[str, Any] | str] = (),
    include_dependency_neighbors: bool = True,
) -> ReuseScopeResolution:
    """Resolve a bounded changed-path scope without importing router internals.

    Exact path-index ownership is authoritative. Module-owner surfaces are used
    only when no path-index owner resolves a path, and repository-wide fallback
    patterns never turn an unknown path into an implicit full-repository scan.
    """

    normalized_paths = tuple(
        sorted({_normalized_path(path) for path in changed_paths if _normalized_path(path)})
    )
    path_entries = tuple(path_mappings)
    owner_entries = tuple(module_owners)
    source_evidence: dict[str, set[str]] = defaultdict(set)
    direct: set[str] = set()
    unresolved: list[str] = []
    ignored: list[dict[str, Any]] = []

    for path in normalized_paths:
        selected, skipped = _select_mappings(path, path_entries, "path_map")
        ignored.extend(skipped)
        if selected:
            selected_with_sources = [(entry, "path_map") for entry in selected]
            owner_matches, owner_skipped = _select_mappings(
                path, owner_entries, "module_owner"
            )
            ignored.extend(owner_skipped)
            for entry in owner_matches:
                if _explicit_exact_shared_owner(entry, path):
                    selected_with_sources.append((entry, "module_owner"))
                else:
                    ignored.append(_ignored_record(path, entry, "module_owner"))
        else:
            selected, skipped = _select_mappings(path, owner_entries, "module_owner")
            ignored.extend(skipped)
            selected_with_sources = [(entry, "module_owner") for entry in selected]
        selected_capabilities = {
            capability
            for entry, _ in selected_with_sources
            for capability in _capabilities(entry)
        }
        if not selected_capabilities:
            unresolved.append(path)
            continue
        direct.update(selected_capabilities)
        for entry, source_prefix in selected_with_sources:
            evidence = f"{source_prefix}:{_pattern(entry)}"
            for capability in _capabilities(entry):
                source_evidence[capability].add(evidence)

    dependencies: set[str] = set()
    if include_dependency_neighbors and direct:
        for raw_edge in runtime_edges:
            edge = _runtime_edge(raw_edge)
            if edge is None or not edge.runtime:
                continue
            if edge.source in direct and edge.target not in direct:
                dependencies.add(edge.target)
                source_evidence[edge.target].add(f"runtime_edge:{edge.source}->{edge.target}")
            if edge.target in direct and edge.source not in direct:
                dependencies.add(edge.source)
                source_evidence[edge.source].add(f"runtime_edge:{edge.source}->{edge.target}")

    normalized_diagnostics = _normalized_diagnostics(diagnostics)
    status = "resolved" if direct and not unresolved else "partial" if direct else "unresolved"
    evidence_complete = bool(normalized_paths) and status == "resolved" and not normalized_diagnostics
    completion_status = "complete" if evidence_complete else "incomplete"
    capability_ids = tuple(sorted(direct | dependencies))
    ignored.sort(
        key=lambda item: (
            item["path"],
            item["source"],
            item["path_pattern"],
            tuple(item["capabilities"]),
        )
    )
    return ReuseScopeResolution(
        mode="changed_paths",
        status=status,
        completion_status=completion_status,
        evidence_complete=evidence_complete,
        capability_ids=capability_ids,
        direct_capability_ids=tuple(sorted(direct)),
        dependency_capability_ids=tuple(sorted(dependencies)),
        unresolved_paths=tuple(sorted(unresolved)),
        sources={key: tuple(sorted(value)) for key, value in sorted(source_evidence.items())},
        ignored_broad_mappings=tuple(ignored),
        diagnostics=normalized_diagnostics,
    )
