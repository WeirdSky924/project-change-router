from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class EvaluationThresholds:
    action_accuracy: float = 0.85
    capability_accuracy: float = 0.85
    review_precision: float = 0.90
    review_recall: float = 1.0
    capability_coverage: float = 0.80
    secondary_contract_accuracy: float = 1.0
    minimum_cases: int = 30


@dataclass(frozen=True)
class EvaluationPolicyDecision:
    passed: bool
    enforcement_mode: str
    reasons: tuple[str, ...]


_RATIO_THRESHOLD_SPECS = (
    ("top1_accuracy_threshold", "action_accuracy", 0.85),
    ("top1_capability_accuracy_threshold", "capability_accuracy", 0.85),
    ("review_precision_threshold", "review_precision", 0.90),
    ("review_recall_threshold", "review_recall", 1.0),
    (
        "minimum_capability_coverage_ratio",
        "capability_coverage",
        0.80,
    ),
    (
        "secondary_contract_accuracy_threshold",
        "secondary_contract_accuracy",
        1.0,
    ),
)

_REQUIRED_CALIBRATION_CATEGORIES = {
    "positive_reuse",
    "positive_extend",
    "extract_boundary",
    "review_veto",
    "false_positive_regression",
    "false_negative_regression",
}

# Bump whenever route or evaluation semantics can change attested predictions.
EVALUATION_ENGINE_VERSION = 1


def _calibration_category_is_consistent(
    case: Mapping[str, object], category: object
) -> bool:
    action = case.get("expected_action")
    if category == "positive_reuse":
        return action == "reuse"
    if category == "positive_extend":
        return action == "extend"
    if category == "extract_boundary":
        return action == "extract"
    if category == "review_veto":
        return action == "review" and case.get("risk_level") in {"high", "critical"}
    if category == "false_positive_regression":
        return action in {"reuse", "extend", "extract", "new"}
    if category == "false_negative_regression":
        return action == "review"
    return False


