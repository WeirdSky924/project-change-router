from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

from router_support.typed_findings import digest_value


AUTHORIZATION_SCHEMA_VERSION = 1
DEFAULT_GRANT_LIFETIME_HOURS = 24
MAX_GRANT_LIFETIME_DAYS = 30
MAX_BOUNDED_USES = 100
CONTEXT_FIELDS = (
    "route_fingerprint",
    "pre_change_snapshot",
    "task_id",
    "paths",
    "owner",
    "canonical_root",
    "route",
    "mutation_envelope",
)


def _now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_paths(values: object) -> list[str]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError("authorization paths must be a list of strings")
    normalized: list[str] = []
    for item in values:
        path = item.replace("\\", "/").strip()
        if (
            not path
            or path.startswith("/")
            or re.match(r"^[A-Za-z]:/", path)
            or ".." in path.split("/")
        ):
            raise ValueError("authorization contains an unsafe path")
        if path not in normalized:
            normalized.append(path)
    return normalized


def normalize_authorization_context(value: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in CONTEXT_FIELDS if field not in value]
    if missing:
        raise ValueError("authorization context is incomplete: " + ", ".join(missing))
    envelope = value.get("mutation_envelope")
    if not isinstance(envelope, Mapping):
        raise ValueError("mutation_envelope must be an object")
    normalized_envelope = {
        "allowed_write_paths": _safe_paths(
            list(envelope.get("allowed_write_paths", []))
        ),
        "forbidden_write_paths": _safe_paths(
            list(envelope.get("forbidden_write_paths", []))
        ),
    }
    route_fingerprint = str(value.get("route_fingerprint", ""))
    snapshot = str(value.get("pre_change_snapshot", ""))
    for name, raw in (
        ("route_fingerprint", route_fingerprint),
        ("pre_change_snapshot", snapshot),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", raw):
            raise ValueError(f"{name} must be a SHA-256 digest")
    return {
        "route_fingerprint": route_fingerprint,
        "pre_change_snapshot": snapshot,
        "task_id": str(value.get("task_id") or ""),
        "paths": _safe_paths(list(value.get("paths", []))),
        "owner": str(value.get("owner") or ""),
        "canonical_root": str(value.get("canonical_root") or ""),
        "route": str(value.get("route") or ""),
        "mutation_envelope": normalized_envelope,
    }


def _parse_timestamp(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("authorization expiry must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("authorization expiry must include a timezone")
    return parsed.astimezone(dt.timezone.utc)


def _expiry(value: str | None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    expires = (
        _parse_timestamp(value)
        if value
        else now + dt.timedelta(hours=DEFAULT_GRANT_LIFETIME_HOURS)
    )
    if expires <= now:
        raise ValueError("authorization expiry must be in the future")
    if expires > now + dt.timedelta(days=MAX_GRANT_LIFETIME_DAYS):
        raise ValueError("authorization expiry exceeds the maximum lifetime")
    return expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _event(
    sequence: int,
    action: str,
    state: str,
    previous_digest: str | None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event = {
        "sequence": sequence,
        "action": action,
        "state": state,
        "timestamp": _now(),
        "previous_digest": previous_digest,
        "details": dict(details or {}),
    }
    event["event_digest"] = digest_value(event)
    return event


def _verify_audit_chain(manifest: Mapping[str, Any]) -> None:
    events = manifest.get("audit_events")
    if not isinstance(events, list) or not events:
        raise ValueError("authorization audit chain is missing")
    previous: str | None = None
    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            raise ValueError("authorization audit chain contains an invalid event")
        payload = {key: value for key, value in event.items() if key != "event_digest"}
        if event.get("sequence") != index or event.get("previous_digest") != previous:
            raise ValueError("authorization audit chain sequence is invalid")
        if event.get("event_digest") != digest_value(payload):
            raise ValueError("authorization audit chain digest is invalid")
        previous = str(event["event_digest"])
    if manifest.get("state") != events[-1].get("state"):
        raise ValueError("authorization audit chain does not match manifest state")
    if digest_value(manifest.get("context", {})) != manifest.get("context_digest"):
        raise ValueError("authorization context digest is invalid")
    binding = {
        "request_id": manifest.get("request_id"),
        "context_digest": manifest.get("context_digest"),
        "authorization_source": manifest.get("authorization_source"),
        "confirmation": manifest.get("confirmation"),
        "max_uses": manifest.get("max_uses"),
        "expires_at": manifest.get("expires_at"),
    }
    if digest_value(binding) != manifest.get("grant_binding_digest"):
        raise ValueError("authorization grant binding digest is invalid")
    uses = sum(event.get("action") == "grant_used" for event in events)
    expected_remaining = int(manifest.get("max_uses", 0)) - uses
    if manifest.get("uses_remaining") != expected_remaining:
        raise ValueError("authorization use count does not match audit chain")


class AuthorizationManifestStore:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.requests_root = self.runtime_root / "authorization-requests"
        self.grants_root = self.runtime_root / "authorizations"

    def create_request(self, context: Mapping[str, Any]) -> dict[str, Any]:
        normalized = normalize_authorization_context(context)
        created_at = _now()
        request_id = digest_value(
            {"context": normalized, "created_at": created_at, "nonce": uuid.uuid4().hex}
        )
        request = {
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "request_id": request_id,
            "state": "requested",
            "created_at": created_at,
            "context": normalized,
            "context_digest": digest_value(normalized),
        }
        _atomic_json(self.requests_root / f"{request_id}.json", request)
        return request

    def _request(self, request_id: str) -> dict[str, Any]:
        path = self.requests_root / f"{request_id}.json"
        if not path.is_file():
            raise ValueError("authorization request does not exist")
        request = json.loads(path.read_text(encoding="utf-8"))
        if digest_value(request.get("context", {})) != request.get("context_digest"):
            raise ValueError("authorization request context digest is invalid")
        return request

    def grant(
        self,
        request_id: str,
        *,
        authorization_source: str,
        confirmation: str,
        max_uses: int = 1,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        request = self._request(request_id)
        existing = list(self.grants_root.glob("*.json")) if self.grants_root.exists() else []
        for path in existing:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("request_id") == request_id:
                raise ValueError("authorization request cannot be granted again")
        if not authorization_source.strip() or not confirmation.strip():
            raise ValueError("grant requires authorization source and confirmation")
        if isinstance(max_uses, bool) or not isinstance(max_uses, int):
            raise ValueError("authorization max_uses must be an integer")
        if max_uses < 1 or max_uses > MAX_BOUNDED_USES:
            raise ValueError("authorization max_uses is outside the bounded range")
        normalized_expiry = _expiry(expires_at)
        grant_id = digest_value(
            {
                "request_id": request_id,
                "source": authorization_source,
                "confirmation": confirmation,
                "nonce": uuid.uuid4().hex,
            }
        )
        first_event = _event(
            0,
            "grant_created",
            "granted",
            None,
            {"max_uses": max_uses, "expires_at": normalized_expiry},
        )
        grant_binding = {
            "request_id": request_id,
            "context_digest": request["context_digest"],
            "authorization_source": authorization_source,
            "confirmation": confirmation,
            "max_uses": max_uses,
            "expires_at": normalized_expiry,
        }
        grant = {
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "grant_id": grant_id,
            "request_id": request_id,
            "state": "granted",
            "context": request["context"],
            "context_digest": request["context_digest"],
            "authorization_source": authorization_source,
            "confirmation": confirmation,
            "max_uses": max_uses,
            "uses_remaining": max_uses,
            "expires_at": normalized_expiry,
            "grant_binding_digest": digest_value(grant_binding),
            "audit_events": [first_event],
        }
        _atomic_json(self.grants_root / f"{grant_id}.json", grant)
        return grant

    def get_grant(self, grant_id: str) -> dict[str, Any]:
        path = self.grants_root / f"{grant_id}.json"
        if not path.is_file():
            raise ValueError("authorization grant does not exist")
        grant = json.loads(path.read_text(encoding="utf-8"))
        _verify_audit_chain(grant)
        return grant

    def _transition(
        self,
        grant: dict[str, Any],
        state: str,
        *,
        action: str | None = None,
        updates: Mapping[str, Any] | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        events = list(grant["audit_events"])
        events.append(
            _event(
                len(events),
                action or state,
                state,
                events[-1]["event_digest"],
                details,
            )
        )
        updated = {
            **grant,
            **dict(updates or {}),
            "state": state,
            "audit_events": events,
        }
        _atomic_json(self.grants_root / f"{grant['grant_id']}.json", updated)
        return updated

    def _expire_if_needed(self, grant: dict[str, Any]) -> dict[str, Any]:
        if grant.get("state") != "granted":
            return grant
        expires_at = _parse_timestamp(str(grant.get("expires_at", "")))
        if expires_at > dt.datetime.now(dt.timezone.utc):
            return grant
        return self._transition(
            grant,
            "expired",
            action="grant_expired",
            details={"expires_at": grant.get("expires_at")},
        )

    def consume(self, grant_id: str, current_context: Mapping[str, Any]) -> dict[str, Any]:
        grant = self._expire_if_needed(self.get_grant(grant_id))
        if grant["state"] != "granted":
            raise ValueError("authorization grant is not active")
        normalized = normalize_authorization_context(current_context)
        if digest_value(normalized) != grant["context_digest"]:
            self._transition(
                grant,
                "invalidated",
                action="context_invalidated",
            )
            raise ValueError("authorization context changed before consumption")
        remaining = int(grant.get("uses_remaining", 1)) - 1
        state = "consumed" if remaining == 0 else "granted"
        return self._transition(
            grant,
            state,
            action="grant_used",
            updates={"uses_remaining": remaining},
            details={"uses_remaining": remaining},
        )

    def active_grant(
        self, request_id: str, current_context: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        current_digest = digest_value(normalize_authorization_context(current_context))
        if not self.grants_root.exists():
            return None
        for path in sorted(self.grants_root.glob("*.json")):
            grant = self._expire_if_needed(self.get_grant(path.stem))
            if grant.get("request_id") != request_id or grant.get("state") != "granted":
                continue
            if grant.get("context_digest") != current_digest:
                self._transition(
                    grant,
                    "invalidated",
                    action="context_invalidated",
                )
                return None
            return grant
        return None
