from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.route_authorization import route_authorization_fingerprint


CURRENT_TASK_AUTHORIZATION = (
    "I authorize overriding this router stop only for the current task after "
    "recording the reason."
)
LIFECYCLE_AUTHORIZATION = (
    "I authorize this lifecycle change with superseded_by, migration_note, and "
    "test impact recorded."
)


def _profiled_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "profiled-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "services" / "payments").mkdir(parents=True)
    (repo / "services" / "payments" / "service.py").write_text(
        "def charge():\n    return True\n",
        encoding="utf-8",
    )
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: authorization-audit
capabilities:
  - id: payment-core
    name: Payment Core
    stage: stable
    status: stable
    path_patterns: ["services/payments/**"]
    public_entries: ["services/payments/service.py"]
    keywords: ["payment", "charge"]
ownership_rules:
  - path_patterns: ["services/payments/**"]
    owner: payments-team
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def _lifecycle_route(tmp_path: Path) -> tuple[Path, router_core.RouteDecision]:
    repo = _profiled_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    decision = router_core.resolve_request(
        "Deprecate the existing payment-core capability after caller migration.",
        ["services\\payments\\service.py", "services/payments/service.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
        freshness_context="route",
    )
    report_path = bundle_root / "reports" / "route-payment-core.json"
    router_core.dump_json_file(report_path, decision.to_dict())
    return bundle_root, decision


def _authorization_feedback(decision: router_core.RouteDecision) -> dict[str, object]:
    return {
        "feedback_id": "feedback-payment-core-lifecycle",
        "decision_id": decision.decision_id,
        "final_action": "deprecate",
        "final_capability": "payment-core",
        "notes": "Lifecycle migration approved for the exact routed path.",
        "authorization_texts": [
            CURRENT_TASK_AUTHORIZATION,
            LIFECYCLE_AUTHORIZATION,
        ],
        "allowed_paths": ["services/payments/service.py"],
        "override_reason": "Named caller migration requires this lifecycle change.",
        "expires_after": "current_task",
        "route_fingerprint": decision.route_fingerprint,
    }


def test_route_decision_persists_normalized_changed_paths(tmp_path: Path) -> None:
    _bundle_root, decision = _lifecycle_route(tmp_path)

    assert decision.changed_paths == ["services/payments/service.py"]
    assert decision.to_dict()["changed_paths"] == ["services/payments/service.py"]


def test_route_schema_requires_changed_paths() -> None:
    path = SKILL_ROOT / "schemas" / "route-decision-report.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert "changed_paths" in schema["required"]
    changed_paths = schema["properties"]["changed_paths"]
    assert changed_paths["type"] == "array"
    assert changed_paths["items"]["type"] == "string"
    assert "authorization_context" in schema["required"]
    assert "route_fingerprint" in schema["required"]


def test_feedback_marks_only_verified_route_authorization_consumed(
    tmp_path: Path,
) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    feedback = _authorization_feedback(decision)
    feedback["allowed_paths"] = [
        "services\\payments\\service.py",
        "services/payments/service.py",
    ]

    payload = router_core.record_manual_feedback(
        bundle_root,
        feedback,
    )

    assert payload["authorization_status"] == "consumed_for_route_only"
    assert payload["override_consumed"] is True
    assert payload["allowed_paths"] == ["services/payments/service.py"]
    assert payload["authorization_texts"] == [
        CURRENT_TASK_AUTHORIZATION,
        LIFECYCLE_AUTHORIZATION,
    ]
    assert payload["override_reason"] == (
        "Named caller migration requires this lifecycle change."
    )
    assert payload["expires_after"] == "current_task"
    assert payload["route_fingerprint"] == decision.route_fingerprint
    persisted = json.loads(
        (
            bundle_root
            / "reports"
            / "manual-feedback"
            / "feedback-payment-core-lifecycle.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted == payload


def test_feedback_rejects_unknown_or_ambiguous_route(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    unknown = _authorization_feedback(decision)
    unknown["decision_id"] = "route-unknown"
    with pytest.raises(ValueError, match="existing route"):
        router_core.record_manual_feedback(bundle_root, unknown)

    source = bundle_root / "reports" / "route-payment-core.json"
    duplicate = bundle_root / "reports" / "route-payment-core-copy.json"
    duplicate.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous route"):
        router_core.record_manual_feedback(
            bundle_root,
            _authorization_feedback(decision),
        )


def test_feedback_rejects_route_without_changed_paths(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    report_path = bundle_root / "reports" / "route-payment-core.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.pop("changed_paths")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ValueError, match="does not persist changed paths"):
        router_core.record_manual_feedback(
            bundle_root,
            _authorization_feedback(decision),
        )


def test_feedback_rejects_route_changed_after_authorization(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    report = decision.to_dict()
    report["action"] = "extend"
    report["review_required"] = False
    report["override_requirements"] = []
    report["route_fingerprint"] = route_authorization_fingerprint(report)
    router_core.dump_json_file(
        bundle_root / "reports" / "route-payment-core.json",
        report,
    )

    with pytest.raises(ValueError, match="authorization route fingerprint"):
        router_core.record_manual_feedback(
            bundle_root,
            _authorization_feedback(decision),
        )


def test_feedback_rejects_path_outside_route(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    feedback = _authorization_feedback(decision)
    feedback["allowed_paths"] = ["services/billing/service.py"]

    with pytest.raises(ValueError, match="outside the routed changed paths"):
        router_core.record_manual_feedback(bundle_root, feedback)


@pytest.mark.parametrize(
    "unsafe_path",
    ["../services/payments/service.py", "/services/payments/service.py", "C:\\service.py"],
)
def test_feedback_rejects_unsafe_path(tmp_path: Path, unsafe_path: str) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    feedback = _authorization_feedback(decision)
    feedback["allowed_paths"] = [unsafe_path]

    with pytest.raises(ValueError, match="unsafe authorization path"):
        router_core.record_manual_feedback(bundle_root, feedback)


def test_feedback_rejects_missing_lifecycle_authorization(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    feedback = _authorization_feedback(decision)
    feedback["authorization_texts"] = [CURRENT_TASK_AUTHORIZATION]

    with pytest.raises(ValueError, match="required authorization text"):
        router_core.record_manual_feedback(bundle_root, feedback)


@pytest.mark.parametrize("field", ["override_reason", "expires_after"])
def test_feedback_rejects_incomplete_audit_fields(
    tmp_path: Path,
    field: str,
) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)
    feedback = _authorization_feedback(decision)
    feedback[field] = ""

    with pytest.raises(ValueError, match=field):
        router_core.record_manual_feedback(bundle_root, feedback)


def test_unstructured_notes_are_not_authorization_evidence(tmp_path: Path) -> None:
    bundle_root, decision = _lifecycle_route(tmp_path)

    payload = router_core.record_manual_feedback(
        bundle_root,
        {
            "feedback_id": "feedback-notes-only",
            "decision_id": decision.decision_id,
            "notes": CURRENT_TASK_AUTHORIZATION,
        },
    )

    assert payload["authorization_status"] == "not_authorization_evidence"
    assert payload["override_consumed"] is False
