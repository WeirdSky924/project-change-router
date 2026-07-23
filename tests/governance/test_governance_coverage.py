from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.governance_coverage import assess_stable_capability_governance
from router_support.governance_coverage import capability_owner_assessment
import router_core
from router_support.governance_coverage import matching_capability_contract_boundaries
from router_support.governance_coverage import request_has_permanent_central_delegation


def _capability(capability_id: str = "example") -> dict[str, object]:
    return {
        "id": capability_id,
        "name": capability_id.title(),
        "status": "stable",
        "maturity": "curated",
        "stage": "stable",
        "public_entries": [f"app/{capability_id}/__init__.py"],
        "contracts": ["scope", "boundary"],
        "lifecycle": {"definition_version": "1.0", "status": "stable"},
    }


def _owner(capability_id: str = "example") -> dict[str, object]:
    return {
        "scope": "capability",
        "target": capability_id,
        "primary": f"{capability_id}-maintainers",
        "reviewers": [f"{capability_id}-architecture-reviewers"],
        "provisional": False,
    }


def _case(capability_id: str, action: str, coverage_kind: str | None = None) -> dict[str, object]:
    case: dict[str, object] = {
        "id": f"{capability_id}-{action}",
        "expected_action": action,
        "expected_capabilities": [capability_id],
    }
    if coverage_kind:
        case["coverage_kind"] = coverage_kind
    return case


def _bundle() -> dict[str, object]:
    return {
        "capability_catalog": {"capabilities": [_capability()]},
        "ownership": {"owners": [_owner()]},
        "evaluation_set": {"cases": [_case("example", "extend"), _case("example", "review")]},
    }


def _route_bundle(
    tmp_path: Path,
    *,
    capability_id: str = "record-contracts",
    module_path: str = "src/models",
    path_patterns: list[str] | None = None,
    forbidden_patterns: list[str] | None = None,
    anti_patterns: list[str] | None = None,
) -> tuple[dict[str, object], Path]:
    bundle_root = tmp_path / "router-bundle"
    marker = bundle_root / "references" / "module-map.yaml"
    marker.parent.mkdir(parents=True)
    marker.write_text("modules: []\n", encoding="utf-8")
    patterns = path_patterns or [f"{module_path}/**"]
    capability = router_core.CapabilityEntry(
        id=capability_id,
        name=capability_id.replace("-", " ").title(),
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        intent_keywords=[capability_id.replace("-", " ")],
        owner_modules=[module_path],
        public_entries=[f"{module_path}/__init__.py"],
        extension_points=[module_path],
        contracts=["Preserve the canonical capability boundary."],
        forbidden_patterns=forbidden_patterns or [],
        anti_patterns=anti_patterns or [],
        lifecycle={"definition_version": "1.0", "status": "stable"},
    )
    module = router_core.ModuleEntry(
        id=f"module-{capability_id}",
        path=module_path,
        layer="domain-service",
        domain=capability_id,
        purpose="Synthetic capability owner",
        source_of_truth="profile",
        owner=capability_id,
    )
    return (
        {
            "config": {
                "repo_stage": "structured",
                "freshness_windows": {"module_map_days": 30},
            },
            "capability_catalog": {"capabilities": [capability.to_dict()]},
            "module_map": {"modules": [module.to_dict()]},
            "ownership": {
                "owners": [
                    {
                        "scope": "capability",
                        "target": capability_id,
                        "primary": f"{capability_id}-maintainers",
                        "reviewers": [f"{capability_id}-architecture-reviewers"],
                        "provisional": False,
                    }
                ]
            },
            "change_rules": {
                "confidence": {
                    "auto_route_threshold": 0.78,
                    "guarded_route_threshold": 0.58,
                },
                "high_risk_capability_ids": [],
            },
            "path_to_capability_map": {
                "path_index": [
                    {
                        "path_pattern": pattern,
                        "capabilities": [capability_id],
                    }
                    for pattern in patterns
                ]
            },
            "evaluation_set": {"mode": "curated", "cases": []},
        },
        bundle_root,
    )


