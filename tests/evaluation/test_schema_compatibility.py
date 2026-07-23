from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


SKILL_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from router_support.evaluation_policy import (  # noqa: E402
    EVALUATION_ENGINE_VERSION,
    policy_for_bundle,
)


def _schema(name: str) -> dict:
    return json.loads((SKILL_ROOT / "schemas" / name).read_text(encoding="utf-8"))


def test_evaluation_engine_version_matches_architecture_manifest() -> None:
    manifest = json.loads(
        (SKILL_ROOT / "skill-version.json").read_text(encoding="utf-8")
    )

    assert (
        EVALUATION_ENGINE_VERSION
        == manifest["architecture_governance_api_version"]
    )


def test_schema_v1_bundle_remains_readable_without_v030_evaluation_fields() -> None:
    config = yaml.safe_load(
        (SKILL_ROOT / "examples" / "bundle" / "router-config.yaml").read_text(
            encoding="utf-8"
        )
    )
    config["evaluation"] = {}
    original = json.loads(json.dumps(config))

    errors = sorted(
        Draft202012Validator(_schema("router-config.schema.json")).iter_errors(config),
        key=lambda error: list(error.path),
    )
    policy = policy_for_bundle({"config": config})

    assert errors == []
    assert config == original
    assert policy.passed is False
    assert policy.enforcement_mode == "review_only"


def test_current_output_examples_validate_against_current_report_schemas() -> None:
    pairs = (
        ("resolve-entry.pass.json", "route-decision-report.schema.json"),
        ("run-evaluation.pass.json", "evaluation-summary.schema.json"),
        ("check-structure.pass.json", "guardrail-report.schema.json"),
    )
    failures: dict[str, list[str]] = {}
    for output_name, schema_name in pairs:
        payload = json.loads(
            (SKILL_ROOT / "examples" / "outputs" / output_name).read_text(
                encoding="utf-8"
            )
        )
        errors = Draft202012Validator(_schema(schema_name)).iter_errors(payload)
        messages = sorted(error.message for error in errors)
        if messages:
            failures[output_name] = messages

    assert failures == {}


def test_ownership_schema_rejects_non_string_identities() -> None:
    ownership = {
        "schema_version": 1,
        "generated_at": "2026-07-23T00:00:00Z",
        "generated_by": "test",
        "source_repository": "fixture",
        "source_commit": None,
        "owners": [
            {
                "scope": "capability",
                "target": "routing-governance",
                "primary": True,
                "reviewers": [{"team": "security"}],
                "provisional": False,
            }
        ],
    }

    errors = list(
        Draft202012Validator(_schema("ownership.schema.json")).iter_errors(
            ownership
        )
    )

    assert errors


def test_evaluation_schemas_expose_optional_v030_policy_contract() -> None:
    config = _schema("router-config.schema.json")
    summary = _schema("evaluation-summary.schema.json")
    legacy_required_config = {
        "top1_accuracy_threshold",
        "review_precision_threshold",
        "minimum_capability_coverage_ratio",
        "minimum_case_count",
    }
    policy_config = {
        "enforcement_enabled",
        "top1_capability_accuracy_threshold",
        "review_recall_threshold",
        "secondary_contract_accuracy_threshold",
        "mode",
    }

    required = set(config["properties"]["evaluation"].get("required", []))
    properties = set(config["properties"]["evaluation"]["properties"])
    attestation = config["properties"]["evaluation"]["properties"][
        "attestation"
    ]
    assert legacy_required_config | policy_config <= properties
    assert (legacy_required_config | policy_config).isdisjoint(required)
    assert "evaluation_engine_version" in attestation["properties"]
    assert "evaluation_engine_version" not in attestation.get("required", [])
    assert "enforcement_mode" in summary["required"]
    assert "enforcement_mode" in summary["properties"]
    assert "secondary_contract_accuracy" in summary["required"]
    assert "strict_secondary_case_count" in summary["required"]
