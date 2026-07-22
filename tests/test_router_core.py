from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
import reuse_runtime


def create_java_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "java-repo"
    (repo / "backend" / "security" / "src" / "main" / "java" / "com" / "example" / "security").mkdir(parents=True)
    (repo / "backend" / "billing" / "src" / "main" / "java" / "com" / "example" / "billing").mkdir(parents=True)
    (repo / "pom.xml").write_text(
        "<project><modules><module>backend/security</module><module>backend/billing</module></modules></project>",
        encoding="utf-8",
    )
    (repo / "backend" / "security" / "pom.xml").write_text(
        "<project><artifactId>security</artifactId><dependencies><dependency><artifactId>billing</artifactId></dependency></dependencies></project>",
        encoding="utf-8",
    )
    (repo / "backend" / "billing" / "pom.xml").write_text(
        "<project><artifactId>billing</artifactId></project>",
        encoding="utf-8",
    )
    (repo / "backend" / "security" / "src" / "main" / "java" / "com" / "example" / "security" / "TokenService.java").write_text(
        "package com.example.security; import com.example.billing.InvoiceService; class TokenService {}",
        encoding="utf-8",
    )
    (repo / "backend" / "billing" / "src" / "main" / "java" / "com" / "example" / "billing" / "InvoiceService.java").write_text(
        "package com.example.billing; public class InvoiceService {}",
        encoding="utf-8",
    )
    return repo


def create_python_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "python-repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'python-repo'\nversion = '0.1.0'\n", encoding="utf-8")
    (repo / "services" / "billing").mkdir(parents=True)
    (repo / "services" / "billing" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "billing" / "service.py").write_text(
        "def bill_customer():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (repo / "services" / "payments").mkdir(parents=True)
    (repo / "services" / "payments" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "payments" / "webhook.py").write_text(
        "from services.billing.service import bill_customer\n\n\ndef handle_webhook():\n    return bill_customer()\n",
        encoding="utf-8",
    )
    return repo


def create_typescript_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ts-repo"
    repo.mkdir(parents=True)
    (repo / "package.json").write_text(
        '{"name":"ts-repo","private":true,"workspaces":["packages/*"]}',
        encoding="utf-8",
    )
    (repo / "packages" / "billing" / "src").mkdir(parents=True)
    (repo / "packages" / "checkout" / "src").mkdir(parents=True)
    (repo / "packages" / "billing" / "package.json").write_text(
        '{"name":"@acme/billing","version":"1.0.0"}',
        encoding="utf-8",
    )
    (repo / "packages" / "checkout" / "package.json").write_text(
        '{"name":"@acme/checkout","version":"1.0.0","dependencies":{"@acme/billing":"1.0.0"}}',
        encoding="utf-8",
    )
    (repo / "packages" / "billing" / "src" / "index.ts").write_text(
        "export function chargeCustomer() { return true; }\n",
        encoding="utf-8",
    )
    (repo / "packages" / "checkout" / "src" / "index.ts").write_text(
        "import { chargeCustomer } from '@acme/billing';\nexport function checkout() { return chargeCustomer(); }\n",
        encoding="utf-8",
    )
    return repo


def create_mixed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "mixed-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'mixed-repo'\nversion = '0.1.0'\n", encoding="utf-8")
    (repo / "services" / "catalog").mkdir(parents=True)
    (repo / "services" / "catalog" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "catalog" / "service.py").write_text("def list_items():\n    return []\n", encoding="utf-8")
    (repo / "packages" / "web" / "src").mkdir(parents=True)
    (repo / "packages" / "web" / "package.json").write_text(
        '{"name":"@acme/web","version":"1.0.0"}',
        encoding="utf-8",
    )
    (repo / "packages" / "web" / "src" / "index.ts").write_text("export const screen = 'ok';\n", encoding="utf-8")
    return repo


