from __future__ import annotations

import dataclasses
import datetime as dt
import difflib
import fnmatch
import hashlib
import math
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from reuse_runtime import (
    FINGERPRINT_VERSION,
    ReuseRuntimePolicy,
    ReuseRuntimeStore,
    file_stat_key,
    iso_now as runtime_iso_now,
    token_sketch,
)
from router_support.import_graph import build_import_graph
from router_support.reuse_scope import resolve_reuse_scope


@dataclass
class ReuseScanBudget:
    max_candidate_files: int = 200
    max_owner_files_per_capability: int = 400
    max_comparisons: int = 5000
    max_file_bytes_for_full_similarity: int = 256_000
    max_normalized_chars_for_full_similarity: int = 180_000
    max_similarity_char_product: int = 120_000_000
    max_length_ratio: float = 8.0
    min_token_jaccard: float = 0.08
    min_path_token_overlap: float = 0.05
    min_fingerprint_advisory_score: float = 0.55
    top_k_owner_files_per_candidate: int = 40


@dataclass(frozen=True)
class ReuseScanEnvironment:
    normalize_rel_path: Callable[..., str]
    should_ignore_path: Callable[..., bool]
    iter_source_files: Callable[..., Iterable[Path]]
    source_files_for_modules: Callable[..., list[Path]]
    root_owner_fallback_modules: Callable[..., list[str]]
    derive_path_tokens: Callable[[str], list[str]]
    normalized_code: Callable[[str], str]
    text_tokens: Callable[[str], list[str]]
    code_suffixes: frozenset[str]
    generic_path_tokens: frozenset[str]


def reuse_scan_budget_from_bundle(
    bundle: dict[str, Any],
    overrides: Optional[dict[str, Any]] = None,
) -> tuple[ReuseScanBudget, tuple[str, ...]]:
    configured = dict(bundle.get("change_rules", {}).get("reuse_scan_budget", {}))
    configured.update(overrides or {})
    if "max_owner_files" in configured and "max_owner_files_per_capability" not in configured:
        configured["max_owner_files_per_capability"] = configured["max_owner_files"]
    if "max_file_bytes" in configured and "max_file_bytes_for_full_similarity" not in configured:
        configured["max_file_bytes_for_full_similarity"] = configured["max_file_bytes"]
    values: dict[str, Any] = {}
    errors: list[str] = []
    float_fields = {
        "max_length_ratio",
        "min_token_jaccard",
        "min_path_token_overlap",
        "min_fingerprint_advisory_score",
    }
    for field_info in dataclasses.fields(ReuseScanBudget):
        raw = configured.get(field_info.name, field_info.default)
        if field_info.name in float_fields:
            valid = not isinstance(raw, bool) and isinstance(raw, (int, float))
            value = float(raw) if valid else float(field_info.default)
            valid = valid and math.isfinite(value)
        else:
            valid = type(raw) is int and raw >= 0
            value = raw if valid else field_info.default
        if not valid:
            errors.append(f"invalid_type_or_range:{field_info.name}")
            values[field_info.name] = field_info.default
        else:
            values[field_info.name] = value
    budget = ReuseScanBudget(**values)
    if budget.max_length_ratio < ReuseScanBudget.max_length_ratio:
        errors.append("unsafe_prefilter:max_length_ratio")
    if not 0 <= budget.min_token_jaccard <= ReuseScanBudget.min_token_jaccard:
        errors.append("unsafe_prefilter:min_token_jaccard")
    if not 0 <= budget.min_path_token_overlap <= ReuseScanBudget.min_path_token_overlap:
        errors.append("unsafe_prefilter:min_path_token_overlap")
    if not 0 <= budget.min_fingerprint_advisory_score <= 1:
        errors.append("invalid_range:min_fingerprint_advisory_score")
    return budget, tuple(dict.fromkeys(errors))


def unique_paths(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    paths: Iterable[Path],
) -> list[Path]:
    seen: set[str] = set()
    ordered: list[Path] = []
    for path in paths:
        rel = environment.normalize_rel_path(repo_root, path)
        if rel in seen:
            continue
        seen.add(rel)
        ordered.append(path)
    return ordered


