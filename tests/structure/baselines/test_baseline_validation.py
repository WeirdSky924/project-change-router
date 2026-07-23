from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator


SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.import_graph import (
    classify_findings_against_baseline,
    finding_fingerprint,
    validate_architecture_baseline,
)
from router_support.structure_guardrails import gather_structure_findings


BASELINE_SOURCE = """\
class Gateway:
    def execute(self):
        return None
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _central_baseline() -> dict[str, object]:
    return {
        "id": "DATA-001-gateway",
        "kind": "python-class-remove-only",
        "path": "app/database/postgres.py",
        "symbol": "Gateway",
        "source_commit": "comparison",
        "owner": "database-runtime",
        "exit_stage": "G2",
        "max_file_lines": len(BASELINE_SOURCE.splitlines()),
        "max_methods": 1,
        "max_public_methods": 1,
        "tracked_members": [],
        "max_tracked_members_present": 0,
    }


def _central_findings(
    tmp_path: Path,
    baseline: dict[str, object],
) -> list[dict[str, object]]:
    repo = tmp_path / "repo"
    _write(repo / "app/database/postgres.py", BASELINE_SOURCE)
    return gather_structure_findings(
        repo,
        {"config": {"source_commit": None}, "change_rules": {"central_growth_baseline": [baseline]}},
        comparison_commit="comparison",
        changed_path_loader=lambda _repo: (),
        baseline_loader=lambda _repo, _commit, _path: BASELINE_SOURCE,
    )


def _change_rules_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-23T00:00:00Z",
        "generated_by": "test",
        "source_repository": "fixture",
        "source_commit": None,
        "confidence": {},
        "high_risk_conditions": [],
        "route_rules": [],
        "decision_policy": {},
        "architecture_baseline": [],
        "central_growth_baseline": [],
    }


def _schema_errors(payload: dict[str, object]) -> list[object]:
    schema = json.loads(
        (SKILL_ROOT / "schemas/change-rules.schema.json").read_text(encoding="utf-8")
    )
    return list(Draft202012Validator(schema).iter_errors(payload))


def test_central_growth_runtime_requires_max_file_lines(tmp_path: Path) -> None:
    baseline = _central_baseline()
    baseline.pop("max_file_lines")

    findings = _central_findings(tmp_path, baseline)

    diagnostic = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["blocking"] is True
    assert diagnostic["invalid_max_fields"] == ["max_file_lines"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_file_lines", True),
        ("max_file_lines", -1),
        ("max_methods", True),
        ("max_methods", -1),
        ("max_public_methods", -1),
        ("max_tracked_members_present", -1),
    ],
)
def test_central_growth_runtime_rejects_non_integer_or_negative_maxima(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    baseline = _central_baseline()
    baseline[field] = value

    findings = _central_findings(tmp_path, baseline)

    diagnostic = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert field in diagnostic["invalid_max_fields"]


def test_central_declared_max_cannot_exceed_comparison_measurement(
    tmp_path: Path,
) -> None:
    baseline = _central_baseline()
    baseline["max_file_lines"] = len(BASELINE_SOURCE.splitlines()) + 100

    findings = _central_findings(tmp_path, baseline)

    diagnostic = next(
        item
        for item in findings
        if item["rule"] == "structure-baseline-diagnostic"
    )
    assert diagnostic["padded_maxima"]["max_file_lines"] == {
        "declared": len(BASELINE_SOURCE.splitlines()) + 100,
        "measured": len(BASELINE_SOURCE.splitlines()),
    }


def test_change_rules_schema_requires_strict_central_maxima() -> None:
    payload = _change_rules_payload()
    baseline = _central_baseline()
    baseline.pop("max_file_lines")
    payload["central_growth_baseline"] = [baseline]
    assert _schema_errors(payload)

    for field, value in (
        ("max_file_lines", True),
        ("max_file_lines", -1),
        ("max_methods", True),
        ("max_public_methods", -1),
    ):
        invalid = _central_baseline()
        invalid[field] = value
        payload["central_growth_baseline"] = [invalid]
        assert _schema_errors(payload), (field, value)


def test_architecture_baseline_rejects_boolean_identity_and_stays_blocking() -> None:
    finding = {
        "severity": "P1",
        "rule": "dependency-direction",
        "source": "app/service.py",
        "target": "app/api.py",
    }
    baseline = {
        "id": True,
        "rule": finding["rule"],
        "source": finding["source"],
        "target": finding["target"],
        "owner": True,
        "exit_stage": True,
        "fingerprint": finding_fingerprint(finding),
    }

    errors = validate_architecture_baseline([baseline], [finding])
    classified = classify_findings_against_baseline([finding], [baseline])

    assert {item["code"] for item in errors} >= {
        "baseline_invalid_id_type",
        "baseline_invalid_owner_type",
        "baseline_invalid_exit_stage_type",
    }
    assert classified[0]["baseline_status"] == "new"
    assert classified[0]["blocking"] is True


def test_change_rules_schema_rejects_boolean_architecture_identity() -> None:
    payload = _change_rules_payload()
    finding = {
        "rule": "dependency-direction",
        "source": "app/service.py",
        "target": "app/api.py",
    }
    payload["architecture_baseline"] = [
        {
            "id": True,
            **finding,
            "owner": True,
            "exit_stage": True,
            "fingerprint": finding_fingerprint(finding),
        }
    ]

    assert _schema_errors(payload)


@pytest.mark.parametrize(
    ("rule", "identity"),
    [
        ("dependency-direction", {"source": True, "target": "app/api.py"}),
        ("runtime-cycle", {"language": "python", "members": [True]}),
        ("public-export-count", {"module": "app.shared", "count": True}),
    ],
)
def test_architecture_baseline_rejects_non_string_or_boolean_identity(
    rule: str,
    identity: dict[str, object],
) -> None:
    item = {
        "id": "invalid-identity",
        "rule": rule,
        **identity,
        "owner": "shared-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint({"rule": rule, **identity}),
    }

    errors = validate_architecture_baseline([item])

    assert "baseline_invalid_identity_type" in {
        error["code"] for error in errors
    }


def test_public_export_count_is_a_one_way_ratchet() -> None:
    baseline_finding = {
        "severity": "P1",
        "rule": "public-export-count",
        "module": "app.shared",
        "count": 4,
    }
    baseline = [{
        "id": "PUBLIC-001-shared",
        "rule": "public-export-count",
        "module": "app.shared",
        "count": 4,
        "owner": "shared-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(baseline_finding),
    }]

    reduced = classify_findings_against_baseline(
        [{**baseline_finding, "count": 2}],
        baseline,
        governed_rules={"public-export-count"},
    )
    grown = classify_findings_against_baseline(
        [{**baseline_finding, "count": 5}],
        baseline,
        governed_rules={"public-export-count"},
    )
    reduced_finding = {**baseline_finding, "count": 2}
    lowered_baseline = [{
        **baseline[0],
        "count": 2,
        "fingerprint": finding_fingerprint(reduced_finding),
    }]
    accepted_low_watermark = classify_findings_against_baseline(
        [reduced_finding],
        lowered_baseline,
        governed_rules={"public-export-count"},
    )
    relapsed = classify_findings_against_baseline(
        [{**baseline_finding, "count": 3}],
        lowered_baseline,
        governed_rules={"public-export-count"},
    )

    assert reduced[0]["blocking"] is False
    assert reduced[0]["baseline_update_required"] is True
    assert reduced[0]["baseline_previous_count"] == 4
    assert reduced[1]["diagnostic_code"] == "baseline_ratchet_update_required"
    assert reduced[1]["blocking"] is True
    assert grown[0]["baseline_status"] == "new"
    assert grown[0]["blocking"] is True
    assert accepted_low_watermark[0]["blocking"] is False
    assert len(accepted_low_watermark) == 1
    assert relapsed[0]["baseline_status"] == "new"
    assert relapsed[0]["blocking"] is True


def test_scoped_orphan_baseline_is_a_blocking_runtime_diagnostic() -> None:
    finding = {
        "rule": "dependency-direction",
        "source": "app/service.py",
        "target": "app/api.py",
    }
    baseline = [{
        "id": "DEP-001-service-api",
        **finding,
        "owner": "service-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(finding),
    }]

    classified = classify_findings_against_baseline(
        [],
        baseline,
        governed_rules={"dependency-direction"},
    )

    assert classified == [
        {
            "severity": "P0",
            "rule": "architecture-baseline-diagnostic",
            "source": "DEP-001-service-api",
            "blocking": True,
            "baseline_status": "new",
            "diagnostic_code": "baseline_orphan",
            "baseline_id": "DEP-001-service-api",
            "message": "Baseline no longer matches a current finding and must be removed",
        }
    ]


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("owner", "   ", "baseline_missing_owner"),
        ("owner", " Provisional:temp", "baseline_unknown_owner"),
        ("owner", "unknown ", "baseline_unknown_owner"),
        ("owner", " unassigned ", "baseline_unknown_owner"),
        ("owner", "None", "baseline_unknown_owner"),
        ("owner", " Capability-Steward:auto", "baseline_unknown_owner"),
        ("owner", "architecture-reviewer:auto ", "baseline_unknown_owner"),
        ("exit_stage", "\t", "baseline_missing_exit_stage"),
    ],
)
def test_architecture_baseline_normalizes_owner_and_exit_metadata(
    field: str,
    value: str,
    expected_code: str,
) -> None:
    finding = {
        "rule": "dependency-direction",
        "source": "app/service.py",
        "target": "app/api.py",
    }
    baseline = {
        "id": "DEP-001-service-api",
        **finding,
        "owner": "service-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(finding),
    }
    baseline[field] = value

    errors = validate_architecture_baseline([baseline])

    assert expected_code in {error["code"] for error in errors}


@pytest.mark.parametrize("field", ["id", "rule", "owner", "exit_stage"])
def test_change_rules_schema_rejects_whitespace_baseline_metadata(
    field: str,
) -> None:
    payload = _change_rules_payload()
    finding = {
        "rule": "dependency-direction",
        "source": "app/service.py",
        "target": "app/api.py",
    }
    baseline = {
        "id": "DEP-001-service-api",
        **finding,
        "owner": "service-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(finding),
    }
    baseline[field] = "   "
    payload["architecture_baseline"] = [baseline]

    assert _schema_errors(payload)


def test_import_graph_diagnostics_cannot_be_architecture_baselined() -> None:
    unresolved = {
        "severity": "P1",
        "rule": "import-graph-diagnostic",
        "source": "app/service.py",
        "language": "python",
        "diagnostic_code": "unresolved-local-import",
    }
    parse_error = {
        **unresolved,
        "diagnostic_code": "parse-error",
    }
    baseline = [{
        "id": "invalid-diagnostic-baseline",
        **unresolved,
        "owner": "service-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(unresolved),
    }]

    classified = classify_findings_against_baseline(
        [unresolved],
        baseline,
        governed_rules={"import-graph-diagnostic"},
    )

    assert finding_fingerprint(unresolved) != finding_fingerprint(parse_error)
    assert classified[0]["baseline_status"] == "new"
    assert classified[0]["blocking"] is True
    assert any(
        item.get("diagnostic_code") == "baseline_unsupported_rule"
        and item["blocking"] is True
        for item in classified[1:]
    )


def test_change_rules_schema_rejects_diagnostic_architecture_baseline() -> None:
    payload = _change_rules_payload()
    finding = {
        "rule": "import-graph-diagnostic",
        "source": "app/service.py",
        "language": "python",
        "diagnostic_code": "parse-error",
    }
    payload["architecture_baseline"] = [{
        "id": "invalid-diagnostic-baseline",
        **finding,
        "owner": "service-runtime",
        "exit_stage": "G2",
        "fingerprint": finding_fingerprint(finding),
    }]

    assert _schema_errors(payload)


def test_change_rules_schema_requires_function_central_measurements() -> None:
    payload = _change_rules_payload()
    function_baseline = {
        "id": "API-001-create-app",
        "kind": "python-function-remove-only",
        "path": "app/api/app.py",
        "symbol": "create_app",
        "source_commit": "comparison",
        "owner": "api-composition",
        "exit_stage": "G2",
        "max_file_lines": 100,
        "max_symbol_lines": 80,
        "max_nested_functions": 12,
        "max_decorated_handlers": 10,
    }
    payload["central_growth_baseline"] = [function_baseline]
    assert _schema_errors(payload) == []

    function_baseline.pop("max_symbol_lines")
    assert _schema_errors(payload)


def test_change_rules_schema_types_reuse_scan_budget_ranges() -> None:
    payload = _change_rules_payload()
    valid_budget = {
        "max_candidate_files": 0,
        "max_comparisons": 5000,
        "max_length_ratio": 8,
        "min_token_jaccard": 0.08,
        "min_path_token_overlap": 0.05,
        "min_fingerprint_advisory_score": 0.55,
    }
    payload["reuse_scan_budget"] = valid_budget
    assert _schema_errors(payload) == []

    for field, value in (
        ("max_candidate_files", True),
        ("max_comparisons", -1),
        ("max_length_ratio", 7.99),
        ("min_token_jaccard", 0.09),
        ("min_path_token_overlap", 0.06),
        ("min_fingerprint_advisory_score", 1.1),
    ):
        invalid = dict(valid_budget)
        invalid[field] = value
        payload["reuse_scan_budget"] = invalid
        assert _schema_errors(payload), (field, value)
