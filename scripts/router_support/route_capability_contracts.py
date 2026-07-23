from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


def ordered_secondary_capabilities(
    *,
    primary_capability: str | None,
    changed_paths: Sequence[str],
    scored_capabilities: Mapping[str, float],
    guarded_threshold: float,
    dependency_priority: Mapping[str, int],
    path_capabilities: Callable[[str], Sequence[str]],
) -> list[str]:
    """Return exact path owners, falling back to scores only without path evidence."""
    if changed_paths:
        candidates = {
            capability
            for path in changed_paths
            for capability in path_capabilities(path)
            if capability and capability != primary_capability
        }
        return sorted(
            candidates,
            key=lambda capability: (
                int(dependency_priority.get(capability, 999)),
                -float(scored_capabilities.get(capability, 0.0)),
                capability,
            ),
        )

    return [
        capability
        for capability, score in scored_capabilities.items()
        if capability != primary_capability and score >= guarded_threshold
    ]


def compare_capability_contract(
    case: Mapping[str, Any],
    *,
    predicted_primary: str | None,
    predicted_secondary: Sequence[str],
) -> dict[str, Any]:
    """Compare legacy top-one membership or an opt-in strict route contract."""
    legacy_expected = [str(item) for item in case.get("expected_capabilities", [])]
    strict_primary = "expected_primary_capability" in case
    strict_secondary = (
        "expected_secondary_capabilities" in case or "secondary_match" in case
    )
    expected_primary = case.get("expected_primary_capability")
    if strict_primary and expected_primary is None:
        expected_primary = legacy_expected[0] if legacy_expected else None

    if strict_primary:
        primary_ok = predicted_primary == expected_primary
    else:
        primary_ok = not legacy_expected or predicted_primary in legacy_expected

    expected_secondary = [
        str(item) for item in case.get("expected_secondary_capabilities", [])
    ]
    predicted = list(dict.fromkeys(str(item) for item in predicted_secondary))
    missing = [item for item in expected_secondary if item not in predicted]
    unexpected = [item for item in predicted if item not in expected_secondary]
    match_mode = str(case.get("secondary_match", "exact"))
    if not strict_secondary:
        secondary_ok = True
        missing = []
        unexpected = []
    elif match_mode == "contains":
        secondary_ok = not missing
        unexpected = []
    else:
        secondary_ok = not missing and not unexpected

    return {
        "strict_primary": strict_primary,
        "strict_secondary": strict_secondary,
        "expected_primary_capability": expected_primary,
        "expected_secondary_capabilities": expected_secondary,
        "predicted_secondary_capabilities": predicted,
        "missing_secondary_capabilities": missing,
        "unexpected_secondary_capabilities": unexpected,
        "primary_ok": primary_ok,
        "secondary_ok": secondary_ok,
    }
