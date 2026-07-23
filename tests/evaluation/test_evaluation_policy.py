from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.evaluation_policy import (
    EvaluationThresholds,
    evaluation_input_digest,
    evaluate_policy,
    make_evaluation_attestation,
    policy_for_bundle,
)
import router_support.evaluation_policy as evaluation_policy
import router_core


def _metrics(**overrides: object) -> dict[str, object]:
    metrics: dict[str, object] = {
        "top1_action_accuracy": 0.85,
        "top1_capability_accuracy": 0.85,
        "review_precision": 0.90,
        "review_recall": 1.0,
        "capability_coverage_ratio": 0.80,
        "secondary_contract_accuracy": 1.0,
        "case_count": 30,
        "strict_secondary_case_count": 0,
    }
    metrics.update(overrides)
    return metrics


@pytest.mark.parametrize(
    ("request_text", "expected_action"),
    [
        (
            "Extend the existing routing governance capability with one metric.",
            "extend",
        ),
        (
            "Extract repeated routing policy checks into the existing governance capability.",
            "extract",
        ),
    ],
)
def test_synthetic_cases_distinguish_extend_and_extract_intent(
    tmp_path: Path,
    request_text: str,
    expected_action: str,
) -> None:
    bundle, bundle_root = _bundle(tmp_path)
    changed_paths = ["tools/router/router_core.py"]
    if expected_action == "extract":
        changed_paths.append("tools/router/evaluation_policy.py")
    decision = router_core.resolve_request(
        request_text,
        changed_paths,
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.action == expected_action
    assert decision.primary_capability == "routing-governance"


def test_plan_state_keyword_is_not_a_capability_lifecycle_intent() -> None:
    assert (
        router_core.request_lifecycle_intent(
            "Rename the active plan file while keeping the capability stable."
        )
        is None
    )
    assert (
        router_core.request_lifecycle_intent(
            "Deprecate the existing payment-core capability and replace it."
        )
        == "deprecate"
    )


@pytest.mark.parametrize(
    "request_text",
    [
        "Add credential storage and rotation to the public API.",
        "Create a second formal repository root instead of reusing the canonical owner.",
        "Change tenant authorization and billing persistence in one request.",
    ],
)
def test_sensitive_or_duplicate_owner_requests_remain_review(
    tmp_path: Path,
    request_text: str,
) -> None:
    bundle, bundle_root = _bundle(tmp_path)
    decision = router_core.resolve_request(
        request_text,
        ["tools/router/router_core.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.action == "review"
    assert decision.review_required is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"top1_action_accuracy": 0.8499}, "top1_action_accuracy"),
        ({"top1_capability_accuracy": 0.8499}, "top1_capability_accuracy"),
        ({"review_precision": 0.8999}, "review_precision"),
        ({"review_recall": 0.9999}, "review_recall"),
        ({"capability_coverage_ratio": 0.7999}, "capability_coverage_ratio"),
        ({"secondary_contract_accuracy": 0.9999}, "secondary_contract_accuracy"),
        ({"case_count": 29}, "case_count"),
    ],
)
def test_each_evaluation_threshold_fails_independently(
    overrides: dict[str, object], reason: str
) -> None:
    decision = evaluate_policy(_metrics(**overrides), EvaluationThresholds())

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert any(reason in item for item in decision.reasons)


def test_exact_evaluation_thresholds_pass() -> None:
    decision = evaluate_policy(_metrics(), EvaluationThresholds())

    assert decision.passed is True
    assert decision.enforcement_mode == "normal"
    assert decision.reasons == ()


@pytest.mark.parametrize("metric_name", tuple(_metrics()))
@pytest.mark.parametrize(
    "metric_value",
    (float("nan"), float("inf"), float("-inf")),
    ids=("nan", "positive-inf", "negative-inf"),
)
def test_non_finite_evaluation_metrics_are_invalid(
    metric_name: str, metric_value: float
) -> None:
    decision = evaluate_policy(
        _metrics(**{metric_name: metric_value}),
        EvaluationThresholds(),
    )

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (f"{metric_name} missing or invalid",)


