from __future__ import annotations

import json

import pytest

from router_support.change_flow import (
    SAFE_ENVELOPE_FIELDS,
    compact_flow_output,
    persist_flow_artifact,
)


def _report() -> dict:
    return {
        "action": "extend",
        "primary_capability": "workflow",
        "execution_gate": {
            "state": "conditional",
            "unknown_evidence": [],
        },
        "veto_reasons": [],
        "allowed_write_paths": ["app/workflow/**"],
        "forbidden_write_paths": ["legacy/**"],
        "unknown_evidence": [],
        "artifact_path": "runtime/full.json",
        "artifact_digest": "a" * 64,
        "output_complete": True,
        "required_commands": ["python check.py"],
        "recommended_next_action": "run_required_commands",
        "candidate_capabilities": [{"id": "workflow", "score": 0.9}],
        "full_diagnostics": {"large": [1, 2, 3]},
    }


def test_compact_projection_cannot_hide_safety_envelope() -> None:
    compact = compact_flow_output(_report(), fields=["action"])

    assert set(SAFE_ENVELOPE_FIELDS) <= set(compact)
    assert compact["action"] == "extend"
    assert "candidate_capabilities" not in compact
    assert "full_diagnostics" not in compact


def test_artifact_reference_mode_keeps_only_envelope_and_next_command() -> None:
    compact = compact_flow_output(_report(), artifact_reference=True)

    assert set(compact) == set(SAFE_ENVELOPE_FIELDS) | {
        "action",
        "primary_capability",
        "recommended_next_action",
        "required_commands",
    }


def test_explicit_safety_envelope_exclusion_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be excluded"):
        compact_flow_output(
            _report(),
            exclude_fields=["execution_gate"],
        )


def test_persisted_artifact_is_content_addressed_and_readable(tmp_path) -> None:
    path, digest = persist_flow_artifact(tmp_path, {"report": "full"})

    assert path.name == f"{digest}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"report": "full"}