def _ratio_threshold(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _threshold_validation_reasons(
    thresholds: EvaluationThresholds,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for config_name, attribute_name, floor in _RATIO_THRESHOLD_SPECS:
        value = _ratio_threshold(getattr(thresholds, attribute_name))
        if value is None:
            reasons.append(f"evaluation_threshold_invalid:{config_name}")
        elif value < floor:
            reasons.append(f"evaluation_threshold_below_floor:{config_name}")
    if _positive_integer(thresholds.minimum_cases) is None:
        reasons.append("evaluation_threshold_invalid:minimum_case_count")
    elif thresholds.minimum_cases < 30:
        reasons.append("evaluation_threshold_below_floor:minimum_case_count")
    return tuple(reasons)


def _thresholds_from_config(
    evaluation: Mapping[str, object],
) -> tuple[EvaluationThresholds | None, tuple[str, ...]]:
    ratios: dict[str, float] = {}
    invalid_reasons: list[str] = []
    for config_name, attribute_name, default in _RATIO_THRESHOLD_SPECS:
        value = _ratio_threshold(evaluation.get(config_name, default))
        if value is None:
            invalid_reasons.append(
                f"evaluation_threshold_invalid:{config_name}"
            )
        elif value < default:
            invalid_reasons.append(
                f"evaluation_threshold_below_floor:{config_name}"
            )
        else:
            ratios[attribute_name] = value

    minimum_cases = _positive_integer(
        evaluation.get("minimum_case_count", 30)
    )
    if minimum_cases is None:
        invalid_reasons.append(
            "evaluation_threshold_invalid:minimum_case_count"
        )
    elif minimum_cases < 30:
        invalid_reasons.append(
            "evaluation_threshold_below_floor:minimum_case_count"
        )
    if invalid_reasons:
        return None, tuple(invalid_reasons)

    return (
        EvaluationThresholds(
            action_accuracy=ratios["action_accuracy"],
            capability_accuracy=ratios["capability_accuracy"],
            review_precision=ratios["review_precision"],
            review_recall=ratios["review_recall"],
            capability_coverage=ratios["capability_coverage"],
            secondary_contract_accuracy=ratios[
                "secondary_contract_accuracy"
            ],
            minimum_cases=minimum_cases,
        ),
        (),
    )


def evaluate_policy(
    metrics: Mapping[str, object],
    thresholds: EvaluationThresholds,
) -> EvaluationPolicyDecision:
    threshold_reasons = _threshold_validation_reasons(thresholds)
    if threshold_reasons:
        return EvaluationPolicyDecision(
            False,
            "review_only",
            threshold_reasons,
        )
    values = {
        "top1_action_accuracy": _ratio_threshold(metrics.get("top1_action_accuracy")),
        "top1_capability_accuracy": _ratio_threshold(metrics.get("top1_capability_accuracy")),
        "review_precision": _ratio_threshold(metrics.get("review_precision")),
        "review_recall": _ratio_threshold(metrics.get("review_recall")),
        "capability_coverage_ratio": _ratio_threshold(metrics.get("capability_coverage_ratio")),
        "secondary_contract_accuracy": _ratio_threshold(metrics.get("secondary_contract_accuracy")),
        "case_count": _positive_integer(metrics.get("case_count")),
        "strict_secondary_case_count": _nonnegative_integer(
            metrics.get("strict_secondary_case_count")
        ),
    }
    limits = {
        "top1_action_accuracy": thresholds.action_accuracy,
        "top1_capability_accuracy": thresholds.capability_accuracy,
        "review_precision": thresholds.review_precision,
        "review_recall": thresholds.review_recall,
        "capability_coverage_ratio": thresholds.capability_coverage,
        "secondary_contract_accuracy": thresholds.secondary_contract_accuracy,
        "case_count": float(thresholds.minimum_cases),
        "strict_secondary_case_count": 0,
    }
    reasons = tuple(
        f"{name} below {limits[name]}"
        if value is not None
        else f"{name} missing or invalid"
        for name, value in values.items()
        if value is None or value < limits[name]
    )
    return EvaluationPolicyDecision(
        passed=not reasons,
        enforcement_mode="normal" if not reasons else "review_only",
        reasons=reasons,
    )


def evaluate_configured_policy(
    metrics: Mapping[str, object],
    evaluation: Mapping[str, object],
    evaluation_set: Mapping[str, object] | None = None,
    requires_secondary_evidence: bool = False,
    valid_capability_ids: set[str] | None = None,
) -> EvaluationPolicyDecision:
    thresholds, threshold_reasons = _thresholds_from_config(evaluation)
    if thresholds is None:
        return EvaluationPolicyDecision(False, "review_only", threshold_reasons)
    if evaluation_set is not None:
        mode = evaluation_set.get("mode")
        if mode not in {"curated", "hybrid"}:
            return EvaluationPolicyDecision(
                False, "review_only", ("evaluation_cases_not_curated",)
            )
        raw_ids = evaluation_set.get("curated_case_ids")
        cases = evaluation_set.get("cases")
        if (
            not isinstance(raw_ids, list)
            or any(not isinstance(case_id, str) or not case_id.strip() for case_id in raw_ids)
            or len(set(raw_ids)) != len(raw_ids)
            or not isinstance(cases, list)
        ):
            return EvaluationPolicyDecision(
                False, "review_only", ("evaluation_case_provenance_invalid",)
            )
        curated_cases: list[Mapping[str, object]] = []
        for case_id in raw_ids:
            matches = [
                case
                for case in cases
                if isinstance(case, Mapping) and case.get("id") == case_id
            ]
            if len(matches) != 1:
                return EvaluationPolicyDecision(
                    False, "review_only", ("evaluation_case_provenance_invalid",)
                )
            curated_cases.append(matches[0])
        if any(
            not _calibration_category_is_consistent(
                case, case.get("calibration_category")
            )
            for case in curated_cases
        ):
            return EvaluationPolicyDecision(
                False, "review_only", ("evaluation_case_category_invalid",)
            )
        expected_primary = [
            case.get("expected_primary_capability") for case in curated_cases
        ]
        if any(
            not isinstance(capability, str) or not capability.strip()
            for capability in expected_primary
        ):
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_case_capability_expectation_missing",),
            )
        if valid_capability_ids is not None and any(
            str(capability) not in valid_capability_ids
            for capability in expected_primary
        ):
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_case_primary_capability_invalid",),
            )
        categories = {
            str(case["calibration_category"]) for case in curated_cases
        }
        missing_categories = sorted(
            _REQUIRED_CALIBRATION_CATEGORIES - categories
        )
        if missing_categories:
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_case_categories_missing:" + ",".join(missing_categories),),
            )
        strict_cases = [
            case
            for case in curated_cases
            if case.get("secondary_match") == "exact"
            and isinstance(case.get("expected_secondary_capabilities"), list)
            and any(
                isinstance(capability, str) and capability.strip()
                for capability in case.get("expected_secondary_capabilities", [])
            )
        ]
        if valid_capability_ids is not None and any(
            any(
                not isinstance(capability, str)
                or capability not in valid_capability_ids
                or capability == case.get("expected_primary_capability")
                for capability in case.get("expected_secondary_capabilities", [])
            )
            for case in strict_cases
        ):
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_case_secondary_capability_invalid",),
            )
        strict_count = _nonnegative_integer(
            metrics.get("strict_secondary_case_count")
        )
        if strict_count != len(strict_cases):
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_secondary_contract_evidence_mismatch",),
            )
        if requires_secondary_evidence and not strict_cases:
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_secondary_contract_evidence_missing",),
            )
        if len(raw_ids) < thresholds.minimum_cases:
            return EvaluationPolicyDecision(
                False,
                "review_only",
                (f"curated_case_count below {thresholds.minimum_cases}",),
            )
        if _positive_integer(metrics.get("case_count")) != len(raw_ids):
            return EvaluationPolicyDecision(
                False,
                "review_only",
                ("evaluation_case_count_provenance_mismatch",),
            )
    return evaluate_policy(metrics, thresholds)