def test_missing_enforcement_flag_defaults_to_review_only(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation.pop("enforcement_enabled")
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == ("evaluation_enforcement_disabled",)


def test_disabled_evaluation_enforcement_cannot_grant_write_authority() -> None:
    decision = policy_for_bundle(
        {"config": {"evaluation": {"enforcement_enabled": False}}}
    )

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == ("evaluation_enforcement_disabled",)


def test_generated_only_evaluation_cannot_grant_write_authority(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["evaluation_set"] = {
        "mode": "generated_only",
        "curated_case_ids": [],
        "cases": [{"id": f"generated-{index}"} for index in range(30)],
    }
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == ("evaluation_cases_not_curated",)


def test_evaluation_thresholds_cannot_be_lowered_below_policy_floors(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation.update(
        {
            "top1_accuracy_threshold": 0,
            "top1_capability_accuracy_threshold": 0,
            "review_precision_threshold": 0,
            "review_recall_threshold": 0,
            "minimum_capability_coverage_ratio": 0,
            "secondary_contract_accuracy_threshold": 0,
            "minimum_case_count": 1,
        }
    )
    evaluation["attestation"] = make_evaluation_attestation(
        bundle,
        _metrics(
            top1_action_accuracy=0,
            top1_capability_accuracy=0,
            review_precision=0,
            review_recall=0,
            capability_coverage_ratio=0,
            secondary_contract_accuracy=0,
            case_count=30,
        ),
    )

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert set(decision.reasons) == {
        "evaluation_threshold_below_floor:top1_accuracy_threshold",
        "evaluation_threshold_below_floor:top1_capability_accuracy_threshold",
        "evaluation_threshold_below_floor:review_precision_threshold",
        "evaluation_threshold_below_floor:review_recall_threshold",
        "evaluation_threshold_below_floor:minimum_capability_coverage_ratio",
        "evaluation_threshold_below_floor:secondary_contract_accuracy_threshold",
        "evaluation_threshold_below_floor:minimum_case_count",
    }


def test_curated_evaluation_requires_the_full_calibration_category_matrix(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    for case in bundle["evaluation_set"]["cases"]:
        case.update(
            {
                "expected_action": "review",
                "risk_level": "high",
                "calibration_category": "review_veto",
            }
        )
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (
        "evaluation_case_categories_missing:extract_boundary,false_negative_regression,false_positive_regression,positive_extend,positive_reuse",
    )


RATIO_THRESHOLD_CONFIG_KEYS = (
    "top1_accuracy_threshold",
    "top1_capability_accuracy_threshold",
    "review_precision_threshold",
    "review_recall_threshold",
    "minimum_capability_coverage_ratio",
    "secondary_contract_accuracy_threshold",
)


@pytest.mark.parametrize("threshold_name", RATIO_THRESHOLD_CONFIG_KEYS)
@pytest.mark.parametrize(
    "threshold_value",
    (
        float("nan"),
        float("inf"),
        float("-inf"),
        -0.01,
        1.01,
        True,
        "0.85",
        None,
    ),
    ids=(
        "nan",
        "positive-inf",
        "negative-inf",
        "below-zero",
        "above-one",
        "boolean",
        "numeric-string",
        "null",
    ),
)
def test_invalid_ratio_threshold_config_forces_review_only(
    tmp_path: Path,
    threshold_name: str,
    threshold_value: object,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation[threshold_name] = threshold_value
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (f"evaluation_threshold_invalid:{threshold_name}",)


@pytest.mark.parametrize(
    "minimum_case_count",
    (
        0,
        -1,
        True,
        1.0,
        30.5,
        float("nan"),
        float("inf"),
        float("-inf"),
        "30",
        None,
    ),
    ids=(
        "zero",
        "negative",
        "boolean",
        "integral-float",
        "fractional-float",
        "nan",
        "positive-inf",
        "negative-inf",
        "numeric-string",
        "null",
    ),
)
def test_invalid_minimum_case_count_config_forces_review_only(
    tmp_path: Path,
    minimum_case_count: object,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation["minimum_case_count"] = minimum_case_count
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (
        "evaluation_threshold_invalid:minimum_case_count",
    )


@pytest.mark.parametrize(
    ("config_name", "invalid_value"),
    (
        ("enforcement_enabled", "true"),
        ("top1_accuracy_threshold", "0.85"),
        ("minimum_case_count", 1.5),
    ),
)
def test_profile_evaluation_values_reach_policy_without_coercion(
    tmp_path: Path,
    config_name: str,
    invalid_value: object,
) -> None:
    config = router_core.build_router_config(
        tmp_path,
        [],
        {"evaluation": {config_name: invalid_value}},
        {
            "repo_stage": "structured",
            "stage_score": 1,
            "stage_reasons": [],
            "signals": {},
        },
    )
    bundle = {
        "config": config,
        "evaluation_set": {"cases": []},
    }
    config["evaluation"]["attestation"] = make_evaluation_attestation(
        bundle,
        _metrics(),
    )

    decision = policy_for_bundle(bundle)

    assert config["evaluation"][config_name] == invalid_value
    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"


def test_evaluate_bundle_does_not_truncate_invalid_case_threshold(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["config"]["evaluation"]["minimum_case_count"] = 1.5
    bundle["evaluation_set"] = {"mode": "curated", "cases": []}

    report = router_core.evaluate_bundle(bundle, tmp_path)

    assert report["status"] == "fail"
    assert report["status_reasons"] == [
        "evaluation_threshold_invalid:minimum_case_count"
    ]


def test_hybrid_evaluation_metrics_only_count_curated_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = _bundle(tmp_path)
    cases = bundle["evaluation_set"]["cases"]
    for case in cases:
        case["request"] = f"{case['expected_action']}:{case['id']}"
        case["expected_capabilities"] = ["routing-governance"]
    bundle["evaluation_set"]["mode"] = "hybrid"
    cases.append(
        {
            "id": "generated-route",
            "request": "review:generated-route",
            "expected_action": "extend",
            "expected_capabilities": [],
        }
    )
    monkeypatch.setattr(
        router_core,
        "resolve_request",
        lambda *args, **kwargs: SimpleNamespace(
            action=args[0].split(":", 1)[0],
            primary_capability="routing-governance",
            secondary_capabilities=[],
        ),
    )

    report = router_core.evaluate_bundle(bundle, tmp_path)

    assert report["case_count"] == 30
    assert report["status"] == "pass"
    assert len(report["per_case_results"]) == 31


@pytest.mark.parametrize(
    ("threshold_name", "floor"),
    (
        ("top1_accuracy_threshold", 0.85),
        ("top1_capability_accuracy_threshold", 0.85),
        ("review_precision_threshold", 0.90),
        ("review_recall_threshold", 1.0),
        ("minimum_capability_coverage_ratio", 0.80),
        ("secondary_contract_accuracy_threshold", 1.0),
    ),
)
def test_ratio_threshold_config_accepts_policy_floor(
    tmp_path: Path,
    threshold_name: str,
    floor: float,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation[threshold_name] = floor
    passing_metrics = _metrics()
    evaluation["attestation"] = make_evaluation_attestation(
        bundle, passing_metrics
    )

    decision = policy_for_bundle(bundle)

    assert decision.passed is True
    assert decision.enforcement_mode == "normal"


def test_schema_v1_missing_threshold_config_uses_runtime_defaults(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    for key in (*RATIO_THRESHOLD_CONFIG_KEYS, "minimum_case_count"):
        evaluation.pop(key, None)
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())

    decision = policy_for_bundle(bundle)

    assert decision.passed is True
    assert decision.enforcement_mode == "normal"
    assert decision.reasons == ()


def _bundle(tmp_path: Path) -> tuple[dict[str, object], Path]:
    bundle_root = tmp_path / "router-bundle"
    marker = bundle_root / "references" / "module-map.yaml"
    marker.parent.mkdir(parents=True)
    marker.write_text("modules: []\n", encoding="utf-8")
    module = {
        "id": "module-routing-governance-tooling",
        "path": "tools/router",
        "layer": "governance",
        "domain": "routing-governance",
        "purpose": "Repository routing tooling",
        "owner": "capability-steward:routing-governance",
        "public_api": "router_core.py",
    }
    capability = {
        "id": "routing-governance",
        "name": "Routing Governance",
        "status": "stable",
        "maturity": "curated",
        "stage": "stable",
        "source_of_truth": "profile",
        "intent_keywords": ["routing governance", "routing policy"],
        "business_intents": ["maintain repository routing policy"],
        "scope": {"domains": ["routing-governance"], "layers": ["governance"]},
        "owner_modules": ["tools/router"],
        "public_entries": ["tools/router/router_core.py"],
        "extension_points": ["tools/router"],
        "route_defaults": {"preferred_action": "extend"},
        "contracts": ["No product authority"],
        "related_tests": [],
        "test_bindings": [],
        "forbidden_patterns": [],
        "dependent_modules": [],
        "anti_patterns": [],
        "lifecycle": {"definition_version": "2.0", "status": "stable", "stage": "stable"},
    }
    categories = (
        ("positive_reuse", "reuse"),
        ("positive_extend", "extend"),
        ("extract_boundary", "extract"),
        ("review_veto", "review"),
        ("false_positive_regression", "extend"),
        ("false_negative_regression", "review"),
    )
    curated_cases = [
        {
            "id": f"curated-{index}",
            "calibration_category": categories[index % len(categories)][0],
            "expected_action": categories[index % len(categories)][1],
            "expected_capabilities": ["routing-governance"],
            "expected_primary_capability": "routing-governance",
            "risk_level": "high",
        }
        for index in range(30)
    ]
    curated_case_ids = [case["id"] for case in curated_cases]
    bundle: dict[str, object] = {
        "root": bundle_root,
        "config": {
            "repo_stage": "structured",
            "freshness_windows": {"module_map_days": 30},
            "evaluation": {
                "enforcement_enabled": True,
                "top1_accuracy_threshold": 0.85,
                "review_precision_threshold": 0.90,
                "minimum_capability_coverage_ratio": 0.80,
                "minimum_case_count": 30,
            },
        },
        "capability_catalog": {"capabilities": [capability]},
        "module_map": {"modules": [module]},
        "ownership": {
            "owners": [
                {
                    "scope": "capability",
                    "target": "routing-governance",
                    "primary": "routing-maintainers",
                    "reviewers": ["routing-architecture-reviewers"],
                    "provisional": False,
                }
            ]
        },
        "change_rules": {
            "confidence": {"auto_route_threshold": 0.78, "guarded_route_threshold": 0.58},
            "high_risk_capability_ids": [],
        },
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "tools/router/**",
                    "capabilities": ["routing-governance"],
                }
            ]
        },
        "evaluation_set": {
            "mode": "curated",
            "curated_case_ids": curated_case_ids,
            "cases": curated_cases,
        },
    }
    return bundle, bundle_root


def test_missing_attestation_forces_write_route_to_review(tmp_path: Path) -> None:
    bundle, bundle_root = _bundle(tmp_path)
    request = "Extend routing governance tooling with evaluation metrics."
    paths = ["tools/router/router_core.py"]

    advisory = router_core.resolve_request(
        request,
        paths,
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )
    enforced = router_core.resolve_request(request, paths, bundle, bundle_root)

    assert advisory.action == "extend"
    assert enforced.action == "review"
    assert enforced.block_reason["code"] == "evaluation_threshold_not_met"
    assert enforced.allowed_write_paths == []
    assert "**" in enforced.forbidden_write_paths


def test_valid_attestation_preserves_advisory_action_and_stale_digest_blocks(
    tmp_path: Path,
) -> None:
    bundle, bundle_root = _bundle(tmp_path)
    evaluation = bundle["config"]["evaluation"]
    evaluation["attestation"] = make_evaluation_attestation(bundle, _metrics())
    request = "Extend routing governance tooling with evaluation metrics."
    paths = ["tools/router/router_core.py"]

    valid = router_core.resolve_request(request, paths, bundle, bundle_root)
    bundle["evaluation_set"]["cases"].append({"id": "changed-input"})
    stale = router_core.resolve_request(request, paths, bundle, bundle_root)

    assert valid.action == "extend"
    assert stale.action == "review"
    assert stale.block_reason["code"] == "evaluation_threshold_not_met"


def test_evaluation_engine_version_change_invalidates_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _ = _bundle(tmp_path)
    attestation = make_evaluation_attestation(bundle, _metrics())
    bundle["config"]["evaluation"]["attestation"] = attestation
    current_version = evaluation_policy.EVALUATION_ENGINE_VERSION

    assert attestation["evaluation_engine_version"] == current_version
    monkeypatch.setattr(
        evaluation_policy,
        "EVALUATION_ENGINE_VERSION",
        current_version + 1,
    )

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (
        "evaluation_attestation_engine_version_mismatch",
    )
    assert evaluation_input_digest(bundle) != attestation["input_digest"]


def test_legacy_attestation_without_engine_version_is_review_only(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    attestation = make_evaluation_attestation(bundle, _metrics())
    attestation.pop("evaluation_engine_version")
    bundle["config"]["evaluation"]["attestation"] = attestation

    decision = policy_for_bundle(bundle)

    assert decision.passed is False
    assert decision.enforcement_mode == "review_only"
    assert decision.reasons == (
        "evaluation_attestation_engine_version_missing",
    )


def test_untrusted_capability_owner_blocks_advisory_write_route(
    tmp_path: Path,
) -> None:
    bundle, bundle_root = _bundle(tmp_path)
    bundle["ownership"] = {
        "owners": [
            {
                "scope": "capability",
                "target": "routing-governance",
                "primary": "UNKNOWN",
                "reviewers": ["UNKNOWN"],
                "provisional": True,
            }
        ]
    }

    decision = router_core.resolve_request(
        "Extend routing governance tooling with evaluation metrics.",
        ["tools/router/router_core.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.action == "review"
    assert decision.block_reason["code"] == "unclear_owner"
    assert decision.allowed_write_paths == []
    assert "**" in decision.forbidden_write_paths
    assert any("owner governance" in reason for reason in decision.veto_reasons)


def test_evaluation_digest_changes_with_capability_ownership(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path)
    bundle["ownership"] = {
        "owners": [
            {
                "scope": "capability",
                "target": "routing-governance",
                "primary": "routing-maintainers",
                "reviewers": ["architecture-reviewers"],
                "provisional": False,
            }
        ]
    }
    changed = deepcopy(bundle)
    changed["ownership"]["owners"][0]["reviewers"] = ["security-reviewers"]

    assert evaluation_input_digest(bundle) != evaluation_input_digest(changed)


def test_evaluation_digest_changes_with_path_to_capability_mapping(
    tmp_path: Path,
) -> None:
    bundle, _ = _bundle(tmp_path)
    changed = deepcopy(bundle)
    changed["path_to_capability_map"]["path_index"][0]["path_pattern"] = (
        "tools/other-router/**"
    )

    assert evaluation_input_digest(bundle) != evaluation_input_digest(changed)


def test_evaluation_digest_changes_with_repo_stage(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path)
    changed = deepcopy(bundle)
    changed["config"]["repo_stage"] = "governed"

    assert evaluation_input_digest(bundle) != evaluation_input_digest(changed)


def test_evaluation_digest_changes_with_high_risk_keywords(tmp_path: Path) -> None:
    bundle, _ = _bundle(tmp_path)
    changed = deepcopy(bundle)
    changed["config"]["high_risk_keywords"] = ["release-control"]

    assert evaluation_input_digest(bundle) != evaluation_input_digest(changed)


def test_schema_v1_missing_route_config_matches_runtime_defaults(
    tmp_path: Path,
) -> None:
    legacy, _ = _bundle(tmp_path)
    legacy["config"].pop("repo_stage")
    explicit_defaults = deepcopy(legacy)
    explicit_defaults["config"].update(
        {"repo_stage": "emerging", "high_risk_keywords": []}
    )

    assert evaluation_input_digest(legacy) == evaluation_input_digest(
        explicit_defaults
    )
