from __future__ import annotations


UNKNOWN_OWNERS = frozenset({"", "unknown", "unassigned", "none"})
GENERATED_OWNER_PREFIXES = (
    "capability-steward:",
    "architecture-reviewer:",
)


def owner_identity(value: object) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def owner_identity_is_valid(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def owner_is_unknown(value: object) -> bool:
    if not owner_identity_is_valid(value):
        return True
    normalized = owner_identity(value)
    return (
        normalized in UNKNOWN_OWNERS
        or normalized.startswith("provisional:")
        or normalized.startswith(GENERATED_OWNER_PREFIXES)
    )
