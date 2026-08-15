from __future__ import annotations

import json
from pathlib import Path

from router_support.execution_gate import (
    reduce_execution_gate,
    shadow_gate_comparison,
)
from router_support.typed_findings import TypedFinding


SKILL_ROOT = Path(__file__).resolve().parents[2]


def test_anonymized_shadow_replay_matrix() -> None:
    fixture = json.loads(
        (
            SKILL_ROOT
            / "examples"
            / "calibration"
            / "anonymized-gate-replays.json"
        ).read_text(encoding="utf-8")
    )

    observed: dict[str, tuple[str, str]] = {}
    for case in fixture["cases"]:
        finding = TypedFinding.create(
            **case["finding"],
            evidence={"replay_case": case["id"]},
        )
        gate = reduce_execution_gate(
            [finding],
            allowed_write_paths=case.get("allowed_write_paths", ["app/**"]),
            forbidden_write_paths=[],
            required_commands=case.get("required_commands", ["python check.py"]),
            output_complete=True,
        )
        shadow = shadow_gate_comparison(
            legacy_state=case["legacy_state"],
            new_gate=gate,
        )
        observed[case["id"]] = (gate["state"], shadow["classification"])

    expected = {
        case["id"]: (case["expected_gate"], case["expected_shadow"])
        for case in fixture["cases"]
    }
    assert observed == expected
