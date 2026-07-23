from __future__ import annotations

import datetime as dt
import fnmatch
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from router_support.repository_surfaces import (
    files_for_standard_repository_surface,
    standard_repository_surface_kind,
)


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _explicit_ownership(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in profile.get("capability_ownership", []):
        if isinstance(item, dict) and item.get("target"):
            records[str(item["target"])].append(item)
    return records


def _reviewers(record: dict[str, Any]) -> list[str]:
    configured = record.get("reviewers", [])
    if not isinstance(configured, list):
        return []
    return [
        reviewer
        for reviewer in configured
        if isinstance(reviewer, str) and reviewer.strip()
    ]


def _identity_or_unknown(value: object) -> str:
    return value if isinstance(value, str) and value.strip() else "UNKNOWN"


def _owner_is_provisional(primary: str, explicit: dict[str, Any]) -> bool:
    normalized = primary.strip().lower()
    return bool(explicit.get("provisional", False)) or (
        normalized in {"", "unknown", "unassigned", "none"}
        or normalized.startswith("provisional:")
    )


def codeowners_candidates(repo_root: Path) -> tuple[Path, ...]:
    return (
        repo_root / ".github" / "CODEOWNERS",
        repo_root / ".gitlab" / "CODEOWNERS",
        repo_root / "CODEOWNERS",
    )


def load_codeowners(repo_root: Path) -> list[tuple[str, list[str]]]:
    for path in codeowners_candidates(repo_root):
        if not path.exists():
            continue
        rules: list[tuple[str, list[str]]] = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) >= 2:
                rules.append((parts[0], parts[1:]))
        return rules
    return []


def codeowner_for_path(
    rel_path: str,
    rules: list[tuple[str, list[str]]],
) -> str | None:
    winner: str | None = None
    normalized = rel_path.replace("\\", "/")
    for pattern, owners in rules:
        normalized_pattern = pattern.lstrip("/").replace("\\", "/")
        if normalized_pattern.endswith("/"):
            normalized_pattern += "*"
        if fnmatch.fnmatchcase(
            normalized,
            normalized_pattern,
        ) or fnmatch.fnmatchcase("/" + normalized, pattern.replace("\\", "/")):
            if owners:
                winner = ",".join(owners)
    return winner


def codeowner_for_module(
    repo_root: Path,
    module: Any,
    rules: list[tuple[str, list[str]]],
    is_ignored: Callable[[Path], bool],
) -> str | None:
    if standard_repository_surface_kind(module.path) == "directory":
        surface_files = files_for_standard_repository_surface(
            repo_root,
            module.path,
            is_ignored,
        )
        if not surface_files:
            return None
        owners = [
            codeowner_for_path(path.relative_to(repo_root).as_posix(), rules)
            for path in surface_files
        ]
        if all(owners) and len(set(owners)) == 1:
            return owners[0]
        return None
    return codeowner_for_path(module.path if module.path != "." else "", rules)


def build_ownership(
    capabilities: list[Any],
    modules: list[Any],
    repo_stage: str,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    explicit_by_target = _explicit_ownership(profile or {})
    owners: list[dict[str, Any]] = []
    for capability in capabilities:
        primary = modules[0].owner if modules else "unassigned"
        for module in modules:
            if module.path in capability.owner_modules:
                primary = module.owner
                break
        explicit_records = explicit_by_target.get(capability.id, [])
        explicit = explicit_records[0] if len(explicit_records) == 1 else None
        reviewers: list[str] = []
        escalation_group = primary
        provisional = True
        if explicit is not None:
            primary = _identity_or_unknown(explicit.get("primary"))
            reviewers = _reviewers(explicit)
            escalation_group = _identity_or_unknown(
                explicit.get("escalation_group")
                or (reviewers[0] if reviewers else primary)
            )
            provisional = _owner_is_provisional(primary, explicit)
        owners.append(
            {
                "scope": "capability",
                "target": capability.id,
                "primary": primary,
                "reviewers": reviewers,
                "escalation_group": escalation_group,
                "provisional": provisional,
            }
        )

    stable_module_owners: dict[str, list[str]] = defaultdict(list)
    for capability in capabilities:
        if capability.status == "stable" or capability.stage in {
            "stable",
            "governed-capability",
        }:
            for module_path in capability.owner_modules:
                stable_module_owners[module_path].append(capability.id)
    for module in modules:
        stable_claims = sorted(set(stable_module_owners.get(module.path, [])))
        primary = module.owner
        reviewers: list[str] = []
        provisional = (
            repo_stage in {"seed", "emerging"}
            or primary in {"unassigned", "UNKNOWN"}
            or str(primary).startswith("provisional:")
        )
        if len(stable_claims) == 1:
            explicit_records = explicit_by_target.get(stable_claims[0], [])
            explicit = explicit_records[0] if len(explicit_records) == 1 else None
            if explicit is not None and explicit.get("primary") == primary:
                reviewers = _reviewers(explicit)
                provisional = _owner_is_provisional(str(primary), explicit)
        owners.append(
            {
                "scope": "module",
                "target": module.path,
                "primary": primary,
                "reviewers": reviewers,
                "escalation_group": reviewers[0] if reviewers else primary,
                "provisional": provisional,
            }
        )
    return {
        "schema_version": 1,
        "generated_at": _iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "owners": owners,
    }


def capability_conflicts(bundle: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    owner_to_capabilities: dict[str, list[str]] = defaultdict(list)
    public_entry_to_capabilities: dict[str, list[str]] = defaultdict(list)
    capabilities = bundle.get("capability_catalog", {}).get("capabilities", [])
    capability_records = [
        item for item in capabilities if isinstance(item, dict) and item.get("id")
    ]
    for capability in capability_records:
        capability_id = str(capability["id"])
        for owner in capability.get("owner_modules", []):
            owner_to_capabilities[str(owner)].append(capability_id)
        for entry in capability.get("public_entries", []):
            public_entry_to_capabilities[str(entry)].append(capability_id)
    for owner, capability_ids in owner_to_capabilities.items():
        unique = sorted(set(capability_ids))
        if len(unique) > 1:
            conflicts.append(
                f"module {owner} is owned by multiple capabilities: {', '.join(unique)}"
            )
    for entry, capability_ids in public_entry_to_capabilities.items():
        unique = sorted(set(capability_ids))
        if len(unique) > 1:
            conflicts.append(
                f"public entry {entry} is claimed by multiple capabilities: "
                f"{', '.join(unique)}"
            )

    ownership_records = bundle.get("ownership", {}).get("owners", [])
    capability_owners = {
        str(item.get("target")): str(item.get("primary"))
        for item in ownership_records
        if isinstance(item, dict)
        and item.get("scope") == "capability"
        and item.get("target")
        and item.get("primary")
    }
    module_owners = {
        str(item.get("target")): str(item.get("primary"))
        for item in ownership_records
        if isinstance(item, dict)
        and item.get("scope") == "module"
        and item.get("target")
        and item.get("primary")
    }
    for capability in capability_records:
        capability_id = str(capability["id"])
        capability_owner = capability_owners.get(capability_id)
        if not capability_owner:
            continue
        for module_path in capability.get("owner_modules", []):
            module_path = str(module_path)
            module_owner = module_owners.get(module_path)
            if module_owner and module_owner != capability_owner:
                conflicts.append(
                    f"capability {capability_id} owner {capability_owner} conflicts "
                    f"with module {module_path} owner {module_owner}"
                )
    return conflicts