def test_complete_stable_capability_has_no_governance_gaps() -> None:
    result = assess_stable_capability_governance(_bundle())

    assert result == {
        "stable_capabilities": ["example"],
        "missing_owner": [],
        "provisional_or_unknown_owner": [],
        "missing_distinct_reviewer": [],
        "missing_lifecycle": [],
        "missing_public_entries": [],
        "missing_contracts": [],
        "missing_positive_cases": [],
        "missing_boundary_cases": [],
    }


def test_build_ownership_uses_explicit_capability_owner_and_reviewer() -> None:
    module = router_core.ModuleEntry(
        id="module-runtime",
        path="src/runtime",
        layer="domain-service",
        domain="runtime",
        purpose="Runtime",
        owner="runtime-maintainers",
    )
    capability = router_core.CapabilityEntry(
        id="runtime",
        name="Runtime",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=[module.path],
    )
    profile = {
        "capability_ownership": [
            {
                "target": "runtime",
                "primary": "runtime-maintainers",
                "reviewers": ["runtime-architecture-reviewers"],
                "escalation_group": "architecture-council",
            }
        ]
    }

    records = router_core.build_ownership(
        [capability], [module], "structured", profile
    )["owners"]
    owner = next(item for item in records if item["scope"] == "capability")

    assert owner == {
        "scope": "capability",
        "target": "runtime",
        "primary": "runtime-maintainers",
        "reviewers": ["runtime-architecture-reviewers"],
        "escalation_group": "architecture-council",
        "provisional": False,
    }


def test_build_ownership_rejects_malformed_profile_identities() -> None:
    module = router_core.ModuleEntry(
        id="module-runtime",
        path="src/runtime",
        layer="domain-service",
        domain="runtime",
        purpose="Runtime",
        owner="runtime-maintainers",
    )
    capability = router_core.CapabilityEntry(
        id="runtime",
        name="Runtime",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=[module.path],
    )
    profile = {
        "capability_ownership": [
            {
                "target": "runtime",
                "primary": True,
                "reviewers": [{"team": "security"}],
                "provisional": False,
            }
        ]
    }

    records = router_core.build_ownership(
        [capability], [module], "structured", profile
    )["owners"]
    owner = next(item for item in records if item["scope"] == "capability")
    assessment = capability_owner_assessment(
        {"ownership": {"owners": [owner]}},
        "runtime",
    )

    assert owner["primary"] == "UNKNOWN"
    assert owner["reviewers"] == []
    assert owner["provisional"] is True
    assert assessment["trusted"] is False


def test_build_ownership_keeps_missing_explicit_stable_owner_provisional() -> None:
    module = router_core.ModuleEntry(
        id="module-runtime",
        path="src/runtime",
        layer="domain-service",
        domain="runtime",
        purpose="Runtime",
        owner="runtime-maintainers",
    )
    capability = router_core.CapabilityEntry(
        id="runtime",
        name="Runtime",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=[module.path],
    )

    records = router_core.build_ownership(
        [capability], [module], "structured", {}
    )["owners"]
    owner = next(item for item in records if item["scope"] == "capability")

    assert owner["primary"] == "runtime-maintainers"
    assert owner["reviewers"] == []
    assert owner["provisional"] is True


def test_stable_capability_reports_owner_and_contract_metadata_gaps() -> None:
    bundle = _bundle()
    capability = bundle["capability_catalog"]["capabilities"][0]
    capability["public_entries"] = []
    capability["contracts"] = []
    capability["lifecycle"] = {}
    owner = bundle["ownership"]["owners"][0]
    owner["primary"] = "UNKNOWN"
    owner["reviewers"] = ["UNKNOWN"]
    owner["provisional"] = True

    result = assess_stable_capability_governance(bundle)

    assert result["provisional_or_unknown_owner"] == ["example"]
    assert result["missing_distinct_reviewer"] == ["example"]
    assert result["missing_lifecycle"] == ["example"]
    assert result["missing_public_entries"] == ["example"]
    assert result["missing_contracts"] == ["example"]