def collect_code_files_from_surface(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    target: Path,
    ignore_patterns: Iterable[str],
) -> list[Path]:
    if not target.exists() or environment.should_ignore_path(target, ignore_patterns, repo_root):
        return []
    if target.is_file():
        return [target] if target.suffix.lower() in environment.code_suffixes else []
    files = [
        file
        for file in environment.iter_source_files(target, ignore_patterns)
        if file.suffix.lower() in environment.code_suffixes
        and not environment.should_ignore_path(file, ignore_patterns, repo_root)
    ]
    return unique_paths(environment, repo_root, files)


def changed_path_candidate_files(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    changed_paths: list[str],
    ignore_patterns: Iterable[str],
) -> list[Path]:
    candidates: list[Path] = []
    for item in changed_paths:
        normalized = item.replace("\\", "/").strip()
        if not normalized:
            continue
        if any(char in normalized for char in "*?["):
            for target in repo_root.glob(normalized.lstrip("/")):
                candidates.extend(
                    collect_code_files_from_surface(
                        environment, repo_root, target, ignore_patterns
                    )
                )
            continue
        raw_path = Path(item)
        target = raw_path if raw_path.is_absolute() else repo_root / normalized
        candidates.extend(
            collect_code_files_from_surface(environment, repo_root, target, ignore_patterns)
        )
    return unique_paths(environment, repo_root, candidates)


def _field(value: Any, name: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _path_pattern(surface: object) -> str:
    normalized = str(surface or "").replace("\\", "/").strip("/")
    if not normalized or any(char in normalized for char in "*?["):
        return normalized
    if Path(normalized).suffix:
        return normalized
    return f"{normalized}/**"


def _paths_from_test_bindings(bindings: Iterable[Mapping[str, Any]]) -> list[str]:
    path_keys = {
        "path",
        "paths",
        "pattern",
        "patterns",
        "test",
        "tests",
        "test_path",
        "test_paths",
        "source_path",
        "source_paths",
    }
    paths: list[str] = []
    for binding in bindings:
        for key, value in binding.items():
            if key not in path_keys:
                continue
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, list):
                paths.extend(str(item) for item in value if isinstance(item, (str, Path)))
    return list(dict.fromkeys(path.replace("\\", "/") for path in paths if path))


def _capability_surfaces(capability: Any) -> list[str]:
    scope = _field(capability, "scope", {})
    values = [
        *_field(capability, "owner_modules", []),
        *scope.get("paths", []),
        *_field(capability, "public_entries", []),
        *_field(capability, "related_tests", []),
        *_paths_from_test_bindings(_field(capability, "test_bindings", [])),
    ]
    return [str(value) for value in values if str(value).strip()]


def _capability_path_mappings(
    bundle: dict[str, Any], capabilities: list[Any]
) -> list[dict[str, Any]]:
    mappings = [
        dict(entry)
        for entry in bundle.get("path_to_capability_map", {}).get("path_index", [])
        if isinstance(entry, Mapping)
    ]
    for capability in capabilities:
        capability_id = str(_field(capability, "id", ""))
        for surface in _capability_surfaces(capability):
            pattern = _path_pattern(surface)
            if pattern:
                mappings.append(
                    {"path_pattern": pattern, "capabilities": [capability_id]}
                )
    return mappings


def _module_owner_mappings(modules: list[Any], capabilities: list[Any]) -> list[dict[str, Any]]:
    capabilities_by_module: dict[str, set[str]] = {}
    for capability in capabilities:
        capability_id = str(_field(capability, "id", ""))
        for owner in _field(capability, "owner_modules", []):
            capabilities_by_module.setdefault(str(owner), set()).add(capability_id)
    mappings: list[dict[str, Any]] = []
    for module in modules:
        module_path = str(_field(module, "path", ""))
        capability_ids = sorted(capabilities_by_module.get(module_path, set()))
        if not capability_ids:
            continue
        surfaces = [
            module_path,
            *_field(module, "key_files", []),
            *_field(module, "index_sources", []),
        ]
        for surface in surfaces:
            pattern = _path_pattern(surface)
            if pattern:
                mappings.append(
                    {"path_pattern": pattern, "capabilities": capability_ids}
                )
    return mappings


