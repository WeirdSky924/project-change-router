from __future__ import annotations

import pytest

from router_support.execution_gate import reduce_execution_gate, shadow_gate_comparison
from router_support.finding_adapters import adapt_check_report
from router_support.typed_findings import TypedFinding, validate_typed_finding


def _finding(**overrides: object) -> TypedFinding:
    values: dict[str, object] = {
        "type": "historical_structure_debt",
        "severity": "P2",
        "invariant_class": "closure_global",
        "origin": "structure",
        "delta_state": "baseline_unchanged",
        "task_relevance": "unrelated",
        "evidence_status": "complete",
        "policy_rule_id": "GATE-HISTORY-001",
        "paths": ["legacy/report.py"],
        "capabilities": ["reports"],
        "evidence": {"line_count": 1300},
    }
    values.update(overrides)
    return TypedFinding.create(**values)


def test_finding_identity_is_content_derived_and_order_stable() -> None:
    first = _finding(paths=["b.py", "a.py"], capabilities=["reports", "core"])
    second = _finding(paths=["a.py", "b.py"], capabilities=["core", "reports"])

    assert first.finding_id == second.finding_id
    assert first.evidence_digest == second.evidence_digest
    assert validate_typed_finding(first.to_dict()) == ()


def test_finding_validation_rejects_missing_policy_identity() -> None:
    payload = _finding().to_dict()
    payload["policy_rule_id"] = ""

    assert "policy_rule_id" in validate_typed_finding(payload)


def test_gate_passes_complete_route_without_relevant_blockers() -> None:
    gate = reduce_execution_gate(
        [],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=[],
        required_commands=["python -m pytest tests/core"],
        output_complete=True,
    )

    assert gate["state"] == "pass"
    assert gate["blocking"] is False
    assert gate["policy_rule_ids"] == ["GATE-PASS-001"]


def test_gate_is_conditional_only_for_complete_unrelated_baseline_debt() -> None:
    gate = reduce_execution_gate(
        [_finding()],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=["legacy/**"],
        required_commands=["python scripts/check_deps.py --repo ."],
        output_complete=True,
    )

    assert gate["state"] == "conditional"
    assert gate["blocking"] is False
    assert gate["decisive_finding_ids"] == [_finding().finding_id]


@pytest.mark.parametrize(
    ("finding", "expected_rule"),
    [
        (
            _finding(
                type="unindexed_path",
                severity="P0",
                delta_state="unknown",
                task_relevance="unknown",
                evidence_status="incomplete",
                policy_rule_id="GATE-PATH-001",
            ),
            "GATE-UNKNOWN-001",
        ),
        (
            _finding(
                type="duplicate_owner",
                severity="P0",
                invariant_class="always_global",
                delta_state="task_local_new",
                task_relevance="relevant",
                policy_rule_id="GATE-OWNER-001",
            ),
            "GATE-HARD-001",
        ),
        (
            _finding(
                type="dynamic_import_unknown",
                severity="P1",
                delta_state="unknown",
                task_relevance="unknown",
                evidence_status="bounded",
                policy_rule_id="GATE-IMPORT-001",
            ),
            "GATE-UNKNOWN-001",
        ),
    ],
)
def test_gate_blocks_unknown_and_hard_invariants(
    finding: TypedFinding, expected_rule: str
) -> None:
    gate = reduce_execution_gate(
        [finding],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=[],
        required_commands=["python scripts/check_deps.py --repo ."],
        output_complete=True,
    )

    assert gate["state"] == "blocked"
    assert expected_rule in gate["policy_rule_ids"]
    assert gate["decisive_finding_ids"] == [finding.finding_id]


def test_bounded_unrelated_evidence_cannot_be_conditional() -> None:
    gate = reduce_execution_gate(
        [_finding(evidence_status="bounded")],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=[],
        required_commands=["python scripts/check_reuse.py --repo ."],
        output_complete=False,
    )

    assert gate["state"] == "blocked"
    assert "GATE-OUTPUT-001" in gate["policy_rule_ids"]


def test_incomplete_output_cannot_bypass_typed_finding_normalization() -> None:
    with pytest.raises(ValueError, match="requires a schema-valid typed finding"):
        reduce_execution_gate(
            [],
            allowed_write_paths=["src/core/**"],
            forbidden_write_paths=[],
            required_commands=["python check.py"],
            output_complete=False,
        )


def test_new_unrelated_p1_is_not_laundered_without_baseline() -> None:
    gate = reduce_execution_gate(
        [_finding(severity="P1", delta_state="task_local_new")],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=[],
        required_commands=["python check.py"],
        output_complete=True,
    )

    assert gate["state"] == "blocked"
    assert "GATE-DELTA-001" in gate["policy_rule_ids"]


def test_shadow_comparison_never_hides_a_less_safe_new_gate() -> None:
    comparison = shadow_gate_comparison(
        legacy_state="blocked",
        new_gate={"state": "pass", "decisive_finding_ids": []},
    )

    assert comparison["classification"] == "less_safe"
    assert comparison["cutover_eligible"] is False


def test_shadow_accepts_proven_historical_debt_as_precision_improvement() -> None:
    gate = reduce_execution_gate(
        [_finding()],
        allowed_write_paths=["src/core/**"],
        forbidden_write_paths=["legacy/**"],
        required_commands=["python check.py"],
        output_complete=True,
    )

    comparison = shadow_gate_comparison(legacy_state="blocked", new_gate=gate)

    assert comparison["classification"] == "precision_improvement"
    assert comparison["cutover_eligible"] is True


def test_proven_architecture_baseline_debt_remains_historical() -> None:
    findings = adapt_check_report(
        "public_api",
        {
            "findings": [
                {
                    "severity": "P1",
                    "rule": "public-export-count",
                    "source": "legacy/api.py",
                    "count": 22,
                    "baseline_status": "existing_debt",
                    "blocking": False,
                }
            ]
        },
        route_paths=["app/workflow/service.py"],
        route_capabilities=["workflow"],
    )

    assert findings[0].type == "historical_public_api_debt"
    assert findings[0].delta_state == "baseline_unchanged"
    assert findings[0].task_relevance == "unrelated"


def test_dynamic_import_inside_route_closure_remains_unknown_and_relevant() -> None:
    findings = adapt_check_report(
        "dependency",
        {
            "findings": [
                {
                    "severity": "P0",
                    "rule": "import-graph-diagnostic",
                    "diagnostic_code": "dynamic-import-unresolved",
                    "source": "app/shared/loader.py",
                }
            ]
        },
        route_paths=["app/workflow/service.py"],
        route_capabilities=["workflow", "shared-runtime"],
        route_scope_paths=["app/workflow", "app/shared"],
    )

    assert findings[0].type == "dynamic_import_unknown"
    assert findings[0].task_relevance == "unknown"
    assert findings[0].delta_state == "unknown"
    assert findings[0].evidence_status == "incomplete"