def test_generated_owner_placeholders_do_not_authorize_stable_capability() -> None:
    bundle = _bundle()
    owner = bundle["ownership"]["owners"][0]
    owner["primary"] = "capability-steward:example"
    owner["reviewers"] = ["architecture-reviewer:example"]
    owner["provisional"] = False

    result = assess_stable_capability_governance(bundle)

    assert result["provisional_or_unknown_owner"] == ["example"]
    assert result["missing_distinct_reviewer"] == ["example"]


def test_owner_and_reviewer_identity_variants_are_not_distinct() -> None:
    bundle = _bundle()
    owner = bundle["ownership"]["owners"][0]
    owner["primary"] = "Example-Maintainers"
    owner["reviewers"] = ["  example-maintainers  "]

    result = assess_stable_capability_governance(bundle)

    assert result["missing_distinct_reviewer"] == ["example"]


def test_malformed_owner_identity_values_are_not_trusted() -> None:
    bundle = _bundle()
    owner = bundle["ownership"]["owners"][0]
    owner["primary"] = True
    owner["reviewers"] = [{"team": "security"}]
    owner["provisional"] = False

    assessment = capability_owner_assessment(bundle, "example")

    assert assessment["trusted"] is False
    assert "capability owner identity is invalid" in assessment["reasons"]
    assert "capability reviewer identity is invalid" in assessment["reasons"]