def evaluation_input_digest(bundle: Mapping[str, object]) -> str:
    change_rules = bundle.get("change_rules", {})
    semantic_change_rules: dict[str, object] = {}
    if isinstance(change_rules, Mapping):
        operational_keys = {
            "reuse_scan_budget",
            "reuse_scan_runtime",
            "reuse_scan_retention",
        }
        semantic_change_rules = {
            str(key): value
            for key, value in change_rules.items()
            if key not in operational_keys
        }
        guardrails = semantic_change_rules.get("guardrails")
        if isinstance(guardrails, Mapping):
            semantic_change_rules["guardrails"] = {
                str(key): value
                for key, value in guardrails.items()
                if key not in operational_keys
            }
    config = bundle.get("config", {})
    route_config = config if isinstance(config, Mapping) else {}
    route_semantic_config = {
        "repo_stage": route_config.get("repo_stage", "emerging"),
        "high_risk_keywords": route_config.get("high_risk_keywords", []),
    }
    payload = {
        "evaluation_engine_version": EVALUATION_ENGINE_VERSION,
        "route_semantic_config": route_semantic_config,
        "capability_catalog": bundle.get("capability_catalog", {}),
        "module_map": bundle.get("module_map", {}),
        "ownership": bundle.get("ownership", {}),
        "change_rules": semantic_change_rules,
        "path_to_capability_map": bundle.get("path_to_capability_map", {}),
        "evaluation_set": bundle.get("evaluation_set", {}),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_evaluation_attestation(
    bundle: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    selected_metrics = {
        name: metrics.get(name)
        for name in (
            "top1_action_accuracy",
            "top1_capability_accuracy",
            "review_precision",
            "review_recall",
            "capability_coverage_ratio",
            "secondary_contract_accuracy",
            "case_count",
            "strict_secondary_case_count",
        )
    }
    return {
        "evaluation_engine_version": EVALUATION_ENGINE_VERSION,
        "input_digest": evaluation_input_digest(bundle),
        "metrics": selected_metrics,
    }


def policy_for_bundle(bundle: Mapping[str, object]) -> EvaluationPolicyDecision:
    config = bundle.get("config", {})
    evaluation = config.get("evaluation", {}) if isinstance(config, Mapping) else {}
    if not isinstance(evaluation, Mapping):
        return EvaluationPolicyDecision(
            False, "review_only", ("evaluation_config_missing",)
        )
    if evaluation.get("enforcement_enabled") is not True:
        return EvaluationPolicyDecision(
            False, "review_only", ("evaluation_enforcement_disabled",)
        )
    thresholds, threshold_reasons = _thresholds_from_config(evaluation)
    if thresholds is None:
        return EvaluationPolicyDecision(
            False,
            "review_only",
            threshold_reasons,
        )
    attestation = evaluation.get("attestation")
    if not isinstance(attestation, Mapping):
        return EvaluationPolicyDecision(False, "review_only", ("evaluation_attestation_missing",))
    attested_engine_version = attestation.get("evaluation_engine_version")
    if attested_engine_version is None:
        return EvaluationPolicyDecision(
            False,
            "review_only",
            ("evaluation_attestation_engine_version_missing",),
        )
    if (
        type(attested_engine_version) is not int
        or attested_engine_version != EVALUATION_ENGINE_VERSION
    ):
        return EvaluationPolicyDecision(
            False,
            "review_only",
            ("evaluation_attestation_engine_version_mismatch",),
        )
    if attestation.get("input_digest") != evaluation_input_digest(bundle):
        return EvaluationPolicyDecision(False, "review_only", ("evaluation_attestation_digest_mismatch",))
    metrics = attestation.get("metrics")
    if not isinstance(metrics, Mapping):
        return EvaluationPolicyDecision(False, "review_only", ("evaluation_attestation_metrics_missing",))
    evaluation_set = bundle.get("evaluation_set", {})
    catalog = bundle.get("capability_catalog", {})
    capabilities = catalog.get("capabilities", []) if isinstance(catalog, Mapping) else []
    catalog_ids = {
        str(capability.get("id"))
        for capability in capabilities
        if isinstance(capability, Mapping) and capability.get("id")
    }
    stable_ids = {
        str(capability.get("id"))
        for capability in capabilities
        if isinstance(capability, Mapping)
        and capability.get("id")
        and (
            str(capability.get("status", "")).lower() == "stable"
            or str(capability.get("stage", "")).lower()
            in {"stable", "governed-capability"}
        )
    }
    return evaluate_configured_policy(
        metrics,
        evaluation,
        evaluation_set if isinstance(evaluation_set, Mapping) else {},
        requires_secondary_evidence=len(stable_ids) > 1,
        valid_capability_ids=catalog_ids,
    )
