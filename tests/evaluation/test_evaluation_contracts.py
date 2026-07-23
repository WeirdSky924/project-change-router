from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.evaluation_policy import make_evaluation_attestation
from router_support.evaluation_policy import policy_for_bundle
from .test_evaluation_policy import _bundle, _metrics


@pytest.mark.parametrize(
    ("metric_name", "invalid_value"),
    (
        ("top1_action_accuracy", 2.0),
        ("top1_capability_accuracy", 2.0),
        ("review_precision", 2.0),
        ("review_recall", 2.0),
        ("capability_coverage_ratio", 2.0),
        ("secondary_contract_accuracy", 2.0),
        ("case_count", 30.0),
    ),
)
def test_attested_metrics_must_have_valid_ratio_and_count_types(
    tmp_path: Path,
    metric_name: str,
    invalid_value: object,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(
        bundle,
        _metrics(**{metric_name: invalid_value}),
    )

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"


def test_curated_cases_require_explicit_capability_expectations(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    for case in bundle["evaluation_set"]["cases"]:
        case.pop("expected_capabilities", None)
        case.pop("expected_primary_capability", None)
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.reasons == (
        "evaluation_case_capability_expectation_missing",
    )


def test_multi_capability_policy_requires_strict_secondary_evidence(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["capability_catalog"]["capabilities"].append(
        {
            "id": "storage-runtime",
            "status": "stable",
            "stage": "stable",
        }
    )
    for case in bundle["evaluation_set"]["cases"]:
        case["expected_capabilities"] = ["routing-governance"]
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.reasons == (
        "evaluation_secondary_contract_evidence_missing",
    )


def test_secondary_capability_evidence_must_reference_the_catalog(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["capability_catalog"]["capabilities"].append(
        {
            "id": "storage-runtime",
            "status": "stable",
            "stage": "stable",
        }
    )
    bundle["evaluation_set"]["cases"][0].update(
        {
            "expected_secondary_capabilities": ["invented-capability"],
            "secondary_match": "exact",
        }
    )
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(
        bundle,
        _metrics(strict_secondary_case_count=1),
    )

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.reasons == (
        "evaluation_case_secondary_capability_invalid",
    )


def test_capability_coverage_uses_only_exact_primary_and_secondary_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["capability_catalog"]["capabilities"].extend(
        [
            {
                "id": "storage-runtime",
                "name": "Storage Runtime",
                "maturity": "curated",
                "status": "stable",
                "stage": "stable",
            },
            {
                "id": "billing-runtime",
                "name": "Billing Runtime",
                "maturity": "curated",
                "status": "stable",
                "stage": "stable",
            },
        ]
    )
    cases = bundle["evaluation_set"]["cases"]
    for case in cases:
        case["request"] = f"{case['expected_action']}:{case['id']}"
        case["expected_capabilities"] = [
            "routing-governance",
            "storage-runtime",
            "billing-runtime",
        ]
    strict = cases[0]
    strict.update(
        {
            "expected_secondary_capabilities": ["storage-runtime"],
            "secondary_match": "exact",
        }
    )

    def resolve(request: str, *args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action=request.split(":", 1)[0],
            primary_capability="routing-governance",
            secondary_capabilities=(
                ["storage-runtime"] if request.endswith(str(strict["id"])) else []
            ),
        )

    monkeypatch.setattr(router_core, "resolve_request", resolve)

    report = router_core.evaluate_bundle(bundle, tmp_path)

    assert report["covered_capability_count"] == 2
    assert report["uncovered_capabilities"] == ["billing-runtime"]
    assert report["status"] == "fail"


def test_strict_secondary_mismatch_forces_evaluation_review_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = _bundle(tmp_path)
    cases = bundle["evaluation_set"]["cases"]
    for case in cases:
        case["request"] = f"{case['expected_action']}:{case['id']}"
        case["expected_capabilities"] = ["routing-governance"]
    strict = cases[0]
    strict.update(
        {
            "expected_secondary_capabilities": ["storage-runtime"],
            "secondary_match": "exact",
        }
    )

    def resolve(request: str, *args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            action=request.split(":", 1)[0],
            primary_capability="routing-governance",
            secondary_capabilities=(
                ["transport-hooks"] if request.endswith(str(strict["id"])) else []
            ),
        )

    monkeypatch.setattr(router_core, "resolve_request", resolve)

    report = router_core.evaluate_bundle(bundle, tmp_path)

    assert report["status"] == "fail"
    assert report["enforcement_mode"] == "review_only"
    assert report["secondary_contract_accuracy"] == 0.0
    assert report["strict_secondary_case_count"] == 1
    assert report["per_case_results"][0]["missing_secondary_capabilities"] == [
        "storage-runtime"
    ]
    assert report["per_case_results"][0]["unexpected_secondary_capabilities"] == [
        "transport-hooks"
    ]