def test_untrusted_secondary_capability_owner_blocks_route_writes(
    tmp_path: Path,
) -> None:
    bundle, bundle_root = _route_bundle(tmp_path)
    bundle["capability_catalog"]["capabilities"].append(
        {
            **bundle["capability_catalog"]["capabilities"][0],
            "id": "audit-hooks",
            "name": "Audit Hooks",
            "owner_modules": ["src/audit"],
            "public_entries": ["src/audit/__init__.py"],
        }
    )
    bundle["module_map"]["modules"].append(
        {
            "id": "module-audit-hooks",
            "path": "src/audit",
            "layer": "domain-service",
            "domain": "audit-hooks",
            "purpose": "Audit hooks",
            "source_of_truth": "profile",
            "owner": "UNKNOWN",
        }
    )
    bundle["ownership"]["owners"].append(
        {
            "scope": "capability",
            "target": "audit-hooks",
            "primary": "UNKNOWN",
            "reviewers": ["UNKNOWN"],
            "provisional": False,
        }
    )
    bundle["path_to_capability_map"]["path_index"][0]["capabilities"] = [
        "record-contracts",
        "audit-hooks",
    ]

    decision = router_core.resolve_request(
        "Extend the existing record contract and its audit hooks.",
        ["src/models/record.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "record-contracts"
    assert decision.secondary_capabilities == ["audit-hooks"]
    assert decision.action == "review"
    assert decision.allowed_write_paths == []
    assert "**" in decision.forbidden_write_paths
    assert any("audit-hooks" in reason for reason in decision.veto_reasons)


def test_stable_capability_requires_positive_and_boundary_cases() -> None:
    bundle = _bundle()
    bundle["capability_catalog"]["capabilities"].append(_capability("positive-only"))
    bundle["capability_catalog"]["capabilities"].append(_capability("boundary-only"))
    bundle["ownership"]["owners"].append(_owner("positive-only"))
    bundle["ownership"]["owners"].append(_owner("boundary-only"))
    bundle["evaluation_set"]["cases"] = [
        _case("example", "extend"),
        _case("example", "review"),
        _case("positive-only", "reuse"),
        _case("boundary-only", "review"),
    ]

    result = assess_stable_capability_governance(bundle)

    assert result["missing_positive_cases"] == ["boundary-only"]
    assert result["missing_boundary_cases"] == ["positive-only"]


def test_explicit_positive_review_case_does_not_fake_a_boundary_case() -> None:
    bundle = _bundle()
    bundle["evaluation_set"]["cases"] = [_case("example", "review", "positive")]

    result = assess_stable_capability_governance(bundle)

    assert result["missing_positive_cases"] == []
    assert result["missing_boundary_cases"] == ["example"]


def test_bundle_audit_reports_missing_stable_boundary_case(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _bundle()
    bundle["config"] = {"repo_stage": "structured"}
    bundle["module_map"] = {"modules": []}
    bundle["path_to_capability_map"] = {"path_index": [{"path_pattern": "app/example.py", "capabilities": ["example"]}]}
    bundle["change_rules"] = {
        "dependency_priority": {"example": 1},
        "contract_quality_policy": {
            "min_contracts_for_profile_capability": 3,
            "min_contracts_for_large_capability": 4,
            "large_capability_file_threshold": 10,
            "recommended_contract_chars": {"min": 1, "max": 500},
        },
    }
    bundle["evaluation_set"] = {"mode": "curated", "cases": [_case("example", "extend")]}

    report = router_core.audit_bundle_governance(repo, bundle)

    finding = next(item for item in report["findings"] if item["rule"] == "stable-capability-boundary-case-missing")
    assert finding["details"]["capabilities"] == ["example"]


def test_contract_quality_uses_structured_contract_descriptions(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _bundle()
    capability = bundle["capability_catalog"]["capabilities"][0]
    capability["source_of_truth"] = "profile"
    capability["contracts"] = [
        {
            "type": "scope",
            "description": "Owns repository-neutral route resolution and validation behavior.",
        },
        {
            "type": "boundary",
            "description": "Keeps repository-specific capability facts outside the shared runtime.",
        },
        {
            "type": "risk",
            "description": "Requires review when routing evidence is stale, incomplete, or ambiguous.",
        },
    ]
    bundle["config"] = {"repo_stage": "structured"}
    bundle["module_map"] = {"modules": []}
    bundle["path_to_capability_map"] = {"path_index": []}
    bundle["change_rules"] = {
        "dependency_priority": {"example": 1},
        "contract_quality_policy": {
            "min_contracts_for_profile_capability": 3,
            "min_contracts_for_large_capability": 4,
            "large_capability_file_threshold": 10,
            "recommended_contract_chars": {"min": 50, "max": 240},
        },
    }

    report = router_core.audit_bundle_governance(repo, bundle)

    assert "contracts-too-short" not in {
        finding["rule"] for finding in report["findings"]
    }


def test_stable_infrastructure_root_accepts_team_owner_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "router.py").write_text("ROUTE = True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = \"governance-root\"\nversion = \"0.1.0\"\n",
        encoding="utf-8",
    )
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: governance-root
capabilities:
  - id: router-runtime
    name: Router Runtime
    path_patterns: ["scripts/**"]
    public_entries: ["scripts/router.py"]
    status: stable
    stage: governed-capability
    contracts:
      - "Owns repository-neutral route resolution and validation behavior."
      - "Keeps repository-specific capability facts outside shared runtime code."
      - "Requires review when routing evidence or ownership metadata changes."
ownership_rules:
  - path_patterns: ["scripts/**"]
    owner: router-maintainers
module_overrides:
  - path: "scripts"
    path_patterns: ["scripts/**"]
    layer: infra
    domain: router-runtime
    public_api: "router.py"
""".lstrip(),
        encoding="utf-8",
    )

    report = router_core.audit_bundle_governance(
        repo,
        router_core.build_router_bundle(repo),
    )

    broad_patterns = {
        pattern
        for finding in report["findings"]
        if finding["rule"] == "ownership-rule-too-broad"
        for pattern in finding["details"]["patterns"]
    }
    assert "scripts/**" not in broad_patterns


def test_bundle_audit_rejects_stale_path_map_capability_reference(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    bundle = _bundle()
    bundle["config"] = {"repo_stage": "structured"}
    bundle["module_map"] = {"modules": []}
    bundle["change_rules"] = {"dependency_priority": {"example": 1}}
    bundle["path_to_capability_map"] = {
        "path_index": [
            {
                "path_pattern": "app/deleted.py",
                "capabilities": ["deleted-capability"],
            }
        ]
    }

    report = router_core.audit_bundle_governance(repo, bundle)

    finding = next(
        item
        for item in report["findings"]
        if item["rule"] == "path-map-references-unknown-capability"
    )
    assert finding["severity"] == "P0"
    assert finding["details"]["unknown_capabilities"] == ["deleted-capability"]


def test_bundle_audit_rejects_duplicate_and_unknown_capability_owners(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".project-change-router.yaml").write_text(
        """
profile_id: owner-validation
capabilities:
  - id: example
    path_patterns: ["app/example.py"]
capability_ownership:
  - target: example
    primary: example-maintainers
    reviewers: [example-reviewers]
  - target: example
    primary: alternate-maintainers
    reviewers: [alternate-reviewers]
  - target: removed-capability
    primary: removed-maintainers
    reviewers: [removed-reviewers]
""".lstrip(),
        encoding="utf-8",
    )
    bundle = _bundle()
    bundle["config"] = {"repo_stage": "structured"}
    bundle["module_map"] = {"modules": []}
    bundle["path_to_capability_map"] = {
        "path_index": [
            {"path_pattern": "app/example.py", "capabilities": ["example"]}
        ]
    }
    bundle["change_rules"] = {"dependency_priority": {"example": 1}}

    report = router_core.audit_bundle_governance(repo, bundle)

    finding = next(
        item
        for item in report["findings"]
        if item["rule"] == "capability-ownership-profile-invalid"
    )
    assert finding["severity"] == "P0"
    assert finding["details"]["duplicate_targets"] == ["example"]
    assert finding["details"]["unknown_targets"] == ["removed-capability"]


def test_capability_conflicts_include_module_owner_disagreement() -> None:
    bundle = _bundle()
    bundle["capability_catalog"]["capabilities"][0]["owner_modules"] = [
        "app/example"
    ]
    bundle["ownership"] = {
        "owners": [
            {
                "scope": "capability",
                "target": "example",
                "primary": "capability-team",
                "reviewers": ["architecture-reviewers"],
                "provisional": False,
            },
            {
                "scope": "module",
                "target": "app/example",
                "primary": "different-module-team",
                "reviewers": ["module-reviewers"],
                "provisional": False,
            },
        ]
    }

    conflicts = router_core.capability_conflicts(bundle)

    assert conflicts == [
        "capability example owner capability-team conflicts with module "
        "app/example owner different-module-team"
    ]


def test_capability_contract_boundary_forces_review(tmp_path: Path) -> None:
    bundle, bundle_root = _route_bundle(
        tmp_path,
        forbidden_patterns=["direct database write", "route registration"],
    )

    decision = router_core.resolve_request(
        "Add a direct database write and route registration to the record contract.",
        ["src/models/record.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "record-contracts"
    assert decision.action == "review"
    assert "capability contract boundary" in " ".join(decision.reasoning)


def test_negated_capability_boundary_does_not_force_review(tmp_path: Path) -> None:
    bundle, bundle_root = _route_bundle(
        tmp_path,
        forbidden_patterns=["direct database write", "route registration"],
    )

    decision = router_core.resolve_request(
        "Extend the existing record validator without direct database write or route registration.",
        ["src/models/record.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "record-contracts"
    assert decision.action == "extend"


def _example_job_boundary_matches(request: str) -> list[str]:
    return matching_capability_contract_boundaries(
        router_core._positive_request_scope(request),
        ["partial Example Job contract treated as success"],
        ["second Example Job Repository root"],
    )


def test_semantic_contract_boundary_matches_incomplete_and_second_owner_synonyms() -> None:
    unsafe_requests = {
        "Allow a seven-method subset of the Example Job contract and regard it as fully usable while absent methods are omitted.": "incomplete contract accepted as successful",
        "Introduce an additional Example Job repository alongside the canonical implementation.": "second repository or store owner",
        "Create an alternate Example Job store implementation beside the canonical repository.": "second repository or store owner",
        "Use an alternate Example Job repository alongside the canonical implementation.": "second repository or store owner",
    }

    for request, expected_match in unsafe_requests.items():
        assert expected_match in _example_job_boundary_matches(request)


def test_semantic_contract_boundary_ignores_protective_rejection_language() -> None:
    protective_requests = [
        "Reject a seven-method subset and fail closed when Example Job operations are absent.",
        "Assert that an incomplete Example Job contract is not treated as success.",
        "Prevent another Example Job repository from existing alongside the canonical owner.",
        "Verify an alternate Example Job store cannot be introduced beside the canonical repository.",
    ]

    for request in protective_requests:
        assert _example_job_boundary_matches(request) == []


def test_semantic_contract_boundary_keeps_dangerous_mixed_clause_after_protection() -> None:
    assert _example_job_boundary_matches(
        "Avoid treating a partial contract as success, but introduce an additional "
        "Example Job repository alongside the canonical implementation."
    ) == ["second repository or store owner"]
    assert _example_job_boundary_matches(
        "Reject a subset and fail closed, but allow an incomplete contract and regard "
        "it as usable."
    ) == ["incomplete contract accepted as successful"]


def test_exact_declared_boundary_phrase_remains_literal_match() -> None:
    assert matching_capability_contract_boundaries(
        router_core._positive_request_scope(
            "Reject the phrase partial contract accepted as successful in this test."
        ),
        ["partial contract accepted as successful"],
        [],
    ) == ["partial contract accepted as successful"]


def test_second_owner_replacement_does_not_count_as_second_owner() -> None:
    assert _example_job_boundary_matches(
        "Replace the canonical Example Job repository with an alternate store and remove the prior owner."
    ) == []


def test_permanent_global_gateway_delegation_forces_review(tmp_path: Path) -> None:
    bundle, bundle_root = _route_bundle(
        tmp_path,
        capability_id="order-persistence",
        module_path="src/orders",
    )

    decision = router_core.resolve_request(
        "Keep all Order SQL and codecs in the central database gateway and add a "
        "nominal SqlOrderRepository that permanently delegates the domain methods "
        "back to the global database gateway.",
        ["src/orders/sql_repository.py"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "order-persistence"
    assert decision.action == "review"
    assert "permanent central delegation" in " ".join(decision.reasoning)


def test_permanent_central_delegation_guard_ignores_temporary_or_negated_scope() -> None:
    assert not request_has_permanent_central_delegation(
        "A compatibility repository temporarily delegates to the global gateway "
        "during a caller migration with a named exit condition."
    )
    assert not request_has_permanent_central_delegation(
        router_core._positive_request_scope(
            "Do not permanently delegate the repository to the global gateway."
        )
    )
    assert not request_has_permanent_central_delegation(
        "A Provider adapter permanently delegates network execution to the "
        "central RemoteExecutionGateway."
    )
    assert not request_has_permanent_central_delegation(
        "The Repository owns its SQL and permanently delegates execute and fetch "
        "primitives to the global database Gateway."
    )


def test_permanent_central_delegation_guard_matches_generic_database_gateway_name() -> None:
    assert request_has_permanent_central_delegation(
        "Create an OrderRepository that permanently delegates all SQL domain methods "
        "back to CentralSqlGateway."
    )


def test_legacy_profile_retirement_is_not_capability_lifecycle(tmp_path: Path) -> None:
    bundle, bundle_root = _route_bundle(
        tmp_path,
        capability_id="routing-governance",
        module_path=".router.yaml",
        path_patterns=[".router.yaml", "router.profile.yaml"],
    )

    decision = router_core.resolve_request(
        "Deprecate and retire router.profile.yaml after moving its capability, owner, "
        "contract, lifecycle, test, and evaluation content into the canonical "
        ".router.yaml profile.",
        [".router.yaml", "router.profile.yaml"],
        bundle,
        bundle_root,
        enforce_evaluation_policy=False,
    )

    assert decision.primary_capability == "routing-governance"
    assert decision.capability_lifecycle_action["intent"] == "none"
