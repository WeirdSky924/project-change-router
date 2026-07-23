from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any


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
