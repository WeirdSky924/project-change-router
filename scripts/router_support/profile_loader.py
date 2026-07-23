from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml


CANONICAL_PROFILE_NAMES = (
    ".project-change-router.yaml",
    ".project-change-router.yml",
)
LEGACY_PROFILE_NAMES = (
    "project-change-router.profile.yaml",
    "project-change-router.profile.yml",
)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            merged = list(result[key])
            for item in value:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = value
    return result


def disambiguate_generated_capability_id(
    capability_id: str,
    reserved_ids: Iterable[str],
) -> str:
    reserved = set(reserved_ids)
    if capability_id not in reserved:
        return capability_id
    base = f"{capability_id}-unmapped"
    candidate = base
    ordinal = 2
    while candidate in reserved:
        candidate = f"{base}-{ordinal}"
        ordinal += 1
    return candidate


def _existing(repo_root: Path, names: tuple[str, ...]) -> list[Path]:
    return [repo_root / name for name in names if (repo_root / name).exists()]


def _skill_profile_candidates(repo_root: Path) -> list[Path]:
    profile_root = Path(__file__).resolve().parent.parent.parent / "profiles"
    if not profile_root.exists():
        return []
    return [
        path
        for path in (
            profile_root / f"{repo_root.name}.yaml",
            profile_root / f"{repo_root.name}.yml",
        )
        if path.exists()
    ]


def profile_candidates(repo_root: Path) -> list[Path]:
    """Return the highest-priority source set; multiple entries are a conflict."""

    canonical = _existing(repo_root, CANONICAL_PROFILE_NAMES)
    if canonical:
        return canonical
    legacy = _existing(repo_root, LEGACY_PROFILE_NAMES)
    if legacy:
        return legacy
    return _skill_profile_candidates(repo_root)


def load_active_profile(repo_root: Path) -> dict[str, Any]:
    candidates = profile_candidates(repo_root)
    if not candidates:
        return {}
    if len(candidates) != 1:
        sources = ", ".join(str(path) for path in candidates)
        raise ValueError(f"multiple active profile sources: {sources}")
    data = yaml.safe_load(candidates[0].read_text(encoding="utf-8"))
    return data or {}


def profile_source_lifecycle_findings(repo_root: Path) -> list[dict[str, Any]]:
    canonical = _existing(repo_root, CANONICAL_PROFILE_NAMES)
    legacy = _existing(repo_root, LEGACY_PROFILE_NAMES)
    findings: list[dict[str, Any]] = []
    if len(canonical) > 1:
        findings.append({
            "severity": "P0",
            "rule": "canonical-profile-source-conflict",
            "target": ".",
            "message": "Multiple canonical profiles define competing governance truth.",
            "recommendation": "Keep exactly one canonical profile source before routing or rebuilding.",
            "details": {
                "sources": [str(path.relative_to(repo_root)) for path in canonical],
            },
        })
        return findings
    if len(legacy) > 1 and not canonical:
        findings.append({
            "severity": "P0",
            "rule": "legacy-profile-source-conflict",
            "target": ".",
            "message": "Multiple legacy profiles define competing governance truth.",
            "recommendation": "Keep exactly one legacy fallback or migrate to one canonical profile.",
            "details": {
                "sources": [str(path.relative_to(repo_root)) for path in legacy],
            },
        })
        return findings
    if canonical and legacy:
        findings.append({
            "severity": "P1",
            "rule": "legacy-profile-lifecycle-debt",
            "target": str(legacy[0].relative_to(repo_root)),
            "message": "A legacy profile exists beside the canonical profile but is not an active source.",
            "recommendation": "Migrate parity, update callers, record rollback metadata, and retire the legacy profile.",
            "details": {
                "active_source": str(canonical[0].relative_to(repo_root)),
                "legacy_sources": [str(path.relative_to(repo_root)) for path in legacy],
            },
        })

    active_profile = (canonical or legacy)
    if not active_profile:
        return findings
    profile_path = active_profile[0]
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    target = str(profile_path.relative_to(repo_root))
    for capability in profile.get("capabilities", []):
        lifecycle = capability.get("lifecycle", {})
        if "implementation_state" not in lifecycle:
            continue
        implementation_state = lifecycle.get("implementation_state")
        if not isinstance(implementation_state, list):
            continue
        if lifecycle.get("replace_snapshot_boundaries") is True:
            continue
        findings.append(
            {
                "severity": "P1",
                "rule": "capability-lifecycle-list-merge-risk",
                "target": target,
                "message": (
                    "Capability implementation_state lists require exact snapshot "
                    "replacement to prevent stale generated lifecycle values."
                ),
                "recommendation": (
                    "Set lifecycle.replace_snapshot_boundaries: true after recording "
                    "the exact replacement lifecycle."
                ),
                "details": {
                    "capability": str(capability.get("id") or "UNKNOWN"),
                    "implementation_state": implementation_state,
                },
            }
        )
    return findings


def retired_profile_path_routes(profile: dict[str, Any]) -> list[tuple[str, str]]:
    routes: list[tuple[str, str]] = []
    for migration in profile.get("profile_lifecycle", {}).get("migrations", []):
        source = str(migration.get("source") or "").strip()
        capability = str(migration.get("route_capability") or "").strip()
        if migration.get("status") != "retired" or not source or not capability:
            continue
        route = (source.replace("\\", "/").strip("/"), capability)
        if route not in routes:
            routes.append(route)
    return routes