def _module_for_source_path(path: str, modules: list[Any]) -> Any | None:
    normalized = path.replace("\\", "/").strip("/")
    matches = []
    root_module = None
    for module in modules:
        module_path = str(_field(module, "path", "")).replace("\\", "/").strip("/")
        if module_path in {"", "."}:
            root_module = module
        elif normalized == module_path or normalized.startswith(module_path + "/"):
            matches.append((len(module_path), module))
    return max(matches, key=lambda item: item[0])[1] if matches else root_module


def _runtime_capability_edges(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    modules: list[Any],
    capabilities: list[Any],
    ignore_patterns: Iterable[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_files = environment.source_files_for_modules(repo_root, modules, ignore_patterns)
    snapshot = build_import_graph(
        repo_root,
        source_files,
        resolution_paths=source_files,
    )
    capability_ids_by_module: dict[str, set[str]] = {}
    for capability in capabilities:
        capability_id = str(_field(capability, "id", ""))
        for owner in _field(capability, "owner_modules", []):
            capability_ids_by_module.setdefault(str(owner), set()).add(capability_id)
    edges: set[tuple[str, str, bool]] = set()
    for edge in snapshot.edges:
        source_module = _module_for_source_path(edge.source, modules)
        target_module = _module_for_source_path(edge.target, modules)
        if source_module is None or target_module is None or source_module is target_module:
            continue
        source_ids = capability_ids_by_module.get(str(_field(source_module, "path", "")), set())
        target_ids = capability_ids_by_module.get(str(_field(target_module, "path", "")), set())
        for source_id in source_ids:
            for target_id in target_ids:
                if source_id != target_id:
                    edges.add((source_id, target_id, bool(edge.runtime)))
    diagnostics = [dataclasses.asdict(diagnostic) for diagnostic in snapshot.diagnostics]
    return (
        [
            {"source": source, "target": target, "runtime": runtime}
            for source, target, runtime in sorted(edges)
        ],
        diagnostics,
    )


def build_reuse_scope(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    bundle: dict[str, Any],
    capabilities: list[Any],
    modules: list[Any],
    candidate_files: list[Path],
    changed_paths: Optional[list[str]],
    ignore_patterns: Iterable[str],
) -> dict[str, Any]:
    if not changed_paths:
        capability_ids = [str(_field(capability, "id", "")) for capability in capabilities]
        has_candidate_evidence = bool(candidate_files)
        return {
            "mode": "full_scan",
            "status": "resolved" if has_candidate_evidence else "unresolved",
            "completion_status": "complete" if has_candidate_evidence else "incomplete",
            "evidence_complete": has_candidate_evidence,
            "capability_ids": capability_ids,
            "direct_capability_ids": capability_ids,
            "dependency_capability_ids": [],
            "unresolved_paths": [],
            "sources": {
                capability_id: ["explicit_full_scan"] for capability_id in capability_ids
            },
            "ignored_broad_mappings": [],
            "diagnostics": []
            if has_candidate_evidence
            else [
                {
                    "code": "no-candidate-source",
                    "path": "",
                    "message": "explicit full scan found no readable source candidates",
                }
            ],
        }

    normalized_paths: list[str] = []
    for raw in changed_paths:
        raw_path = Path(raw)
        if raw_path.is_absolute():
            normalized_paths.append(environment.normalize_rel_path(repo_root, raw_path))
        else:
            normalized = raw.replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            normalized_paths.append(normalized.lstrip("/"))
    runtime_edges, diagnostics = _runtime_capability_edges(
        environment,
        repo_root,
        modules,
        capabilities,
        ignore_patterns,
    )
    if not candidate_files:
        diagnostics.append(
            {
                "code": "no-candidate-source",
                "path": ",".join(normalized_paths),
                "message": "changed paths resolved to no readable source candidates",
            }
        )
    result = resolve_reuse_scope(
        changed_paths=normalized_paths,
        path_mappings=_capability_path_mappings(bundle, capabilities),
        module_owners=_module_owner_mappings(modules, capabilities),
        runtime_edges=runtime_edges,
        diagnostics=diagnostics,
        include_dependency_neighbors=bool(
            bundle.get("change_rules", {})
            .get("reuse_scan_scope", {})
            .get("include_dependency_neighbors", True)
        ),
    )
    payload = result.to_dict()
    known_capabilities = {
        str(_field(capability, "id", "")) for capability in capabilities
    }
    unknown_capabilities = sorted(
        set(payload["capability_ids"]) - known_capabilities
    )
    if unknown_capabilities:
        payload["diagnostics"].append(
            {
                "code": "unknown-scope-capability",
                "capabilities": unknown_capabilities,
                "message": "reuse scope references capability IDs absent from the catalog",
            }
        )
        for key in (
            "capability_ids",
            "direct_capability_ids",
            "dependency_capability_ids",
        ):
            payload[key] = [
                capability_id
                for capability_id in payload[key]
                if capability_id in known_capabilities
            ]
        payload["sources"] = {
            capability_id: sources
            for capability_id, sources in payload["sources"].items()
            if capability_id in known_capabilities
        }
        payload["status"] = (
            "partial" if payload["direct_capability_ids"] else "unresolved"
        )
        if not payload["direct_capability_ids"]:
            payload["unresolved_paths"] = sorted(
                set(payload["unresolved_paths"]) | set(normalized_paths)
            )
        payload["completion_status"] = "incomplete"
        payload["evidence_complete"] = False
    payload["ignored_broad_mappings"] = [
        {key: value for key, value in item.items() if key != "source"}
        for item in payload["ignored_broad_mappings"]
    ]
    return payload


def capability_owner_files(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    capability: Any,
    modules: list[Any],
    ignore_patterns: Iterable[str],
) -> list[Path]:
    module_by_path = {str(_field(module, "path", "")): module for module in modules}
    owner_paths: list[str] = []
    for owner in _field(capability, "owner_modules", []):
        if owner == ".":
            fallback_modules = environment.root_owner_fallback_modules(capability, modules)
            if fallback_modules:
                owner_paths.extend(fallback_modules)
                continue
        owner_paths.append(owner)

    files: list[Path] = []
    for owner in owner_paths:
        if any(char in owner for char in "*?["):
            for target in repo_root.glob(owner.replace("\\", "/").lstrip("/")):
                files.extend(
                    collect_code_files_from_surface(
                        environment, repo_root, target, ignore_patterns
                    )
                )
            continue
        module = module_by_path.get(owner)
        target = (
            repo_root / str(_field(module, "path", ""))
            if module and _field(module, "path", "") != "."
            else repo_root
            if module
            else repo_root / owner
        )
        files.extend(
            collect_code_files_from_surface(environment, repo_root, target, ignore_patterns)
        )
    return unique_paths(environment, repo_root, files)


def collect_surface_files(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    surfaces: Iterable[str],
    ignore_patterns: Iterable[str],
) -> list[Path]:
    files: list[Path] = []
    for surface in surfaces:
        normalized = str(surface).replace("\\", "/").strip()
        if not normalized:
            continue
        if any(char in normalized for char in "*?["):
            for target in repo_root.glob(normalized.lstrip("/")):
                files.extend(
                    collect_code_files_from_surface(
                        environment, repo_root, target, ignore_patterns
                    )
                )
        else:
            target = Path(normalized)
            if not target.is_absolute():
                target = repo_root / normalized
            files.extend(
                collect_code_files_from_surface(
                    environment, repo_root, target, ignore_patterns
                )
            )
    return unique_paths(environment, repo_root, files)


def is_test_file(path: Path) -> bool:
    normalized = path.as_posix().lower()
    name = path.name.lower()
    return (
        any(segment in {"test", "tests", "__tests__"} for segment in normalized.split("/"))
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def capability_comparison_files(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    capability: Any,
    modules: list[Any],
    ignore_patterns: Iterable[str],
    candidate_files: list[Path],
) -> list[Path]:
    owner_files = capability_owner_files(
        environment, repo_root, capability, modules, ignore_patterns
    )
    if not any(is_test_file(candidate) for candidate in candidate_files):
        return owner_files
    module_by_path = {str(_field(module, "path", "")): module for module in modules}
    test_surfaces = list(_field(capability, "related_tests", []))
    test_surfaces += _paths_from_test_bindings(_field(capability, "test_bindings", []))
    for owner in _field(capability, "owner_modules", []):
        module = module_by_path.get(owner)
        if module:
            test_surfaces.extend(_field(module, "key_files", []))
            test_surfaces.extend(_field(module, "index_sources", []))
    test_files = [
        path
        for path in collect_surface_files(
            environment, repo_root, test_surfaces, ignore_patterns
        )
        if is_test_file(path)
    ]
    return unique_paths(environment, repo_root, [*test_files, *owner_files])