def create_profiled_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "profiled-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "services" / "payments").mkdir(parents=True)
    (repo / "services" / "payments" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "payments" / "service.py").write_text("def charge():\n    return True\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: acme
capabilities:
  - id: payment-core
    name: Payment Core
    path_patterns:
      - "services/payments/**"
    keywords: ["payment", "charge", "refund"]
    aliases: ["payments"]
    route_defaults:
      preferred_action: reuse
ownership_rules:
  - path_patterns: ["services/payments/**"]
    owner: payments-team
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def create_composite_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "composite-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'composite-repo'\nversion = '0.1.0'\n", encoding="utf-8")
    (repo / "services" / "billing").mkdir(parents=True)
    (repo / "services" / "billing" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "billing" / "service.py").write_text("def invoice():\n    return True\n", encoding="utf-8")
    (repo / "services" / "shipping").mkdir(parents=True)
    (repo / "services" / "shipping" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "shipping" / "service.py").write_text("def ship():\n    return True\n", encoding="utf-8")
    (repo / "frontend" / "billing").mkdir(parents=True)
    (repo / "frontend" / "billing" / "view.ts").write_text("export const invoiceView = true;\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: composite
capabilities:
  - id: billing-core
    name: Billing Core
    path_patterns: ["services/billing/**"]
    keywords: ["billing", "invoice"]
    public_entries: ["services/billing/service.py"]
    stage: stable
    status: stable
  - id: billing-ui
    name: Billing UI
    path_patterns: ["frontend/**"]
    keywords: ["billing", "invoice", "ui", "display"]
    public_entries: ["frontend/billing/view.ts"]
    stage: stable
    status: stable
ownership_rules:
  - path_patterns: ["services/billing/**"]
    owner: billing-core-team
  - path_patterns: ["frontend/**"]
    owner: frontend-team
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def create_seed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "seed-repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return repo


def create_emerging_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "emerging-repo"
    repo.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'emerging-repo'\nversion = '0.1.0'\n", encoding="utf-8")
    (repo / "services" / "orders").mkdir(parents=True)
    (repo / "services" / "orders" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "orders" / "service.py").write_text("def place_order():\n    return True\n", encoding="utf-8")
    (repo / "services" / "notifications").mkdir(parents=True)
    (repo / "services" / "notifications" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "notifications" / "service.py").write_text("def notify():\n    return True\n", encoding="utf-8")
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_orders.py").write_text("def test_orders():\n    assert True\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: emerging
ownership_rules:
  - path_patterns: ["services/orders/**"]
    owner: provisional:orders
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return repo


def test_bootstrap_bundle_for_java_repo(tmp_path: Path) -> None:
    repo = create_java_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    assert bundle_root.exists()
    assert (bundle_root / "router-config.yaml").exists()
    modules = bundle["module_map"]["modules"]
    assert {module["path"] for module in modules} == {"backend/billing", "backend/security"}
    capabilities = bundle["capability_catalog"]["capabilities"]
    assert {cap["id"] for cap in capabilities} >= {"billing", "security"}


def test_python_repo_root_detection_and_resolution(tmp_path: Path) -> None:
    repo = create_python_repo(tmp_path)
    nested = repo / "services" / "payments"
    assert router_core.repo_root_from(nested) == repo.resolve()
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Extend the payment webhook behavior with a new validation step",
        ["services/payments/webhook.py"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.primary_capability in {"payments", "billing"}
    assert decision.action in {"extend", "review", "reuse"}
    assert decision.required_reads
    assert decision.routing_confidence >= 0.0
    assert decision.decision_confidence >= 0.0
    assert decision.routing_confidence_level in {"low", "medium", "high"}
    assert decision.decision_confidence_level in {"low", "medium", "high"}
    assert isinstance(decision.decision_basis, str)
    assert decision.confidence_level in {"low", "medium", "high"}
    assert isinstance(decision.confidence_reasons, list)
    assert isinstance(decision.positive_signals, dict)
    assert isinstance(decision.negative_signals, dict)
    assert isinstance(decision.risk_signals, dict)
    assert isinstance(decision.recommended_next_action, str)
    assert isinstance(decision.recommended_next_steps, list)
    assert isinstance(decision.why_not_actions, dict)
    assert isinstance(decision.block_reason, dict)
    assert isinstance(decision.missing_evidence, list)
    assert isinstance(decision.analysis_directions, list)
    assert isinstance(decision.safe_next_steps, list)
    assert isinstance(decision.suggested_questions, list)
    assert isinstance(decision.profile_repair_hints, list)
    assert isinstance(decision.override_requirements, list)
    assert isinstance(decision.allowed_write_paths, list)
    assert isinstance(decision.forbidden_write_paths, list)
    assert isinstance(decision.must_read_before_edit, list)
    assert isinstance(decision.post_change_closeout, list)
    assert isinstance(decision.composite_route, dict)
    assert isinstance(decision.capability_lifecycle_action, dict)
    assert isinstance(decision.evaluation_regression_hints, list)


def test_typescript_workspace_dependency_mapping(tmp_path: Path) -> None:
    repo = create_typescript_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    modules = {module["path"]: module for module in bundle["module_map"]["modules"]}
    assert "packages/billing" in modules
    assert "packages/checkout" in modules
    assert "packages/billing" in modules["packages/checkout"]["depends_on"]
    findings = router_core.gather_dependency_findings(repo, bundle)
    assert findings == []


def test_mixed_repo_discovers_multiple_languages(tmp_path: Path) -> None:
    repo = create_mixed_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    languages = set(bundle["config"]["supported_languages"])
    assert "python" in languages
    assert "typescript" in languages or "javascript" in languages
    repositories = bundle["config"]["repositories"]
    assert repositories


def test_profile_overrides_capability_and_owner(tmp_path: Path) -> None:
    repo = create_profiled_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    capabilities = {cap["id"]: cap for cap in bundle["capability_catalog"]["capabilities"]}
    assert "payment-core" in capabilities
    ownership_entries = [entry for entry in bundle["ownership"]["owners"] if entry["scope"] == "module"]
    assert any(entry["target"] == "services/payments" and entry["primary"] == "payments-team" for entry in ownership_entries)


def test_profile_can_declare_non_code_governance_capability(tmp_path: Path) -> None:
    repo = tmp_path / "skill-like-repo"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "resolve_entry.py").write_text("print('route')\n", encoding="utf-8")
    (repo / "examples" / "agent-workflows").mkdir(parents=True)
    (repo / "examples" / "agent-workflows" / "README.md").write_text("# Agent workflows\n", encoding="utf-8")
    (repo / "references").mkdir()
    (repo / "references" / "router-workflow.md").write_text("# Router workflow\n", encoding="utf-8")
    (repo / "README.md").write_text("# Skill repo\n", encoding="utf-8")
    (repo / "README.en.md").write_text("# Skill repo\n", encoding="utf-8")
    (repo / "SKILL.md").write_text("---\nname: x\ndescription: x\n---\n# X\n", encoding="utf-8")
    (repo / ".project-change-router.yaml").write_text(
        (SKILL_ROOT / "examples" / "profiles" / "skill-repo.project-change-router.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bundle = router_core.bootstrap_bundle(repo, write=True)
    capabilities = {cap["id"]: cap for cap in bundle["capability_catalog"]["capabilities"]}
    assert "skill-documentation" in capabilities
    assert "examples" in capabilities["skill-documentation"]["owner_modules"]
    decision = router_core.resolve_request(
        "Add more examples for agents to understand governance outputs.",
        ["examples/agent-workflows/README.md"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action in {"reuse", "extend"}
    assert decision.primary_capability == "skill-documentation"
    assert decision.routing_confidence_level == "high"


def test_seed_repo_stage_is_conservative(tmp_path: Path) -> None:
    repo = create_seed_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    assert bundle["config"]["repo_stage"] == "seed"
    decision = router_core.resolve_request(
        "Extend the existing platform capability with a new behavior",
        ["app.py"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action == "review"
    assert decision.routing_confidence_level == "low"
    assert decision.decision_confidence_level == "high"
    assert decision.decision_basis == "policy_guardrail"
    assert decision.veto_reasons
    assert decision.recommended_next_action == "request_human_review"
    assert decision.block_reason["code"] in {"early_repo_policy_guardrail", "missing_capability_candidate"}
    assert decision.allowed_write_paths == []
    assert "**" in decision.forbidden_write_paths
    assert decision.safe_next_steps
    assert decision.override_requirements
    assert decision.evaluation_regression_hints


def test_seed_repo_new_feature_prefers_new_over_review(tmp_path: Path) -> None:
    repo = create_seed_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Create a brand-new memory subsystem for this repository",
        ["memory.py"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action == "new"
    assert decision.routing_confidence_level == "low"
    assert decision.decision_confidence_level == "high"
    assert decision.decision_basis == "policy_guardrail"


def test_emerging_repo_limits_provisional_capabilities(tmp_path: Path) -> None:
    repo = create_emerging_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    assert bundle["config"]["repo_stage"] in {"seed", "emerging", "structured"}
    capabilities = bundle["capability_catalog"]["capabilities"]
    assert any(cap["stage"] in {"provisional", "candidate", "stable"} for cap in capabilities)
    decision = router_core.resolve_request(
        "Extract repeated order and notification logic into a shared reusable entry point",
        ["services/orders", "services/notifications"],
        bundle,
        repo / "project-change-router",
    )
    if bundle["config"]["repo_stage"] in {"seed", "emerging"}:
        assert decision.action in {"review", "new"}
    else:
        assert decision.action in {"review", "extract"}
    assert "extract" in decision.why_not_actions


def test_validate_bundle(tmp_path: Path) -> None:
    repo = create_typescript_repo(tmp_path)
    router_core.bootstrap_bundle(repo, write=True)
    errors = router_core.validate_bundle_files(repo / "project-change-router")
    assert errors == []
    assert (repo / "project-change-router" / "references" / "path-to-capability-map.yaml").exists()


def test_governance_audit_reports_path_index_and_profile_health(tmp_path: Path) -> None:
    repo = create_profiled_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    path_map = bundle["path_to_capability_map"]
    assert path_map["lookup"]["services/payments/**"] == ["payment-core"]
    report = router_core.audit_bundle_governance(repo, bundle)
    assert report["severity_counts"]["P0"] == 0
    assert report["summary"]["profile_backed_capability_count"] >= 1
    assert "findings" in report
    assert "repair_suggestions" in report


def test_governance_audit_flags_profile_catalog_drift(tmp_path: Path) -> None:
    repo = create_python_repo(tmp_path)
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: drift
capabilities:
  - id: ghost-capability
    name: Ghost Capability
    path_patterns: ["missing/**"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    bundle = router_core.bootstrap_bundle(repo, write=True)
    report = router_core.audit_bundle_governance(repo, bundle)
    assert report["status"] == "fail"
    assert any(finding["rule"] == "profile-capability-not-in-catalog" for finding in report["findings"])
    assert any(suggestion["kind"] == "profile_path_pattern_fix" for suggestion in report["repair_suggestions"])


def test_capability_lifecycle_changes_are_review_only(tmp_path: Path) -> None:
    repo = create_profiled_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Deprecate the existing payment-core capability and replace it with billing-runtime",
        ["services/payments/service.py"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action == "review"
    assert decision.block_reason["code"] == "capability_lifecycle_change"
    assert decision.capability_lifecycle_action["intent"] == "deprecate"
    assert decision.capability_lifecycle_action["review_required"] is True
    assert "superseded_by" in decision.capability_lifecycle_action["required_metadata"]
    assert decision.profile_repair_hints


def test_composite_route_metadata_marks_cross_stack_review(tmp_path: Path) -> None:
    repo = create_composite_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Modify billing invoice behavior and UI display together",
        ["services/billing/service.py", "frontend/billing/view.ts"],
        bundle,
        repo / "project-change-router",
    )
    assert decision.action == "review"
    assert decision.composite_route_required is True
    assert decision.coordination_required is True
    assert decision.composite_route["required"] is True
    assert decision.composite_route["primary"] == "billing-core"
    assert "billing-ui" in decision.composite_route["secondary"]
    assert decision.composite_route["coordination_policy"] == "review_before_write"
    assert {participant["capability"] for participant in decision.composite_route["participants"]} >= {"billing-core", "billing-ui"}
    assert decision.allowed_write_paths == []
    assert "**" in decision.forbidden_write_paths


def test_route_decision_report_schema_includes_guidance(tmp_path: Path) -> None:
    repo = create_seed_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    decision = router_core.resolve_request(
        "Extend the existing platform capability with a new behavior",
        ["app.py"],
        bundle,
        repo / "project-change-router",
    )
    errors = router_core.validate_against_schema(
        decision.to_dict(),
        SKILL_ROOT / "schemas" / "route-decision-report.schema.json",
    )
    assert errors == []


def test_governance_report_schema_includes_repair_suggestions(tmp_path: Path) -> None:
    repo = create_python_repo(tmp_path)
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: drift
capabilities:
  - id: ghost-capability
    name: Ghost Capability
    path_patterns: ["missing/**"]
""".strip()
        + "\n",
        encoding="utf-8",
    )
    bundle = router_core.bootstrap_bundle(repo, write=True)
    report = router_core.audit_bundle_governance(repo, bundle)
    errors = router_core.validate_against_schema(
        report,
        SKILL_ROOT / "schemas" / "governance-report.schema.json",
    )
    assert errors == []
    assert report["repair_suggestions"]


def test_evaluation_runs(tmp_path: Path) -> None:
    repo = create_java_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    summary = router_core.evaluate_bundle(bundle, repo)
    assert summary["case_count"] >= 12
    assert "top1_action_accuracy" in summary
    assert "evaluation_mode" in summary


def test_manual_feedback_recording(tmp_path: Path) -> None:
    repo = create_java_repo(tmp_path)
    bundle = router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    payload = router_core.record_manual_feedback(
        bundle_root,
        {
            "decision_id": "route-1",
            "final_action": "review",
            "final_capability": "billing",
            "notes": "Confirmed by human reviewer",
            "confirmed_public_entry": "backend/billing/src/main/java",
            "confirmed_owner": "billing-team",
            "profile_update_recommended": True,
        },
    )
    assert payload["final_action"] == "review"
    feedback_dir = bundle_root / "reports" / "manual-feedback"
    assert any(feedback_dir.glob("feedback-*.json"))


def test_profile_curated_evaluation_mode(tmp_path: Path) -> None:
    repo = create_profiled_repo(tmp_path)
    profile_path = repo / ".project-change-router.yaml"
    profile_path.write_text(
        profile_path.read_text(encoding="utf-8")
        + """
evaluation:
  mode: curated
  cases:
    - id: curated-case-1
      request: Reuse the existing payment capability.
      expected_action: reuse
      expected_capabilities: ["payment-core"]
      expected_modules: ["services/payments"]
      expected_reads: []
      changed_paths: ["services/payments"]
      risk_level: medium
""",
        encoding="utf-8",
    )
    bundle = router_core.bootstrap_bundle(repo, write=True)
    assert bundle["evaluation_set"]["mode"] in {"curated", "hybrid"}
    assert any(case["id"] == "curated-case-1" for case in bundle["evaluation_set"]["cases"])


def test_reuse_scan_changed_test_path_does_not_fallback_to_full_scan(tmp_path: Path) -> None:
    repo = tmp_path / "reuse-scan-repo"
    (repo / "app" / "services").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    for index in range(12):
        (repo / "app" / "services" / f"service_{index}.py").write_text(
            f"def service_{index}():\n    return {index}\n",
            encoding="utf-8",
        )
    (repo / "tests" / "test_workflow_execution.py").write_text(
        "def test_workflow_execution():\n    assert True\n",
        encoding="utf-8",
    )
    module = router_core.ModuleEntry(
        id="module-app-services",
        path="app/services",
        layer="domain-service",
        domain="app-services",
        purpose="Application services",
    )
    capability = router_core.CapabilityEntry(
        id="app-services",
        name="Application Services",
        status="stable",
        maturity="stable",
        stage="stable",
        owner_modules=["app/services"],
        public_entries=["app/services"],
        related_tests=["tests/test_workflow_execution.py"],
    )
    bundle = {
        "config": {"generated_at": "2026-01-01T00:00:00Z", "ignore_paths": []},
        "change_rules": {"reuse_scan_budget": {"max_comparisons": 100}},
        "module_map": {"modules": [module.to_dict()]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
    }
    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_workflow_execution.py"])

    assert report["scan"]["candidate_file_count"] == 1
    assert report["scan"]["candidate_examples"] == ["tests/test_workflow_execution.py"]
    assert report["scan"]["raw_pair_count"] == 12
    assert report["scan"]["scope"]["capability_ids"] == ["app-services"]
    assert report["scan"]["completion_status"] == "complete"


def reuse_scope_fixture(tmp_path: Path) -> tuple[Path, dict]:
    repo = tmp_path / "scoped-reuse-repo"
    (repo / "app" / "workflow").mkdir(parents=True)
    (repo / "app" / "billing").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    for index in range(3):
        (repo / "app" / "workflow" / f"worker_{index}.py").write_text(
            f"def execute_workflow_{index}(payload):\n    return payload.get('value', {index})\n",
            encoding="utf-8",
        )
        (repo / "app" / "billing" / f"invoice_{index}.py").write_text(
            f"def create_invoice_{index}(amount):\n    return amount + {index}\n",
            encoding="utf-8",
        )
    test_path = repo / "tests" / "test_workflow_execution.py"
    test_path.write_text(
        "def test_workflow_execution(payload):\n    return payload.get('value', 0)\n",
        encoding="utf-8",
    )
    modules = [
        router_core.ModuleEntry("workflow-module", "app/workflow", "domain-service", "workflow", "Workflow"),
        router_core.ModuleEntry("billing-module", "app/billing", "domain-service", "billing", "Billing"),
    ]
    capabilities = [
        router_core.CapabilityEntry(
            "workflow",
            "Workflow",
            "stable",
            "stable",
            stage="stable",
            owner_modules=["app/workflow"],
            related_tests=["tests/test_workflow_execution.py"],
        ),
        router_core.CapabilityEntry(
            "billing",
            "Billing",
            "stable",
            "stable",
            stage="stable",
            owner_modules=["app/billing"],
        ),
    ]
    bundle = {
        "config": {"generated_at": "2026-01-01T00:00:00Z", "ignore_paths": []},
        "change_rules": {"reuse_scan_budget": {"max_comparisons": 100}},
        "module_map": {"modules": [module.to_dict() for module in modules]},
        "capability_catalog": {"capabilities": [capability.to_dict() for capability in capabilities]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "tests/test_workflow_execution.py",
                    "capabilities": ["workflow"],
                },
                {
                    "path_pattern": "**",
                    "capabilities": ["billing"],
                }
            ]
        },
    }
    return repo, bundle


def test_reuse_scan_limits_owner_files_to_resolved_capability(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)

    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_workflow_execution.py"])

    assert report["scan"]["scope"]["direct_capability_ids"] == ["workflow"]
    assert report["scan"]["scope"]["ignored_broad_mappings"] == [
        {
            "path": "tests/test_workflow_execution.py",
            "path_pattern": "**",
            "capabilities": ["billing"],
        }
    ]
    assert report["scan"]["capabilities_scanned"] == 1
    assert report["scan"]["capabilities_skipped_by_scope"] == 1
    assert report["scan"]["owner_file_count"] == 4
    assert report["scan"]["raw_pair_count"] == 3


def test_reuse_scan_unknown_path_returns_incomplete_without_repo_scan(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    unknown = repo / "tests" / "test_unmapped_feature.py"
    unknown.write_text("def test_unmapped():\n    assert True\n", encoding="utf-8")

    report = router_core.gather_reuse_report(repo, bundle, ["tests/test_unmapped_feature.py"])

    assert report["scan"]["scope"]["status"] == "unresolved"
    assert report["scan"]["raw_pair_count"] == 0
    assert report["scan"]["completion_status"] == "incomplete"
    assert any(finding["rule"] == "reuse-scan-scope-unresolved" for finding in report["findings"])


def test_reuse_scan_persistent_fingerprint_cache_is_reused(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    runtime_root = tmp_path / "runtime"
    options = {
        "runtime_root": str(runtime_root),
        "run_id": "first",
        "cache_mode": "auto",
        "soft_timeout_seconds": 10,
        "checkpoint_interval_seconds": 0.1,
    }

    first = router_core.gather_reuse_report(
        repo, bundle, ["tests/test_workflow_execution.py"], runtime_options=options
    )
    options["run_id"] = "second"
    second = router_core.gather_reuse_report(
        repo, bundle, ["tests/test_workflow_execution.py"], runtime_options=options
    )

    assert first["scan"]["fingerprint_cache_misses"] > 0
    assert first["scan"]["fingerprints_written"] > 0
    assert second["scan"]["fingerprint_cache_hits"] == first["scan"]["fingerprint_cache_misses"]
    assert second["scan"]["fingerprint_cache_misses"] == 0


def test_reuse_scan_soft_timeout_emits_incomplete_evidence(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
        runtime_options={"soft_timeout_seconds": 0.000001},
    )

    assert report["scan"]["completion_status"] == "timeout"
    assert report["scan"]["termination_reason"] == "soft_timeout"
    assert report["scan"]["evidence_complete"] is False
    assert any(finding["rule"] == "reuse-scan-incomplete" for finding in report["findings"])


def test_reuse_scan_reports_large_file_fingerprint_candidate_without_exact_match(tmp_path: Path) -> None:
    repo, bundle = reuse_scope_fixture(tmp_path)
    candidate_text = (repo / "tests" / "test_workflow_execution.py").read_text(encoding="utf-8")
    (repo / "app" / "workflow" / "worker_0.py").write_text(candidate_text, encoding="utf-8")

    report = router_core.gather_reuse_report(
        repo,
        bundle,
        ["tests/test_workflow_execution.py"],
        budget_overrides={"max_file_bytes_for_full_similarity": 10},
    )

    candidates = [
        finding for finding in report["findings"] if finding["rule"] == "duplicate-fingerprint-candidate"
    ]
    assert candidates
    assert candidates[0]["fingerprint_score"] >= 0.55
    assert report["scan"]["comparisons_run"] == 0
    assert report["scan"]["completion_status"] == "bounded"


def test_runtime_store_deduplicates_canonical_reports_and_cleans_diagnostics(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime-store"
    canonical = {
        "run_id": "run-one",
        "result_status": "pass",
        "completion_status": "complete",
        "findings": [],
    }
    semantic = {"result_status": "pass", "findings": []}
    with reuse_runtime.ReuseRuntimeStore(runtime_root) as store:
        first = store.persist_report("canonical", canonical, semantic)
        canonical["run_id"] = "run-two"
        second = store.persist_report("canonical", canonical, semantic)
        diagnostic = store.persist_report(
            "diagnostic",
            {"run_id": "diag", "result_status": "warn", "completion_status": "bounded"},
        )
        policy = reuse_runtime.ReuseRetentionPolicy(diagnostic_max_count=0)
        removed = store.cleanup(tmp_path, policy)

    assert first.deduplicated is False
    assert second.deduplicated is True
    assert second.occurrence_count == 2
    assert first.path == second.path
    assert removed["diagnostic"] == 1
    assert not diagnostic.path.exists()


def test_runtime_store_preserves_and_rebuilds_corrupt_fingerprint_database(tmp_path: Path) -> None:
    runtime_root = tmp_path / "corrupt-runtime"
    runtime_root.mkdir()
    (runtime_root / "reuse-runtime.sqlite3").write_bytes(b"not-a-sqlite-database")

    with reuse_runtime.ReuseRuntimeStore(runtime_root) as store:
        recovery = store.recovery_event
        store.put_fingerprint(
            "app/service.py",
            "stat-key",
            {
                "suffix": ".py",
                "file_size": 10,
                "normalized_length": 8,
                "token_count": 2,
                "token_sketch": ["a", "b"],
                "content_digest": "digest",
            },
        )
        cached = store.get_fingerprint("app/service.py", "stat-key")

    assert recovery and recovery["reason"] == "sqlite_database_rebuilt"
    assert Path(recovery["preserved_corrupt_database"]).exists()
    assert cached and cached["content_digest"] == "digest"


def test_atomic_skill_upgrade_does_not_modify_existing_repository_bundle(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    old_install = codex_home / "skills" / "project-change-router"
    old_install.mkdir(parents=True)
    (old_install / "old-file.txt").write_text("old install\n", encoding="utf-8")
    target_repo = tmp_path / "long-lived-project"
    bundle_file = target_repo / "project-change-router" / "references" / "capability-catalog.yaml"
    bundle_file.parent.mkdir(parents=True)
    bundle_file.write_text("schema_version: 1\ncapabilities: []\n", encoding="utf-8")
    before = bundle_file.read_bytes()

    install = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "install_skill.py"),
            "--target",
            "codex",
            "--codex-home",
            str(codex_home),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    verify = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "install_skill.py"),
            "--target",
            "codex",
            "--codex-home",
            str(codex_home),
            "--verify-only",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert install.returncode == 0, install.stderr
    assert verify.returncode == 0, verify.stderr
    assert bundle_file.read_bytes() == before
    assert not (old_install / "old-file.txt").exists()
    manifest = json.loads((old_install / ".installation-manifest.json").read_text(encoding="utf-8"))
    assert manifest["skill_version"] == "0.2.0"
    assert manifest["reuse_engine_api_version"] == 2


def test_check_reuse_hard_timeout_returns_canonical_incomplete_report(tmp_path: Path) -> None:
    repo, _bundle = reuse_scope_fixture(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "check_reuse.py"),
            "--repo",
            str(repo),
            "--changed-path",
            "tests/test_workflow_execution.py",
            "--timeout-seconds",
            "0",
            "--hard-timeout-seconds",
            "0.02",
            "--runtime-dir",
            str(tmp_path / "hard-timeout-runtime"),
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(result.stdout)
    assert result.returncode == 2
    assert report["report_class"] == "canonical"
    assert report["result_status"] == "warn"
    assert report["completion_status"] == "timeout"
    assert report["evidence_complete"] is False
    assert Path(report["artifacts"]["checkpoint"]).exists()
    assert router_core.validate_against_schema(
        report,
        SKILL_ROOT / "schemas" / "reuse-scan-report.schema.json",
    ) == []


def test_reuse_output_examples_match_report_schema() -> None:
    schema = SKILL_ROOT / "schemas" / "reuse-scan-report.schema.json"
    for filename in ("check-reuse.pass.json", "check-reuse.warn.json", "check-reuse.timeout.json"):
        report = json.loads((SKILL_ROOT / "examples" / "outputs" / filename).read_text(encoding="utf-8"))
        assert router_core.validate_against_schema(report, schema) == []


def test_root_owner_path_map_falls_back_to_same_domain_module(tmp_path: Path) -> None:
    repo = tmp_path / "path-map-repo"
    (repo / "migrations").mkdir(parents=True)
    (repo / "app").mkdir(parents=True)
    modules = [
        router_core.ModuleEntry(
            id="module-database-schema-migrations",
            path="migrations",
            layer="infra",
            domain="database-schema-migrations",
            purpose="Schema migrations",
        ),
        router_core.ModuleEntry(
            id="module-app",
            path="app",
            layer="domain-service",
            domain="app",
            purpose="Application code",
        ),
    ]
    capability = router_core.CapabilityEntry(
        id="database-schema-migrations",
        name="Database Schema Migrations",
        status="stable",
        maturity="stable",
        stage="stable",
        source_of_truth="curated",
        owner_modules=["."],
        public_entries=["."],
    )

    path_map = router_core.build_path_to_capability_map(repo, [capability], modules)

    assert path_map["lookup"]["migrations/**"] == ["database-schema-migrations"]
    assert "database-schema-migrations" not in path_map["lookup"].get("**", [])


def test_governance_flags_repo_wide_capability_mapping(tmp_path: Path) -> None:
    repo = tmp_path / "bad-path-map-repo"
    repo.mkdir(parents=True)
    modules = [
        router_core.ModuleEntry(
            id="module-database-schema-migrations",
            path="migrations",
            layer="infra",
            domain="database-schema-migrations",
            purpose="Schema migrations",
        ),
        router_core.ModuleEntry(
            id="module-app",
            path="app",
            layer="domain-service",
            domain="app",
            purpose="Application code",
        ),
    ]
    capability = router_core.CapabilityEntry(
        id="database-schema-migrations",
        name="Database Schema Migrations",
        status="stable",
        maturity="stable",
        stage="stable",
        source_of_truth="curated",
        owner_modules=["."],
        public_entries=["."],
    )
    bundle = {
        "config": {"repo_stage": "structured"},
        "change_rules": {},
        "module_map": {"modules": [module.to_dict() for module in modules]},
        "capability_catalog": {"capabilities": [capability.to_dict()]},
        "path_to_capability_map": {
            "path_index": [
                {
                    "path_pattern": "**",
                    "capabilities": ["database-schema-migrations"],
                    "relationship": "unique",
                    "sources": ["owner_modules"],
                    "modules": ["."],
                }
            ],
            "uncovered_modules": [],
            "ambiguous_patterns": [],
        },
    }

    report = router_core.audit_bundle_governance(repo, bundle)
    rules = {finding["rule"] for finding in report["findings"]}

    assert "capability-root-owner-too-broad" in rules
    assert "path-map-repository-wide-capability" in rules
    assert any(suggestion["kind"] == "narrow_capability_ownership" for suggestion in report["repair_suggestions"])
