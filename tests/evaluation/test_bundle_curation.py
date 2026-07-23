from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def create_profiled_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "profiled-repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "services" / "payments").mkdir(parents=True)
    (repo / "services" / "payments" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "services" / "payments" / "service.py").write_text(
        "def charge():\n    return True\n",
        encoding="utf-8",
    )
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
    assert [case["id"] for case in bundle["evaluation_set"]["cases"]] == ["curated-case-1"]


def test_hybrid_evaluation_rebuild_preserves_existing_cases() -> None:
    existing = {
        "mode": "hybrid",
        "curated_case_ids": ["real-regression", "shared"],
        "cases": [
            {"id": "real-regression", "request": "Preserve this reviewed route."},
            {"id": "shared", "request": "Keep the reviewed version."},
        ],
    }
    generated = {
        "mode": "generated_only",
        "cases": [
            {"id": "shared", "request": "Generated replacement."},
            {"id": "generated-route", "request": "Generated route."},
        ],
    }

    merged = router_core.merge_curated_evaluation(existing, generated, {})

    assert merged["mode"] == "hybrid"
    assert [case["id"] for case in merged["cases"]] == [
        "real-regression",
        "shared",
        "generated-route",
    ]
    assert merged["cases"][1]["request"] == "Keep the reviewed version."


def test_hybrid_rebuild_does_not_promote_generated_cases_to_curated() -> None:
    existing = {
        "mode": "hybrid",
        "curated_case_ids": ["real-route"],
        "cases": [
            {"id": "real-route", "request": "Reviewed route."},
            {"id": "old-generated", "request": "Old generated route."},
        ],
    }
    generated = {
        "mode": "generated_only",
        "cases": [{"id": "new-generated", "request": "New generated route."}],
    }

    merged = router_core.merge_curated_evaluation(existing, generated, {})

    assert merged["mode"] == "hybrid"
    assert merged["curated_case_ids"] == ["real-route"]
    assert [case["id"] for case in merged["cases"]] == [
        "real-route",
        "old-generated",
        "new-generated",
    ]


def test_empty_curated_profile_does_not_relabel_generated_cases() -> None:
    generated = {
        "mode": "generated_only",
        "cases": [{"id": "generated-route", "request": "Generated route."}],
    }

    merged = router_core.merge_curated_evaluation(
        {},
        generated,
        {"evaluation": {"mode": "curated", "cases": []}},
    )

    assert merged["mode"] == "generated_only"
    assert merged["curated_case_ids"] == []


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
    assert manifest["skill_version"] == "0.3.0"
    assert manifest["reuse_engine_api_version"] == 2
    assert manifest["architecture_governance_api_version"] == 1


def test_path_map_preserves_profile_ownership_rules_without_discovered_modules(tmp_path: Path) -> None:
    repo = tmp_path / "governance-path-map-repo"
    repo.mkdir(parents=True)
    capability = router_core.CapabilityEntry(
        id="rebuild-governance",
        name="Rebuild Governance",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="profile",
        owner_modules=["docs/governance/CANONICAL_ROOTS.md"],
        public_entries=["docs/governance/CANONICAL_ROOTS.md"],
    )
    profile = {
        "ownership_rules": [
            {
                "owner": "rebuild-governance",
                "path_patterns": [
                    ".claude/skills/project-change-router/scripts/**",
                    ".claude/skills/project-change-router/tests/**",
                ],
            }
        ]
    }

    path_map = router_core.build_path_to_capability_map(repo, [capability], [], profile)

    assert path_map["lookup"][".claude/skills/project-change-router/scripts/**"] == ["rebuild-governance"]
    assert path_map["lookup"][".claude/skills/project-change-router/tests/**"] == ["rebuild-governance"]


def test_rebuild_preserves_curated_architecture_records(tmp_path: Path) -> None:
    repo = create_profiled_repo(tmp_path)
    execution_root = repo / "app" / "services" / "task_execution"
    execution_root.mkdir(parents=True)
    execution_test = repo / "tests" / "canonical" / "task_execution" / "test_gateway.py"
    execution_test.parent.mkdir(parents=True)
    execution_test.write_text("def test_gateway():\n    assert True\n", encoding="utf-8")
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (execution_root / "gateway.py").write_text(
        "class TaskExecutionGateway:\n    pass\n",
        encoding="utf-8",
    )
    router_core.bootstrap_bundle(repo, write=True)
    bundle_root = repo / "project-change-router"
    existing = router_core.load_bundle(bundle_root)
    execution_module = router_core.ModuleEntry(
        id="module-task-execution-gateway",
        path="app/services/task_execution",
        layer="shared-capability",
        domain="task-runtime-internal",
        purpose="Curated canonical task execution boundary",
        public_api="gateway.py",
        source_of_truth="curated",
        key_files=["tests/canonical/task_execution/test_gateway.py"],
        generated=False,
        owner="runtime-platform",
    )
    execution_capability = router_core.CapabilityEntry(
        id="task-execution-gateway",
        name="Task Execution Gateway",
        status="stable",
        maturity="curated",
        stage="stable",
        source_of_truth="curated",
        owner_modules=[execution_module.path],
        public_entries=["app/services/task_execution/gateway.py"],
    )
    existing["module_map"]["modules"].append(execution_module.to_dict())
    existing["capability_catalog"]["capabilities"].append(execution_capability.to_dict())
    existing["evaluation_set"] = {
        "schema_version": 1,
        "mode": "curated",
        "cases": [
            {
                "id": f"curated-route-{index:02d}",
                "request": f"Review real route {index}",
                "expected_action": "review",
                "expected_capabilities": [execution_capability.id],
                "expected_modules": [execution_module.path],
                "expected_reads": execution_capability.public_entries,
                "changed_paths": execution_capability.public_entries,
                "risk_level": "high",
            }
            for index in range(83)
        ],
    }
    router_core.write_bundle(bundle_root, existing)

    rebuilt = router_core.build_router_bundle(repo)
    modules = {item["path"]: item for item in rebuilt["module_map"]["modules"]}
    capability_ids = [item["id"] for item in rebuilt["capability_catalog"]["capabilities"]]
    case_ids = {item["id"] for item in rebuilt["evaluation_set"]["cases"]}
    failures = []
    if execution_module.path not in modules:
        failures.append("curated module path was dropped")
    if modules.get("app", {}).get("source_of_truth") == "generated":
        failures.append("generated ancestor shadows a curated module boundary")
    if modules.get("tests", {}).get("source_of_truth") == "generated":
        failures.append("generated test root shadows curated test ownership")
    if execution_capability.id not in capability_ids:
        failures.append("curated capability was dropped")
    if "task-runtime-internal" in capability_ids:
        failures.append("generated capability shadows curated module ownership")
    if not {f"curated-route-{index:02d}" for index in range(83)} <= case_ids:
        failures.append("curated evaluation case was dropped")
    if modules[execution_module.path]["owner"] != "runtime-platform":
        failures.append("curated module owner was dropped")
    if len(capability_ids) != len(set(capability_ids)):
        failures.append("duplicate capability IDs were generated")
    assert failures == []
