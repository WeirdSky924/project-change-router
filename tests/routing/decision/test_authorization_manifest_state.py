from __future__ import annotations

import datetime as dt

import pytest

import router_support.authorization_manifest as authorization_manifest
from router_support.authorization_manifest import AuthorizationManifestStore


def _context(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "route_fingerprint": "a" * 64,
        "pre_change_snapshot": "b" * 64,
        "task_id": "task-1",
        "paths": ["app/service.py"],
        "owner": "workflow-runtime",
        "canonical_root": "app/services/workflow",
        "route": "extend",
        "mutation_envelope": {
            "allowed_write_paths": ["app/services/workflow/**"],
            "forbidden_write_paths": ["legacy/**"],
        },
    }
    values.update(overrides)
    return values


def test_request_does_not_create_authority(tmp_path) -> None:
    store = AuthorizationManifestStore(tmp_path)

    request = store.create_request(_context())

    assert request["state"] == "requested"
    assert store.active_grant(request["request_id"], _context()) is None


def test_user_grant_is_single_use_and_cannot_revive(tmp_path) -> None:
    store = AuthorizationManifestStore(tmp_path)
    request = store.create_request(_context())
    grant = store.grant(
        request["request_id"],
        authorization_source="user",
        confirmation="I authorize this exact mutation envelope.",
    )

    assert grant["state"] == "granted"
    consumed = store.consume(grant["grant_id"], _context())
    assert consumed["state"] == "consumed"
    assert store.active_grant(request["request_id"], _context()) is None

    with pytest.raises(ValueError, match="cannot be granted again"):
        store.grant(
            request["request_id"],
            authorization_source="user",
            confirmation="I repeat the same authorization.",
        )


def test_relevant_input_change_invalidates_grant(tmp_path) -> None:
    store = AuthorizationManifestStore(tmp_path)
    request = store.create_request(_context())
    grant = store.grant(
        request["request_id"],
        authorization_source="user",
        confirmation="I authorize this exact mutation envelope.",
    )

    assert store.active_grant(
        request["request_id"],
        _context(route_fingerprint="c" * 64),
    ) is None
    persisted = store.get_grant(grant["grant_id"])
    assert persisted["state"] == "invalidated"


def test_bounded_multi_use_requires_explicit_limit(tmp_path) -> None:
    store = AuthorizationManifestStore(tmp_path)
    request = store.create_request(_context())
    grant = store.grant(
        request["request_id"],
        authorization_source="user",
        confirmation="I authorize exactly two uses.",
        max_uses=2,
    )

    first = store.consume(grant["grant_id"], _context())
    second = store.consume(grant["grant_id"], _context())

    assert first["state"] == "granted"
    assert first["uses_remaining"] == 1
    assert second["state"] == "consumed"
    assert second["uses_remaining"] == 0


def test_expired_grant_transitions_before_use(tmp_path, monkeypatch) -> None:
    store = AuthorizationManifestStore(tmp_path)
    request = store.create_request(_context())
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    grant = store.grant(
        request["request_id"],
        authorization_source="user",
        confirmation="I authorize this envelope for one hour.",
        expires_at=expires.isoformat(),
    )

    real_datetime = authorization_manifest.dt.datetime

    class FutureDateTime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            value = expires + dt.timedelta(hours=1)
            return value if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(authorization_manifest.dt, "datetime", FutureDateTime)

    with pytest.raises(ValueError, match="not active"):
        store.consume(grant["grant_id"], _context())
    assert store.get_grant(grant["grant_id"])["state"] == "expired"


def test_grant_audit_chain_detects_tampering(tmp_path) -> None:
    store = AuthorizationManifestStore(tmp_path)
    request = store.create_request(_context())
    grant = store.grant(
        request["request_id"],
        authorization_source="user",
        confirmation="I authorize this exact mutation envelope.",
    )

    manifest_path = tmp_path / "authorizations" / f"{grant['grant_id']}.json"
    raw = manifest_path.read_text(encoding="utf-8").replace(
        '"state": "granted"', '"state": "consumed"'
    )
    manifest_path.write_text(raw, encoding="utf-8")

    with pytest.raises(ValueError, match="audit chain"):
        store.get_grant(grant["grant_id"])
