from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from router_support.generated_output_baseline.contract import json_safe_diagnostic


PCR_BUNDLE_ARTIFACTS = {
    "capability_catalog": "project-change-router/references/capability-catalog.yaml",
    "module_map": "project-change-router/references/module-map.yaml",
    "ownership": "project-change-router/references/ownership.yaml",
    "change_rules": "project-change-router/references/change-rules.yaml",
    "path_to_capability_map": "project-change-router/references/path-to-capability-map.yaml",
    "exception_registry": "project-change-router/references/exception-registry.yaml",
    "evaluation_set": "project-change-router/references/evaluation-set.yaml",
}
GENERATED_OUTPUT_MODE = "pinned-idempotent-v1"
GENERATOR_ID = "pcr-router-bundle-v1"
RULE_FIELDS = frozenset({
    "id",
    "mode",
    "generator_id",
    "canonical_source",
    "source_commit",
    "owner",
    "reason",
    "exit_stage",
    "exit_condition",
    "initialization_authorization",
    "artifacts",
    "fingerprint",
})
ARTIFACT_FIELDS = frozenset({
    "bundle_key",
    "source_commit",
    "semantic_digest",
    "canonical_text_digest",
    "line_count",
})


@dataclass(frozen=True)
class GeneratedOutputVerification:
    verified_paths: frozenset[str]
    findings: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...]


def finding(
    code: str,
    source: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return json_safe_diagnostic({
        "severity": "P0",
        "rule": "generated-output-baseline-diagnostic",
        "source": source,
        "blocking": True,
        "baseline_status": "new",
        "diagnostic_code": code,
        "message": message,
        **details,
    })
