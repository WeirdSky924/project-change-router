from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


CHANNEL_NAMES = ("intra_capability", "cross_capability", "extended")


def _field(value: object, name: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _capability_id(value: object) -> str:
    return str(_field(value, "id", ""))


def _surfaces(value: object) -> set[str]:
    lifecycle = _field(value, "lifecycle", {}) or {}
    canonical = lifecycle.get("canonical_root", {}) if isinstance(lifecycle, Mapping) else {}
    canonical_path = canonical.get("path") if isinstance(canonical, Mapping) else None
    values = [
        *_field(value, "owner_modules", []),
        *_field(value, "public_entries", []),
        *([canonical_path] if canonical_path else []),
    ]
    return {
        str(item).replace("\\", "/").strip("/")
        for item in values
        if str(item).strip()
    }


def plan_reuse_channels(
    *,
    scope: Mapping[str, Any],
    capabilities: Iterable[object],
    action: str,
    lifecycle_intent: bool,
) -> dict[str, dict[str, Any]]:
    entries = list(capabilities)
    by_id = {
        _capability_id(item): item for item in entries if _capability_id(item)
    }
    direct = {
        str(item) for item in scope.get("direct_capability_ids", []) if str(item)
    }
    dependencies = {
        str(item)
        for item in scope.get("dependency_capability_ids", [])
        if str(item)
    }
    direct_surfaces = {
        surface
        for capability_id in direct
        for surface in _surfaces(by_id.get(capability_id, {}))
    }
    shared = {
        capability_id
        for capability_id, capability in by_id.items()
        if capability_id not in direct
        and direct_surfaces
        and _surfaces(capability) & direct_surfaces
    }
    cross = direct | dependencies | shared
    extended_required = action in {"new", "extract"} or lifecycle_intent
    extended = (set(by_id) - cross) if extended_required else set()
    scope_complete = scope.get("completion_status") == "complete"

    def channel(ids: set[str], *, required: bool) -> dict[str, Any]:
        return {
            "required": required,
            "capability_ids": sorted(ids),
            "completion_status": "planned" if required else "not_required",
            "evidence_complete": False if required else True,
            "finding_count": 0,
            "scope_complete": scope_complete,
        }

    return {
        "intra_capability": channel(direct, required=bool(direct)),
        "cross_capability": channel(cross, required=bool(cross)),
        "extended": channel(extended, required=extended_required and bool(extended)),
    }


def summarize_channel_coverage(
    channels: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    required = [
        channels[name]
        for name in CHANNEL_NAMES
        if name in channels and channels[name].get("completion_status") != "not_required"
    ]
    complete = bool(required) and all(
        item.get("completion_status") == "complete" for item in required
    )
    finding_count = sum(int(item.get("finding_count", 0)) for item in required)
    return {
        "evidence_complete": complete,
        "finding_count": finding_count,
        "duplicate_conclusion": (
            "found" if finding_count else "none_found" if complete else "not_proven"
        ),
        "required_channel_count": len(required),
        "complete_channel_count": sum(
            item.get("completion_status") == "complete" for item in required
        ),
    }


def comparison_channels(
    *,
    owner_capability_id: str,
    candidate_capability_ids: Iterable[str],
    channels: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    candidate_ids = {str(value) for value in candidate_capability_ids if value}
    result: list[str] = []
    if (
        owner_capability_id in candidate_ids
        and channels.get("intra_capability", {}).get("required")
    ):
        result.append("intra_capability")
    if (
        any(value != owner_capability_id for value in candidate_ids)
        and owner_capability_id
        in channels.get("cross_capability", {}).get("capability_ids", [])
    ):
        result.append("cross_capability")
    if owner_capability_id in channels.get("extended", {}).get(
        "capability_ids", []
    ):
        result.append("extended")
    return result
