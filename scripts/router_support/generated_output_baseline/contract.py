from __future__ import annotations

import copy
import datetime as dt
import math
from collections.abc import Mapping, Sequence, Set
from pathlib import Path
from typing import Any


GENERATOR_CLOCK_EVENTS = frozenset({
    "curated_bundle_lifecycle_calibrated",
    "generated_from_repository_structure",
})


def _normalize_path_map_file_counts(
    expected: dict[str, Any],
    actual: Mapping[str, Any],
) -> None:
    expected_index = expected.get("path_index", [])
    actual_index = actual.get("path_index", [])
    if not isinstance(expected_index, list) or not isinstance(actual_index, list):
        return
    actual_by_pattern: dict[str, Mapping[str, Any]] = {}
    for item in actual_index:
        if not isinstance(item, Mapping) or not isinstance(item.get("path_pattern"), str):
            continue
        pattern = str(item["path_pattern"])
        if pattern in actual_by_pattern:
            return
        actual_by_pattern[pattern] = item
    for item in expected_index:
        if not isinstance(item, dict) or not isinstance(item.get("path_pattern"), str):
            continue
        actual_item = actual_by_pattern.get(str(item["path_pattern"]))
        expected_count = item.get("code_file_count")
        actual_count = (
            actual_item.get("code_file_count")
            if isinstance(actual_item, Mapping)
            else None
        )
        if (
            isinstance(expected_count, int)
            and not isinstance(expected_count, bool)
            and expected_count >= 0
            and isinstance(actual_count, int)
            and not isinstance(actual_count, bool)
            and actual_count >= 0
        ):
            item["code_file_count"] = actual_count


def expected_artifact_source_commit(
    payload: Mapping[str, Any],
) -> str | None:
    if "source_commit" not in payload:
        raise ValueError("generated artifact omits source_commit")
    value = payload["source_commit"]
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("generated artifact source_commit must be a string or null")
    return value


def normalize_rebuild_volatiles(
    expected: dict[str, Any],
    actual: Mapping[str, Any],
    *,
    bundle_key: str,
) -> None:
    if "generated_at" in expected and "generated_at" in actual:
        expected["generated_at"] = actual["generated_at"]
    if bundle_key == "path_to_capability_map":
        _normalize_path_map_file_counts(expected, actual)
        return
    if bundle_key != "capability_catalog":
        return
    actual_capabilities = {
        str(item.get("id")): item
        for item in actual.get("capabilities", [])
        if isinstance(item, Mapping) and item.get("id")
    } if isinstance(actual.get("capabilities", []), list) else {}
    expected_capabilities = expected.get("capabilities", [])
    if not isinstance(expected_capabilities, list):
        return
    for item in expected_capabilities:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        actual_item = actual_capabilities.get(str(item["id"]))
        if not isinstance(actual_item, Mapping):
            continue
        if "last_verified_at" in item and "last_verified_at" in actual_item:
            item["last_verified_at"] = actual_item["last_verified_at"]
        expected_lifecycle = item.get("lifecycle")
        actual_lifecycle = actual_item.get("lifecycle")
        if not isinstance(expected_lifecycle, Mapping) or not isinstance(
            actual_lifecycle, Mapping
        ):
            continue
        expected_log = expected_lifecycle.get("changelog", [])
        actual_log = actual_lifecycle.get("changelog", [])
        if not isinstance(expected_log, list) or not isinstance(actual_log, list):
            continue
        for expected_entry, actual_entry in zip(expected_log, actual_log):
            if not isinstance(expected_entry, dict) or not isinstance(
                actual_entry, Mapping
            ):
                continue
            event = expected_entry.get("event")
            if event in GENERATOR_CLOCK_EVENTS and event == actual_entry.get("event"):
                expected_entry["date"] = actual_entry.get("date")


def projected_artifact_payload(
    payload: Mapping[str, Any],
    *,
    bundle_key: str | None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(payload))
    projected.pop("generated_at", None)
    projected.pop("source_commit", None)
    if bundle_key != "capability_catalog":
        return projected
    capabilities = projected.get("capabilities", [])
    if not isinstance(capabilities, list):
        return projected
    for item in capabilities:
        if not isinstance(item, dict):
            continue
        item.pop("last_verified_at", None)
        lifecycle = item.get("lifecycle")
        if not isinstance(lifecycle, Mapping):
            continue
        changelog = lifecycle.get("changelog", [])
        if not isinstance(changelog, list):
            continue
        for entry in changelog:
            if isinstance(entry, dict) and entry.get("event") in GENERATOR_CLOCK_EVENTS:
                entry.pop("date", None)
    return projected


def _diagnostic_key(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dt.date, dt.datetime)):
        return f"<{type(value).__name__}:{value.isoformat()}>"
    return f"<{type(value).__name__}:{value!r}>"


def sorted_diagnostic_keys(values: Sequence[object] | Set[object]) -> list[str]:
    return sorted((_diagnostic_key(value) for value in values))


def json_safe_diagnostic(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {
            "type": "float",
            "value": repr(value),
        }
    if isinstance(value, (dt.date, dt.datetime)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, Path):
        return {"type": "path", "value": str(value)}
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: _diagnostic_key(pair[0])):
            normalized = _diagnostic_key(key)
            if normalized in result:
                suffix = 2
                while f"{normalized}#{suffix}" in result:
                    suffix += 1
                normalized = f"{normalized}#{suffix}"
            result[normalized] = json_safe_diagnostic(item)
        return result
    if isinstance(value, Set):
        return [
            json_safe_diagnostic(item)
            for item in sorted(value, key=_diagnostic_key)
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe_diagnostic(item) for item in value]
    return {"type": type(value).__name__, "value": repr(value)}
