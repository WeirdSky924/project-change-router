from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from jsonschema import Draft202012Validator

from router_support.bundle_io import (
    dump_json_file,
    dump_yaml_file,
    load_json_file,
    load_yaml_file,
    prepare_router_bundle_for_preserved_write,
    write_router_bundle as write_bundle,
    write_text_in_chunks,
)
from router_support.import_graph import build_import_graph, classify_findings_against_baseline
from router_support.import_source_scan import JSX_SOURCE_SUFFIXES, scan_typescript_source
from router_support.java_source_scan import java_imports
from router_support.freshness_checks import (
    build_structure_snapshot,
    repository_freshness_report,
)
from router_support.generated_output_baseline import (
    validate_generated_output_rules,
)
from router_support.generated_output_baseline.write_guard import (
    assert_bootstrap_write_allowed,
)
from router_support.index_rebuild import (
    IndexRebuildOperations,
    rebuild_router_index,
)
from router_support.evaluation_policy import evaluate_configured_policy, make_evaluation_attestation, policy_for_bundle
from router_support.governance_coverage import (
    build_governance_repair_suggestions,
    build_stable_capability_governance_findings,
    capabilities_owner_assessment,
    contract_description,
    matching_capability_contract_boundaries,
)
from router_support.profile_loader import (
    deep_merge, disambiguate_generated_capability_id, load_active_profile,
    profile_candidates, profile_source_lifecycle_findings, retired_profile_path_routes,
)
from router_support.repository_surfaces import (
    discover_standard_repository_surfaces, has_standard_ci_surface,
    overlay_standard_repository_surface_records, standard_repository_surface_kind,
)
from router_support.ownership_governance import (
    build_ownership, capability_conflicts, codeowner_for_module, load_codeowners,
)
from router_support.route_capability_contracts import (
    compare_capability_contract,
    ordered_secondary_capabilities,
)
from router_support.route_constraints import glob_match, required_checks_for, scoped_owner_modules
from router_support.route_read_paths import build_required_read_paths
from router_support.route_authorization import (
    authorization_audit_fields,
    route_authorization_fingerprint,
    routing_truth_digest,
)
from router_support.reuse_scan import (
    ReuseScanBudget,
    ReuseScanEnvironment,
    changed_path_candidate_files as _changed_path_candidate_files,
)
from router_support.reuse_scan_engine import (
    gather_reuse_report as _gather_reuse_report,
)
from router_support.route_intent import (
    high_risk_keyword_scope as _high_risk_keyword_scope,
    module_path_proximity,
    owner_evidence_paths as _owner_evidence_paths,
    parse_request_type,
    positive_request_scope as _positive_request_scope,
    request_additive_intent,
    request_duplicate_signal,
    request_duplicates_existing_owner,
    request_has_high_risk_keyword as _request_has_high_risk_keyword,
    request_has_phrase as _request_has_phrase,
    request_lifecycle_intent,
    request_lifecycle_target,
    request_prefers_extract,
    request_prefers_reuse,
    request_requires_review,
    request_requires_sensitive_review,
    request_targets_existing_capability,
)
from router_support.structure_guardrails import refresh_profile_structure_guardrails


DEFAULT_IGNORE_GLOBS = [
    "**/.git/**",
    "**/.hg/**",
    "**/.svn/**",
    "**/.idea/**",
    "**/.vscode/**",
    "**/.pytest_cache/**",
    "**/__pycache__/**",
    "**/node_modules/**",
    "**/.next/**",
    "**/.nuxt/**",
    "**/dist/**",
    "**/build/**",
    "**/target/**",
    "**/coverage/**",
    "**/.venv/**",
    "**/venv/**",
    "**/.mypy_cache/**",
    "**/*.min.js",
    "**/*.class",
    "**/*.log",
]

CODE_SUFFIXES = {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".sql"}
MANIFEST_FILES = [
    "pom.xml",
    "package.json",
    "pnpm-workspace.yaml",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "settings.gradle",
    "settings.gradle.kts",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "Cargo.toml",
]
ROOT_MARKERS = [".git", *MANIFEST_FILES]
GENERIC_CONTAINER_NAMES = {
    "src",
    "app",
    "apps",
    "services",
    "packages",
    "libs",
    "modules",
    "backend",
    "frontend",
    "clients",
    "server",
}
GENERIC_PATH_TOKENS = {
    "src",
    "app",
    "apps",
    "services",
    "packages",
    "libs",
    "modules",
    "backend",
    "frontend",
    "clients",
    "server",
    "internal",
    "pkg",
    "lib",
    "main",
    "java",
    "python",
    "ts",
    "js",
    "common",
}
DEFAULT_HIGH_RISK_KEYWORDS = [
    "auth",
    "authentication",
    "authorization",
    "identity",
    "permission",
    "rbac",
    "tenant",
    "workspace",
    "billing",
    "payment",
    "invoice",
    "refund",
    "subscription",
    "entitlement",
    "quota",
    "security",
    "secret",
    "token",
    "credential",
    "crypto",
    "migration",
    "schema",
    "webhook",
    "gateway",
]
PRIVATE_SEGMENTS = {"internal", "private", "impl", "_internal", "_private"}
EXTENSION_FILE_MARKERS = ("plugin", "registry", "hook", "extension", "adapter", "interface", "port")
CHANGE_VERBS = ("add", "change", "extend", "modify", "update", "introduce", "create", "implement", "fix", "refactor", "增加", "变更", "扩展", "修改", "新增", "实现", "修复", "重构")

@dataclass
class ModuleEntry:
    id: str
    path: str
    layer: str
    domain: str
    purpose: str
    public_api: Optional[str] = None
    source_of_truth: str = "generated"
    key_files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    allowed_inbound_from: list[str] = field(default_factory=list)
    allowed_outbound_to: list[str] = field(default_factory=list)
    generated: bool = True
    index_sources: list[str] = field(default_factory=list)
    owner: str = "unassigned"
    status: str = "active"
    lifecycle: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class CapabilityEntry:
    id: str
    name: str
    status: str
    maturity: str
    stage: str = "candidate"
    source_of_truth: str = "generated"
    intent_keywords: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    business_intents: list[str] = field(default_factory=list)
    scope: dict[str, Any] = field(default_factory=dict)
    owner_modules: list[str] = field(default_factory=list)
    public_entries: list[str] = field(default_factory=list)
    extension_points: list[str] = field(default_factory=list)
    route_defaults: dict[str, Any] = field(default_factory=dict)
    contracts: list[Any] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    test_bindings: list[dict[str, Any]] = field(default_factory=list)
    forbidden_patterns: list[str] = field(default_factory=list)
    dependent_modules: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    lifecycle: dict[str, Any] = field(default_factory=dict)
    last_verified_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class RouteDecision:
    decision_id: str
    timestamp: str
    request_type: str
    request_summary: str
    changed_paths: list[str]
    repo_stage: str
    action: str
    decision_basis: str
    routing_confidence: float
    routing_confidence_level: str
    decision_confidence: float
    decision_confidence_level: str
    confidence: float
    confidence_level: str
    overlap_score: float
    primary_capability: Optional[str]
    primary_capability_stage: Optional[str]
    secondary_capabilities: list[str]
    candidate_capabilities: list[dict[str, Any]]
    candidate_modules: list[dict[str, Any]]
    required_reads: list[str]
    required_checks: list[str]
    forbidden_paths: list[str]
    review_required: bool
    coordination_required: bool
    composite_route_required: bool
    recommended_next_action: str
    recommended_next_steps: list[str]
    why_not_actions: dict[str, Any]
    block_reason: dict[str, Any]
    missing_evidence: list[dict[str, Any]]
    analysis_directions: list[str]
    safe_next_steps: list[str]
    suggested_questions: list[str]
    profile_repair_hints: list[dict[str, Any]]
    override_requirements: list[dict[str, Any]]
    allowed_write_paths: list[str]
    forbidden_write_paths: list[str]
    must_read_before_edit: list[str]
    post_change_closeout: list[dict[str, Any]]
    composite_route: dict[str, Any]
    capability_lifecycle_action: dict[str, Any]
    evaluation_regression_hints: list[dict[str, Any]]
    confidence_reasons: list[str]
    veto_reasons: list[str]
    positive_signals: dict[str, Any]
    negative_signals: dict[str, Any]
    risk_signals: dict[str, Any]
    reasoning: list[str]
    authorization_context: dict[str, Any]
    route_fingerprint: str
    source_of_truths: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parent.parent


def profile_dir(skill_root: Optional[Path] = None) -> Path:
    return (skill_root or project_root_from_file()) / "profiles"


def schema_dir(skill_root: Optional[Path] = None) -> Path:
    return (skill_root or project_root_from_file()) / "schemas"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_date() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def safe_parse_date(value: Optional[str]) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_rel_path(root: Path, path: Path | str) -> str:
    root = root.resolve()
    value = Path(path).resolve()
    try:
        return value.relative_to(root).as_posix()
    except ValueError:
        return value.as_posix()


def stable_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "item"


def title_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in stable_slug(value).split("-") if part) or "Capability"


def stage_rank(stage: str) -> int:
    order = {
        "seed": 0,
        "emerging": 1,
        "structured": 2,
        "governed": 3,
        "provisional": 0,
        "candidate": 1,
        "stable": 2,
        "governed-capability": 3,
    }
    return order.get(stage, 0)


def confidence_level_for(score: float) -> str:
    if score >= 0.80:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def decision_confidence_for(
    action: str,
    repo_stage: str,
    routing_confidence: float,
    veto_reasons: list[str],
    high_risk: bool,
) -> tuple[float, str, str]:
    if action == "review":
        if repo_stage == "seed" and veto_reasons:
            return 0.95, "high", "policy_guardrail"
        if veto_reasons or high_risk:
            return 0.9, "high", "policy_guardrail"
        if routing_confidence < 0.55:
            return 0.8, "medium", "insufficient_route_evidence"
        return 0.7, "medium", "guarded_review"
    if action == "new":
        if repo_stage == "seed":
            return 0.9, "high", "policy_guardrail"
        if routing_confidence < 0.55:
            return 0.75, "medium", "capability_gap"
        return 0.7, "medium", "capability_gap"
    if action == "reuse":
        score = max(0.7, routing_confidence)
        return score, confidence_level_for(score), "capability_match"
    if action == "extend":
        score = max(0.72, routing_confidence)
        return score, confidence_level_for(score), "capability_match"
    score = max(0.72, routing_confidence)
    return score, confidence_level_for(score), "capability_match"


def text_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", text.lower()) if token]


def match_strength(text: str, keywords: Iterable[str]) -> float:
    lower = text.lower()
    best = 0.0
    for keyword in keywords:
        candidate = keyword.lower().strip()
        if not candidate:
            continue
        if candidate in lower:
            return 1.0
        parts = [part for part in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", candidate) if part]
        if parts and any(part in lower for part in parts):
            best = max(best, 0.5)
    return best


def current_git_commit(repo_root: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def default_ignore_patterns(config: dict[str, Any]) -> list[str]:
    patterns = list(DEFAULT_IGNORE_GLOBS)
    patterns.extend(config.get("ignore_paths", []))
    return list(dict.fromkeys(patterns))


def should_ignore_path(path: Path, ignore_patterns: Iterable[str], root: Path) -> bool:
    rel = normalize_rel_path(root, path)
    return glob_match(ignore_patterns, rel)


def iter_source_files(root: Path, ignore_patterns: Iterable[str]) -> Iterator[Path]:
    if root.is_file():
        if root.suffix.lower() in CODE_SUFFIXES | {".json", ".yaml", ".yml", ".xml", ".toml"}:
            yield root
        return
    for base, dirs, files in os.walk(root):
        base_path = Path(base)
        dirs[:] = [
            name for name in dirs if not should_ignore_path(base_path / name, ignore_patterns, root)
        ]
        for filename in files:
            path = base_path / filename
            if should_ignore_path(path, ignore_patterns, root):
                continue
            if path.suffix.lower() in CODE_SUFFIXES | {".json", ".yaml", ".yml", ".xml", ".toml"}:
                yield path


def contains_code(path: Path, suffixes: Optional[set[str]] = None) -> bool:
    suffixes = suffixes or CODE_SUFFIXES
    if path.is_file():
        return path.suffix.lower() in suffixes
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in suffixes:
            return True
    return False


def repo_root_from(start: Path | str | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    bundle_marker = Path("project-change-router") / "router-config.yaml"
    best: Optional[Path] = None
    best_score = -1
    for candidate in [current, *current.parents]:
        if (candidate / bundle_marker).exists():
            return candidate
        score = 0
        if (candidate / ".git").exists():
            score += 100
        score += sum(10 for marker in MANIFEST_FILES if (candidate / marker).exists())
        if any((candidate / child).exists() for child in ("src", "app", "services", "packages", "libs")):
            score += 3
        if score > best_score:
            best = candidate
            best_score = score
    return best or current


def load_bundle(bundle_root: Path) -> dict[str, Any]:
    router_config_path = bundle_root / "router-config.yaml"
    if not router_config_path.exists():
        return {}
    references = bundle_root / "references"
    bundle = {
        "root": bundle_root,
        "config": load_yaml_file(router_config_path),
        "capability_catalog": load_yaml_file(references / "capability-catalog.yaml"),
        "module_map": load_yaml_file(references / "module-map.yaml"),
        "ownership": load_yaml_file(references / "ownership.yaml"),
        "change_rules": load_yaml_file(references / "change-rules.yaml"),
        "path_to_capability_map": load_yaml_file(references / "path-to-capability-map.yaml"),
        "exception_registry": load_yaml_file(references / "exception-registry.yaml"),
        "evaluation_set": load_yaml_file(references / "evaluation-set.yaml"),
    }
    return bundle


def manual_feedback_dir(bundle_root: Path) -> Path:
    return bundle_root / "reports" / "manual-feedback"


def load_manual_feedback(bundle_root: Path) -> list[dict[str, Any]]:
    directory = manual_feedback_dir(bundle_root)
    if not directory.exists():
        return []
    feedback_items: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            feedback_items.append(load_json_file(path))
        except Exception:
            continue
    return feedback_items


def feedback_summary(feedback_items: list[dict[str, Any]]) -> dict[str, Any]:
    by_capability: dict[str, int] = defaultdict(int)
    confirmations = 0
    profile_updates = 0
    for item in feedback_items:
        capability = item.get("final_capability")
        if capability:
            by_capability[str(capability)] += 1
        if item.get("confirmed_owner") or item.get("confirmed_public_entry"):
            confirmations += 1
        if item.get("profile_update_recommended"):
            profile_updates += 1
    return {
        "feedback_count": len(feedback_items),
        "confirmed_boundary_count": confirmations,
        "profile_update_recommended_count": profile_updates,
        "capability_confirmation_counts": dict(by_capability),
    }


def resolve_bundle_root(repo_root: Path) -> Path:
    return repo_root / "project-change-router"


def validate_against_schema(data: dict[str, Any], schema_path: Path) -> list[str]:
    schema = load_json_file(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors]


def validate_bundle(bundle_root: Path, skill_root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    schema_root = schema_dir(skill_root)
    refs = bundle_root / "references"
    files_and_schemas = [
        (bundle_root / "router-config.yaml", schema_root / "router-config.schema.json"),
        (refs / "capability-catalog.yaml", schema_root / "capability-catalog.schema.json"),
        (refs / "module-map.yaml", schema_root / "module-map.schema.json"),
        (refs / "ownership.yaml", schema_root / "ownership.schema.json"),
        (refs / "change-rules.yaml", schema_root / "change-rules.schema.json"),
        (refs / "path-to-capability-map.yaml", schema_root / "path-to-capability-map.schema.json"),
        (refs / "exception-registry.yaml", schema_root / "exception-registry.schema.json"),
        (refs / "evaluation-set.yaml", schema_root / "evaluation-set.schema.json"),
    ]
    for file_path, schema_path in files_and_schemas:
        if not file_path.exists():
            errors.append(f"missing file: {file_path}")
            continue
        if not schema_path.exists():
            errors.append(f"missing schema: {schema_path}")
            continue
        prefix = f"{file_path.name}: "
        errors.extend([prefix + item for item in validate_against_schema(load_yaml_file(file_path), schema_path)])
    return errors


def validate_bundle_files(bundle_root: Path) -> list[str]:
    return validate_bundle(bundle_root)


def schema_files() -> list[str]:
    return sorted(path.name for path in schema_dir().glob("*.json"))


def file_suffix_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".java":
        return "java"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    return "text"


def parse_xml_modules(pom_path: Path) -> list[str]:
    tree = ET.parse(pom_path)
    root = tree.getroot()
    ns = {"m": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    query = ".//m:modules/m:module" if ns else ".//modules/module"
    result = []
    for node in root.findall(query, ns):
        text = (node.text or "").strip()
        if text:
            result.append(text.replace("\\", "/"))
    return result


def parse_xml_dependencies(pom_path: Path) -> list[str]:
    tree = ET.parse(pom_path)
    root = tree.getroot()
    ns = {"m": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    query = ".//m:dependencies/m:dependency" if ns else ".//dependencies/dependency"
    deps: list[str] = []
    for node in root.findall(query, ns):
        artifact = node.findtext("m:artifactId", default="", namespaces=ns) if ns else node.findtext("artifactId", default="")
        if artifact:
            deps.append(artifact.strip())
    return deps


def parse_package_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def detect_repo_manifest_kind(repo_root: Path) -> str:
    if (repo_root / "pom.xml").exists():
        return "maven"
    if (repo_root / "pnpm-workspace.yaml").exists() or (repo_root / "package.json").exists():
        return "node"
    if (repo_root / "pyproject.toml").exists() or (repo_root / "requirements.txt").exists() or (repo_root / "setup.py").exists():
        return "python"
    if (repo_root / "settings.gradle").exists() or (repo_root / "settings.gradle.kts").exists():
        return "gradle"
    return "generic"


def derive_path_tokens(path: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z]+", path.lower().replace("\\", "/")) if token]


def extract_domain_from_path(path: str) -> str:
    tokens = [token for token in derive_path_tokens(path) if token not in GENERIC_PATH_TOKENS]
    return tokens[-1] if tokens else Path(path).name.lower()


def classify_layer(path: str, package_name: Optional[str] = None) -> str:
    haystack = " ".join([path.lower().replace("\\", "/"), package_name or ""])
    if any(token in haystack for token in ("frontend", "web", "ui", "admin", "mobile", "client")):
        return "ui"
    if any(token in haystack for token in ("infra", "ops", "deploy", "database", "migration", "storage", "queue", "broker", "config")):
        return "infra"
    if any(token in haystack for token in ("sdk", "adapter", "integration", "transport", "api", "gateway", "cli")):
        return "adapter"
    if any(token in haystack for token in ("shared", "common", "core", "platform", "security", "billing", "tenant", "auth", "identity")):
        return "shared-capability"
    if any(token in haystack for token in ("feature", "experience", "product", "workflow", "story")):
        return "feature-module"
    return "domain-service"


def infer_allowed_layers(layer: str) -> list[str]:
    matrix = {
        "ui": ["adapter", "domain-service", "shared-capability", "infra", "feature-module"],
        "feature-module": ["adapter", "domain-service", "shared-capability", "infra"],
        "adapter": ["domain-service", "shared-capability", "infra", "adapter"],
        "domain-service": ["domain-service", "shared-capability", "infra"],
        "shared-capability": ["shared-capability", "infra"],
        "infra": ["infra", "shared-capability", "domain-service"],
    }
    return matrix.get(layer, ["domain-service", "shared-capability", "infra"])


def directory_code_files(path: Path, suffixes: Optional[set[str]] = None) -> list[Path]:
    suffixes = suffixes or CODE_SUFFIXES
    files: list[Path] = []
    for candidate in path.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in suffixes:
            files.append(candidate)
    return files


def choose_key_files(module_root: Path, preferred: list[str]) -> list[str]:
    selected: list[str] = []
    for rel in preferred:
        candidate = module_root / rel
        if candidate.exists():
            selected.append(rel.replace("\\", "/"))
    if selected:
        return selected[:6]
    fallback = []
    for candidate in directory_code_files(module_root)[:6]:
        fallback.append(candidate.relative_to(module_root).as_posix())
    return fallback


def java_source_roots(module_root: Path) -> list[str]:
    roots = []
    for rel in ("src/main/java", "src/main/kotlin", "src/test/java"):
        if (module_root / rel).exists():
            roots.append(rel)
    return roots


def infer_java_packages(module_root: Path) -> list[str]:
    packages: set[str] = set()
    for source_root in java_source_roots(module_root):
        for file in (module_root / source_root).rglob("*.java"):
            text = file.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r"^\s*package\s+([\w\.]+)\s*;", text, flags=re.M)
            if match:
                package = match.group(1)
                parts = package.split(".")
                if len(parts) >= 2:
                    packages.add(".".join(parts[:2]))
                packages.add(package)
    return sorted(packages)


def maven_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    root_pom = repo_root / "pom.xml"
    if not root_pom.exists():
        return []
    declared = parse_xml_modules(root_pom)
    if not declared:
        declared = ["."]
    artifact_lookup: dict[str, str] = {}
    entries: list[ModuleEntry] = []
    for rel in declared:
        module_root = (repo_root / rel).resolve()
        if not module_root.exists() or should_ignore_path(module_root, ignore_patterns, repo_root):
            continue
        pom_path = module_root / "pom.xml"
        deps = parse_xml_dependencies(pom_path) if pom_path.exists() else []
        package_prefixes = infer_java_packages(module_root)
        manifest_sources = ["pom.xml"]
        key_files = choose_key_files(module_root, ["pom.xml", "src/main/java", "src/main/resources", "src/test/java"])
        module_path = rel.replace("\\", "/")
        if module_path == ".":
            module_path = "."
        artifact_lookup[module_root.name] = module_path
        entries.append(
            ModuleEntry(
                id=f"module-{stable_slug(module_path if module_path != '.' else repo_root.name)}",
                path=module_path,
                layer=classify_layer(module_path),
                domain=extract_domain_from_path(module_path if module_path != "." else repo_root.name),
                purpose=f"Java module at {module_path}",
                public_api=java_source_roots(module_root)[0] if java_source_roots(module_root) else None,
                key_files=key_files,
                depends_on=deps,
                index_sources=manifest_sources,
                lifecycle={
                    "language": "java",
                    "manifest": normalize_rel_path(repo_root, pom_path) if pom_path.exists() else None,
                    "artifact_name": module_root.name,
                    "package_prefixes": package_prefixes,
                    "source_roots": java_source_roots(module_root),
                    "import_names": package_prefixes or [module_root.name],
                    "allowed_outbound_layers": infer_allowed_layers(classify_layer(module_path)),
                },
            )
        )
    for entry in entries:
        entry.depends_on = sorted({artifact_lookup.get(dep, dep) for dep in entry.depends_on if artifact_lookup.get(dep, dep) != entry.path and artifact_lookup.get(dep, dep) in {item.path for item in entries}})
    return entries


def node_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    package_files = [path for path in repo_root.rglob("package.json") if not should_ignore_path(path, ignore_patterns, repo_root)]
    manifest_to_name: dict[Path, str] = {}
    for package_file in package_files:
        data = parse_package_json(package_file)
        name = str(data.get("name") or package_file.parent.name)
        manifest_to_name[package_file.parent.resolve()] = name
    path_lookup = {name: normalize_rel_path(repo_root, path) for path, name in manifest_to_name.items()}
    for package_file in package_files:
        module_root = package_file.parent
        data = parse_package_json(package_file)
        module_path = normalize_rel_path(repo_root, module_root)
        package_name = str(data.get("name") or module_root.name)
        public_api = None
        for candidate in ("src/index.ts", "src/index.tsx", "src/index.js", "src/index.jsx", "index.ts", "index.js"):
            if (module_root / candidate).exists():
                public_api = candidate
                break
        if public_api is None and data.get("exports"):
            public_api = "package.json"
        deps: set[str] = set()
        for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for dep_name in (data.get(section) or {}).keys():
                target = path_lookup.get(dep_name)
                if target and target != module_path:
                    deps.add(target)
        entries.append(
            ModuleEntry(
                id=f"module-{stable_slug(module_path)}",
                path=module_path,
                layer=classify_layer(module_path, package_name),
                domain=extract_domain_from_path(module_path),
                purpose=str(data.get("description") or f"Node package {package_name}"),
                public_api=public_api,
                key_files=choose_key_files(module_root, ["package.json", "src/index.ts", "src/index.js", "src/main.ts", "src/App.tsx"]),
                depends_on=sorted(deps),
                index_sources=[normalize_rel_path(repo_root, package_file)],
                lifecycle={
                    "language": "node",
                    "manifest": normalize_rel_path(repo_root, package_file),
                    "package_name": package_name,
                    "import_names": [package_name, module_root.name],
                    "source_roots": ["src"] if (module_root / "src").exists() else ["."],
                    "allowed_outbound_layers": infer_allowed_layers(classify_layer(module_path, package_name)),
                },
            )
        )
    return entries


def candidate_python_dirs(repo_root: Path, ignore_patterns: Iterable[str]) -> list[Path]:
    candidates: set[Path] = set()
    src_root = repo_root / "src"
    if src_root.exists():
        for child in src_root.iterdir():
            if child.is_dir() and not should_ignore_path(child, ignore_patterns, repo_root) and contains_code(child, {".py"}):
                candidates.add(child)
    for child in repo_root.iterdir():
        if not child.is_dir() or should_ignore_path(child, ignore_patterns, repo_root):
            continue
        if child.name.startswith("."):
            continue
        if (child / "__init__.py").exists():
            candidates.add(child)
            continue
        py_files = list(child.glob("*.py"))
        if py_files:
            candidates.add(child)
            continue
        if child.name in GENERIC_CONTAINER_NAMES and contains_code(child, {".py"}):
            for grandchild in child.iterdir():
                if grandchild.is_dir() and contains_code(grandchild, {".py"}):
                    candidates.add(grandchild)
            if not any(item.parent == child for item in candidates) and contains_code(child, {".py"}):
                candidates.add(child)
    if not candidates and any((repo_root / marker).exists() for marker in ("pyproject.toml", "requirements.txt", "setup.py")) and contains_code(repo_root, {".py"}):
        candidates.add(repo_root)
    return sorted(candidates)


def python_import_roots(module_root: Path) -> list[str]:
    roots: list[str] = []
    if module_root == module_root.parent / module_root.name and (module_root / "__init__.py").exists():
        roots.append(module_root.name)
    for candidate in module_root.iterdir() if module_root.is_dir() else []:
        if candidate.is_dir() and (candidate / "__init__.py").exists():
            roots.append(candidate.name)
    if (module_root / "__init__.py").exists():
        roots.append(module_root.name)
    return sorted(set(roots))


def python_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    for module_root in candidate_python_dirs(repo_root, ignore_patterns):
        module_path = normalize_rel_path(repo_root, module_root)
        if module_path == ".":
            module_path = "."
        import_names = python_import_roots(module_root)
        public_api = "__init__.py" if (module_root / "__init__.py").exists() else None
        if public_api is None:
            for candidate in ("main.py", "app.py", "service.py", "api.py"):
                if (module_root / candidate).exists():
                    public_api = candidate
                    break
        layer = classify_layer(module_path)
        entries.append(
            ModuleEntry(
                id=f"module-{stable_slug(module_path if module_path != '.' else repo_root.name)}",
                path=module_path,
                layer=layer,
                domain=extract_domain_from_path(module_path if module_path != "." else repo_root.name),
                purpose=f"Python module at {module_path}",
                public_api=public_api,
                key_files=choose_key_files(module_root, ["__init__.py", "main.py", "app.py", "service.py", "api.py"]),
                index_sources=[module_path],
                lifecycle={
                    "language": "python",
                    "import_names": import_names or [module_root.name],
                    "source_roots": ["."],
                    "allowed_outbound_layers": infer_allowed_layers(layer),
                },
            )
        )
    return entries


def generic_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    top_level_code_dirs = []
    for child in repo_root.iterdir():
        if not child.is_dir() or should_ignore_path(child, ignore_patterns, repo_root):
            continue
        if child.name.startswith(".") or child.name in {"project-change-router"}:
            continue
        if contains_code(child):
            top_level_code_dirs.append(child)
    for module_root in top_level_code_dirs:
        module_path = normalize_rel_path(repo_root, module_root)
        layer = classify_layer(module_path)
        entries.append(
            ModuleEntry(
                id=f"module-{stable_slug(module_path)}",
                path=module_path,
                layer=layer,
                domain=extract_domain_from_path(module_path),
                purpose=f"Source module at {module_path}",
                public_api=None,
                key_files=choose_key_files(module_root, []),
                index_sources=[module_path],
                lifecycle={
                    "language": "generic",
                    "import_names": [module_root.name],
                    "source_roots": ["."],
                    "allowed_outbound_layers": infer_allowed_layers(layer),
                },
            )
        )
    if not entries and contains_code(repo_root):
        entries.append(
            ModuleEntry(
                id=f"module-{stable_slug(repo_root.name)}",
                path=".",
                layer="domain-service",
                domain=extract_domain_from_path(repo_root.name),
                purpose="Root workspace module",
                public_api=None,
                key_files=choose_key_files(repo_root, []),
                index_sources=["."],
                lifecycle={
                    "language": "generic",
                    "import_names": [repo_root.name],
                    "source_roots": ["."],
                    "allowed_outbound_layers": infer_allowed_layers("domain-service"),
                },
            )
        )
    return entries


def dedupe_modules(modules: list[ModuleEntry], repo_root: Path) -> list[ModuleEntry]:
    by_path: dict[str, ModuleEntry] = {}
    for module in modules:
        existing = by_path.get(module.path)
        if not existing:
            by_path[module.path] = module
            continue
        existing_score = len(existing.index_sources) + len(existing.key_files) + len(existing.depends_on)
        new_score = len(module.index_sources) + len(module.key_files) + len(module.depends_on)
        if new_score > existing_score:
            by_path[module.path] = module
    result = list(by_path.values())
    drop_paths: set[str] = set()
    paths = {module.path for module in result}
    for module in result:
        if module.path == ".":
            if len(result) > 1:
                drop_paths.add(".")
            continue
        if Path(module.path).name in GENERIC_CONTAINER_NAMES:
            prefix = module.path.rstrip("/") + "/"
            if any(other != module.path and other.startswith(prefix) for other in paths):
                root = repo_root / module.path
                direct_code = any(candidate.is_file() and candidate.suffix.lower() in CODE_SUFFIXES for candidate in root.glob("*")) if root.exists() else False
                if not direct_code:
                    drop_paths.add(module.path)
    return sorted([module for module in result if module.path not in drop_paths], key=lambda item: (item.path.count("/"), item.path))


def discover_languages(repo_root: Path, modules: list[ModuleEntry]) -> list[str]:
    languages: set[str] = set()
    for file in iter_source_files(repo_root, DEFAULT_IGNORE_GLOBS):
        kind = file_suffix_kind(file)
        if kind != "text":
            languages.add(kind)
    if not languages:
        for module in modules:
            language = str(module.lifecycle.get("language") or "")
            if language and language != "generic":
                languages.add(language)
    return sorted(languages or {"generic"})


def count_cross_module_edges(modules: list[ModuleEntry]) -> int:
    return sum(1 for module in modules for dep in module.depends_on if dep != module.path)


def meaningful_module_count(modules: list[ModuleEntry]) -> int:
    count = 0
    for module in modules:
        if module.path == ".":
            continue
        if Path(module.path).name.lower() not in GENERIC_CONTAINER_NAMES:
            count += 1
    return count


def profile_signal_counts(profile: dict[str, Any]) -> dict[str, int]:
    capability_count = len(profile.get("capabilities", []))
    owner_rule_count = len(profile.get("ownership_rules", []))
    public_api_override_count = sum(1 for rule in profile.get("module_overrides", []) if "public_api" in rule)
    return {
        "profile_capability_count": capability_count,
        "profile_owner_rule_count": owner_rule_count,
        "profile_public_api_override_count": public_api_override_count,
    }


def profile_stage(profile: dict[str, Any]) -> str:
    return str(profile.get("profile_stage") or "provisional").lower()


def heuristic_public_entry_ratio(modules: list[ModuleEntry]) -> float:
    considered = [module for module in modules if module.public_api]
    if not considered:
        return 1.0
    heuristic = 0
    for module in considered:
        entry = (module.public_api or "").lower()
        if entry in {"__init__.py", "index.ts", "index.js", "index.tsx", "index.jsx"}:
            heuristic += 1
    return heuristic / max(1, len(considered))


def provisional_owner_ratio(modules: list[ModuleEntry]) -> float:
    if not modules:
        return 1.0
    provisional = 0
    for module in modules:
        owner = (module.owner or "").lower()
        if owner in {"unassigned", "platform-owners"} or owner.startswith("provisional:") or owner.endswith("-owners"):
            provisional += 1
    return provisional / len(modules)


def generated_only_ratio(capabilities: list[CapabilityEntry]) -> float:
    if not capabilities:
        return 1.0
    generated = sum(1 for capability in capabilities if capability.source_of_truth == "generated")
    return generated / len(capabilities)


def count_tests(repo_root: Path) -> tuple[int, int]:
    test_files = []
    test_dirs = [repo_root / "tests", repo_root / "test", repo_root / "src" / "test", repo_root / "src" / "tests"]
    for root in test_dirs:
        if root.exists():
            test_files.extend([path for path in root.rglob("*") if path.is_file()])
    module_like_tests = sum(1 for file in test_files if file.suffix.lower() in CODE_SUFFIXES)
    return len(test_files), module_like_tests


def detect_boundary_evidence(repo_root: Path) -> bool:
    patterns = ["*.proto", "*openapi*.yml", "*openapi*.yaml", "*schema*.json", "*swagger*.yaml", "*swagger*.yml"]
    for pattern in patterns:
        if list(repo_root.rglob(pattern)):
            return True
    return False


def evaluation_mode(capabilities: list[CapabilityEntry], profile: dict[str, Any]) -> str:
    if profile.get("evaluation", {}).get("mode") == "curated":
        return "curated"
    if any(capability.source_of_truth == "profile" for capability in capabilities):
        return "hybrid"
    return "generated_only"


def detect_branch_mode(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    branch = result.stdout.strip()
    if not branch:
        return "unknown"
    if branch in {"main", "master", "develop"}:
        return "default"
    return "feature"


def classify_repo_stage(modules: list[ModuleEntry], capabilities: list[CapabilityEntry], profile: dict[str, Any], repo_root: Path, feedback_items: Optional[list[dict[str, Any]]] = None) -> tuple[str, dict[str, Any]]:
    feedback_items = feedback_items or []
    feedback_meta = feedback_summary(feedback_items)
    profile_counts = profile_signal_counts(profile)
    has_profile = bool(profile)
    explicit_profile_stage = profile_stage(profile)
    has_codeowners = bool(load_codeowners(repo_root))
    has_ci = has_standard_ci_surface(repo_root)
    boundary_evidence = detect_boundary_evidence(repo_root)
    module_count = len(modules)
    meaningful_count = meaningful_module_count(modules)
    cross_edges = count_cross_module_edges(modules)
    languages = discover_languages(repo_root, modules)
    tests_total, module_tests = count_tests(repo_root)
    heuristic_ratio = heuristic_public_entry_ratio(modules)
    provisional_ratio = provisional_owner_ratio(modules)
    stable_caps = sum(1 for capability in capabilities if capability.stage in {"stable", "governed-capability"} or capability.status == "stable")
    candidate_caps = sum(1 for capability in capabilities if capability.stage == "candidate" or capability.status == "candidate")
    provisional_caps = sum(1 for capability in capabilities if capability.stage == "provisional")
    capability_signals_available = bool(capabilities)
    generated_ratio = generated_only_ratio(capabilities)
    eval_mode = evaluation_mode(capabilities, profile)
    branch_mode = detect_branch_mode(repo_root)

    reasons: list[str] = []
    score = 0

    if module_count <= 1 or meaningful_count <= 1:
        reasons.append("very few meaningful modules discovered")
    else:
        score += 1
        reasons.append(f"{meaningful_count} meaningful modules discovered")
    if meaningful_count >= 4:
        score += 1
    if cross_edges > 0:
        score += 1
        reasons.append(f"{cross_edges} cross-module dependencies discovered")
    if boundary_evidence:
        score += 1
        reasons.append("shared schema or boundary evidence discovered")
    if has_profile:
        score += 1
        reasons.append("repository profile present")
    if profile_counts["profile_capability_count"] > 0:
        score += 2
        reasons.append(f"{profile_counts['profile_capability_count']} profile-backed capabilities declared")
    if has_codeowners:
        score += 1
        reasons.append("CODEOWNERS present")
    if has_ci:
        score += 1
        reasons.append("CI configuration present")
    if tests_total > 0:
        score += 1
        reasons.append(f"{tests_total} test files discovered")
    if eval_mode == "curated":
        score += 2
        reasons.append("curated evaluation mode enabled")
    elif eval_mode == "generated_only":
        reasons.append("evaluation set is generated-only")
    if feedback_meta["confirmed_boundary_count"] > 0:
        score += 1
        reasons.append(f"{feedback_meta['confirmed_boundary_count']} manual boundary confirmations recorded")
    if capability_signals_available and heuristic_ratio >= 0.8:
        score -= 2
        reasons.append("public entries are mostly heuristic")
    elif not capability_signals_available and heuristic_ratio >= 0.8:
        reasons.append("public entries are mostly heuristic")
    if capability_signals_available and provisional_ratio >= 0.8:
        score -= 2
        reasons.append("ownership is mostly provisional")
    elif not capability_signals_available and provisional_ratio >= 0.8:
        reasons.append("ownership is mostly provisional")
    if capability_signals_available and generated_ratio >= 0.8:
        score -= 2
        reasons.append("most capabilities are generated rather than curated")
    elif not capability_signals_available and generated_ratio >= 0.8:
        reasons.append("most capabilities are generated rather than curated")
    if branch_mode == "feature":
        score -= 1
        reasons.append("current worktree is on a non-default branch")

    seed_gate = (
        meaningful_count <= 1
        or (
            meaningful_count <= 1
            and profile_counts["profile_capability_count"] == 0
            and stable_caps == 0
            and module_tests == 0
        )
        or heuristic_ratio >= 0.9 and provisional_ratio >= 0.9
    )
    governed_gate = (
        has_profile
        and has_ci
        and has_codeowners
        and profile_counts["profile_capability_count"] >= 2
        and stable_caps >= 2
        and provisional_ratio < 0.4
        and heuristic_ratio < 0.4
        and eval_mode != "generated_only"
    )
    structured_gate = (
        meaningful_count >= 3
        and cross_edges >= 1
        and (profile_counts["profile_capability_count"] > 0 or stable_caps >= 1)
    )

    if explicit_profile_stage == "governed":
        stage = "governed"
    elif explicit_profile_stage == "structured":
        stage = "structured"
    elif explicit_profile_stage == "emerging" and not seed_gate:
        stage = "emerging"
    elif governed_gate:
        stage = "governed"
    elif seed_gate and score <= 2:
        stage = "seed"
    elif structured_gate and score >= 6:
        stage = "structured"
    else:
        stage = "emerging"

    signal_payload = {
        "module_count": module_count,
        "meaningful_module_count": meaningful_count,
        "cross_module_edges": cross_edges,
        "language_count": len(languages),
        "has_profile": has_profile,
        "profile_stage": explicit_profile_stage,
        "profile_capability_count": profile_counts["profile_capability_count"],
        "profile_owner_rule_count": profile_counts["profile_owner_rule_count"],
        "profile_public_api_override_count": profile_counts["profile_public_api_override_count"],
        "has_codeowners": has_codeowners,
        "has_ci": has_ci,
        "shared_boundary_evidence": boundary_evidence,
        "stable_capability_count": stable_caps,
        "candidate_capability_count": candidate_caps,
        "provisional_capability_count": provisional_caps,
        "provisional_owner_ratio": round(provisional_ratio, 4),
        "heuristic_public_entry_ratio": round(heuristic_ratio, 4),
        "generated_only_ratio": round(generated_ratio, 4),
        "test_file_count": tests_total,
        "module_with_tests_count": module_tests,
        "evaluation_mode": eval_mode,
        "branch_mode": branch_mode,
        "manual_feedback_count": feedback_meta["feedback_count"],
        "confirmed_boundary_count": feedback_meta["confirmed_boundary_count"],
        "profile_update_recommended_count": feedback_meta["profile_update_recommended_count"],
    }
    return stage, {
        "repo_stage": stage,
        "stage_score": score,
        "stage_reasons": reasons,
        "signals": signal_payload,
    }


def discover_repositories(repo_root: Path, modules: list[ModuleEntry]) -> list[dict[str, Any]]:
    repositories = [{"id": repo_root.name, "path": ".", "type": detect_repo_manifest_kind(repo_root)}]
    top_level_paths = {module.path.split("/")[0] for module in modules if module.path not in {".", ""}}
    for item in sorted(top_level_paths):
        candidate = repo_root / item
        if candidate.is_dir() and any((candidate / marker).exists() for marker in MANIFEST_FILES):
            repositories.append({"id": item, "path": item, "type": detect_repo_manifest_kind(candidate)})
    return repositories


def public_import_names(module: ModuleEntry) -> list[str]:
    names = []
    names.extend(module.lifecycle.get("import_names", []))
    package_name = module.lifecycle.get("package_name")
    if package_name:
        names.append(str(package_name))
    domain = module.domain
    if domain:
        names.append(domain)
    return list(dict.fromkeys(name for name in names if name))


def module_for_path(path: str, modules: list[ModuleEntry]) -> Optional[ModuleEntry]:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.rstrip("/")
    candidates: list[tuple[int, ModuleEntry]] = []
    for module in modules:
        if module.path == ".":
            candidates.append((0, module))
            continue
        prefix = module.path.rstrip("/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            candidates.append((prefix.count("/"), module))
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item[0], reverse=True)[0][1]


def parse_python_imports(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                imports.append("." * node.level + node.module)
            elif node.level:
                imports.append("." * node.level)
            elif node.module:
                imports.append(node.module)
    return imports


def parse_js_imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [
        item.specifier
        for item in scan_typescript_source(
            text,
            allow_jsx=path.suffix.lower() in JSX_SOURCE_SUFFIXES,
        ).imports
    ]


def parse_java_imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return java_imports(text)


def _existing_python_import_target(candidate: Path) -> Optional[Path]:
    if candidate.is_dir() and (candidate / "__init__.py").exists():
        return candidate / "__init__.py"
    if candidate.is_file():
        return candidate
    python_file = candidate.with_suffix(".py")
    if python_file.exists():
        return python_file
    return None


def _python_import_target(
    name: str,
    *,
    repo_root: Path,
    source_file: Path,
) -> Optional[Path]:
    if source_file.suffix.lower() != ".py":
        return None
    if name.startswith("."):
        level = len(name) - len(name.lstrip("."))
        remainder = name[level:]
        base = source_file.parent
        for _ in range(max(0, level - 1)):
            base = base.parent
        candidate = base.joinpath(*remainder.split(".")) if remainder else base
        return _existing_python_import_target(candidate)
    candidate = repo_root.joinpath(*name.split("."))
    return _existing_python_import_target(candidate)


def _import_match_score(name: str, module: ModuleEntry) -> Optional[tuple[int, int, int]]:
    lower = name.lower()
    matches: list[tuple[int, int, int]] = []
    for import_name in public_import_names(module):
        normalized = import_name.lower()
        if lower == normalized or lower.startswith(normalized + ".") or lower.startswith(normalized + "/"):
            matches.append((3, len(normalized), module.path.count("/")))
    for prefix in module.lifecycle.get("package_prefixes", []):
        normalized = str(prefix).lower()
        if lower == normalized or lower.startswith(normalized + "."):
            matches.append((2, len(normalized), module.path.count("/")))
    if module.path != ".":
        basename = Path(module.path).stem.lower()
        if lower == basename or lower.startswith(basename + "/") or f"/{basename}/" in lower:
            matches.append((1, len(basename), module.path.count("/")))
    return max(matches) if matches else None


def infer_import_reference(name: str, source_module: ModuleEntry, modules: list[ModuleEntry], repo_root: Path, source_file: Path) -> tuple[Optional[ModuleEntry], Optional[str]]:
    if not name:
        return None, None
    normalized = name.replace("\\", "/")
    python_target = _python_import_target(
        normalized,
        repo_root=repo_root,
        source_file=source_file,
    )
    if python_target is not None:
        rel = normalize_rel_path(repo_root, python_target)
        module = module_for_path(rel, modules)
        return module, rel if module else None
    if normalized.startswith("."):
        target = (source_file.parent / normalized).resolve()
        if target.is_dir():
            if (target / "__init__.py").exists():
                target = target / "__init__.py"
        else:
            for suffix in (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                if target.with_suffix(suffix).exists():
                    target = target.with_suffix(suffix)
                    break
        rel = normalize_rel_path(repo_root, target)
        module = module_for_path(rel, modules)
        return module, rel if module else None
    candidates: list[tuple[tuple[int, int, int], ModuleEntry]] = []
    for module in modules:
        score = _import_match_score(normalized, module)
        if score is not None:
            candidates.append((score, module))
    if not candidates:
        return None, None
    return max(candidates, key=lambda item: item[0])[1], None


def resolve_import_to_module(name: str, source_module: ModuleEntry, modules: list[ModuleEntry], repo_root: Path, source_file: Path) -> Optional[ModuleEntry]:
    target, _ = infer_import_reference(name, source_module, modules, repo_root, source_file)
    return target


def source_files_for_modules(repo_root: Path, modules: list[ModuleEntry], ignore_patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for module in modules:
        root = repo_root / module.path if module.path != "." else repo_root
        if not root.exists():
            continue
        for file in iter_source_files(root, ignore_patterns):
            if file.suffix.lower() not in CODE_SUFFIXES:
                continue
            rel = normalize_rel_path(repo_root, file)
            if rel not in seen:
                seen.add(rel)
                files.append(file)
    return files


def discover_modules(repo_root: Path, config: Optional[dict[str, Any]] = None, profile: Optional[dict[str, Any]] = None) -> list[ModuleEntry]:
    config = config or {}
    profile = profile or {}
    merged_config = deep_merge(config, profile.get("discovery", {}))
    ignore_patterns = default_ignore_patterns(merged_config)
    discovered: list[ModuleEntry] = []
    discovered.extend(maven_modules(repo_root, ignore_patterns))
    discovered.extend(node_modules(repo_root, ignore_patterns))
    discovered.extend(python_modules(repo_root, ignore_patterns))
    discovered.extend(generic_modules(repo_root, ignore_patterns))
    modules = dedupe_modules(discovered, repo_root)
    surfaces = discover_standard_repository_surfaces(
        repo_root,
        lambda path: should_ignore_path(path, ignore_patterns, repo_root),
    )
    records = overlay_standard_repository_surface_records(
        (module.to_dict() for module in modules),
        surfaces,
        infer_allowed_layers("infra"),
    )
    modules = [ModuleEntry(**record) for record in records]
    apply_profile_module_overrides(repo_root, modules, profile)
    prune_nested_module_key_files(repo_root, modules)
    infer_module_dependencies(repo_root, modules, merged_config)
    assign_module_ownership(repo_root, modules, profile, ignore_patterns)
    for module in modules:
        if (
            not module.allowed_outbound_to
            and not module.lifecycle.get("nested_module_boundary")
        ):
            module.allowed_outbound_to = sorted(set(module.depends_on))
        module.lifecycle.setdefault("allowed_outbound_layers", infer_allowed_layers(module.layer))
    return modules


def apply_profile_module_overrides(
    repo_root: Path,
    modules: list[ModuleEntry],
    profile: dict[str, Any],
) -> None:
    rules = profile.get("module_overrides", [])
    existing_paths = {module.path for module in modules}
    for rule in rules:
        declared_path = str(rule.get("path") or "").replace("\\", "/").strip("/")
        if not declared_path or declared_path in existing_paths:
            continue
        module_root = (repo_root / declared_path).resolve()
        try:
            module_root.relative_to(repo_root.resolve())
        except ValueError:
            continue
        planned_path = rule.get("status") == "planned"
        if not planned_path and (
            not module_root.exists()
            or not (module_root.is_dir() or module_root.is_file())
        ):
            continue
        public_api = rule.get("public_api")
        preferred_key_files: list[str] = []
        if public_api:
            normalized_public = str(public_api).replace("\\", "/")
            if normalized_public.startswith(declared_path.rstrip("/") + "/"):
                normalized_public = normalized_public[len(declared_path.rstrip("/")) + 1 :]
            if (module_root / normalized_public).is_file():
                preferred_key_files.append(normalized_public)
        layer = rule.get("layer", classify_layer(declared_path))
        modules.append(
            ModuleEntry(
                id=rule.get("id", f"module-{stable_slug(declared_path)}"),
                path=declared_path,
                layer=layer,
                domain=rule.get("domain", extract_domain_from_path(declared_path)),
                purpose=rule.get("purpose", f"Profile-declared module at {declared_path}"),
                public_api=public_api,
                source_of_truth="profile",
                key_files=(
                    list(rule["key_files"])
                    if "key_files" in rule
                    else (
                        [module_root.name]
                        if module_root.is_file()
                        else choose_key_files(module_root, preferred_key_files)
                    )
                ),
                allowed_inbound_from=list(rule.get("allowed_inbound_from", [])),
                allowed_outbound_to=list(rule.get("allowed_outbound_to", [])),
                generated=False,
                index_sources=["profile.module_overrides"],
                owner=rule.get("owner", "unassigned"),
                status=rule.get("status", "active"),
                lifecycle={
                    "language": "python" if contains_code(module_root, {".py"}) else "generic",
                    "source_roots": list(rule.get("source_roots", [declared_path])),
                    "import_names": list(rule.get("import_names", [])),
                    "allowed_outbound_layers": infer_allowed_layers(layer),
                    "planned_path": planned_path,
                    "nested_module_boundary": bool(
                        rule.get("nested_module_boundary", False)
                    ),
                    **(
                        {
                            "declared_allowed_outbound_to": list(
                                rule["allowed_outbound_to"]
                            )
                        }
                        if "allowed_outbound_to" in rule
                        else {}
                    ),
                    **dict(rule.get("lifecycle", {})),
                },
            )
        )
        existing_paths.add(declared_path)
    for module in modules:
        for rule in rules:
            declared_path = str(rule.get("path") or "").replace("\\", "/").strip("/")
            if declared_path and module.path != declared_path:
                continue
            patterns = rule.get("path_patterns", [])
            if patterns and not glob_match(patterns, module.path):
                continue
            if declared_path and module.path == declared_path:
                if "id" in rule:
                    module.id = str(rule["id"])
                module.source_of_truth = "profile"
                module.generated = False
                module.index_sources = ["profile.module_overrides"]
                module.lifecycle["definition_source"] = "profile.module_overrides"
            if "layer" in rule:
                module.layer = rule["layer"]
            if "domain" in rule:
                module.domain = rule["domain"]
            if "public_api" in rule:
                module.public_api = rule["public_api"]
            if "purpose" in rule:
                module.purpose = rule["purpose"]
            if "key_files" in rule:
                module.key_files = list(rule["key_files"])
            if "allowed_inbound_from" in rule:
                module.allowed_inbound_from = list(rule["allowed_inbound_from"])
            if "owner" in rule:
                module.owner = rule["owner"]
            if "status" in rule:
                module.status = rule["status"]
                module.lifecycle["planned_path"] = rule["status"] == "planned"
            if "nested_module_boundary" in rule:
                module.lifecycle["nested_module_boundary"] = bool(
                    rule["nested_module_boundary"]
                )
            if "lifecycle" in rule:
                module.lifecycle.update(dict(rule["lifecycle"]))
            if "allowed_outbound_to" in rule:
                declared = list(rule["allowed_outbound_to"])
                module.allowed_outbound_to = list(
                    dict.fromkeys(module.allowed_outbound_to + declared)
                )
                module.lifecycle["declared_allowed_outbound_to"] = declared
            for key in ("import_names", "package_prefixes", "source_roots"):
                if key in rule:
                    module.lifecycle[key] = list(dict.fromkeys(list(module.lifecycle.get(key, [])) + list(rule[key])))


def prune_nested_module_key_files(repo_root: Path, modules: list[ModuleEntry]) -> None:
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if module_root.is_file():
            module.key_files = [module_root.name]
            continue
        retained: list[str] = []
        for key_file in module.key_files:
            normalized = key_file.replace("\\", "/").strip("/")
            rel_path = (
                normalized
                if normalized == module.path
                or normalized.startswith(module.path.rstrip("/") + "/")
                else f"{module.path.rstrip('/')}/{normalized}"
            )
            owner = module_for_path(rel_path, modules)
            if owner is None or owner.path == module.path:
                retained.append(key_file)
        module.key_files = retained


def infer_module_dependencies(repo_root: Path, modules: list[ModuleEntry], config: dict[str, Any]) -> None:
    ignore_patterns = default_ignore_patterns(config)
    path_lookup = {module.path: module for module in modules}
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if not module_root.exists():
            continue
        deps = set(module.depends_on)
        for source_file in iter_source_files(module_root, ignore_patterns):
            source_owner = module_for_path(
                normalize_rel_path(repo_root, source_file), modules
            )
            if source_owner is not None and source_owner.path != module.path:
                continue
            kind = file_suffix_kind(source_file)
            if kind == "python":
                imports = parse_python_imports(source_file)
            elif kind in {"javascript", "typescript"}:
                imports = parse_js_imports(source_file)
            elif kind == "java":
                imports = parse_java_imports(source_file)
            else:
                imports = []
            for imp in imports:
                target = resolve_import_to_module(imp, module, modules, repo_root, source_file)
                if target and target.path != module.path and target.path in path_lookup:
                    deps.add(target.path)
        module.depends_on = sorted(deps)


def profile_ownership_for_path(rel_path: str, profile: dict[str, Any]) -> Optional[str]:
    for rule in profile.get("ownership_rules", []):
        patterns = rule.get("path_patterns", [])
        if patterns and glob_match(patterns, rel_path):
            owner = rule.get("owner")
            if owner:
                return str(owner)
    return None


def default_owner_name(module: ModuleEntry) -> str:
    if module.domain and module.domain not in {"root", "workspace"}:
        return f"provisional:{stable_slug(module.domain)}"
    return "unassigned"


def assign_module_ownership(
    repo_root: Path,
    modules: list[ModuleEntry],
    profile: dict[str, Any],
    ignore_patterns: Iterable[str] = (),
) -> None:
    rules = load_codeowners(repo_root)
    for module in modules:
        owner = (
            codeowner_for_module(
                repo_root,
                module,
                rules,
                lambda path: should_ignore_path(
                    path,
                    ignore_patterns,
                    repo_root,
                ),
            )
            if rules
            else None
        )
        if not owner:
            owner = profile_ownership_for_path(module.path, profile)
        if (
            not owner
            and module.source_of_truth == "profile"
            and module.owner not in {"", "unassigned"}
        ):
            owner = module.owner
        if not owner:
            owner = default_owner_name(module)
        module.owner = owner


def infer_public_entries_from_modules(modules: list[ModuleEntry]) -> list[str]:
    entries: list[str] = []
    for module in modules:
        module_entries: list[str] = []
        if module.public_api:
            public_api = str(module.public_api).replace("\\", "/").strip("/")
            suffix = Path(public_api).suffix.lower()
            looks_like_entry_file = suffix in CODE_SUFFIXES or suffix in {
                ".json",
                ".md",
                ".toml",
                ".xml",
                ".yaml",
                ".yml",
            }
            if looks_like_entry_file:
                if module.path == ".":
                    module_entries.append(public_api)
                elif public_api == module.path or public_api.startswith(module.path.rstrip("/") + "/"):
                    module_entries.append(public_api)
                else:
                    module_entries.append(f"{module.path.rstrip('/')}/{public_api}")
        if not module_entries:
            for key_file in module.key_files[:1]:
                normalized = str(key_file).replace("\\", "/").strip("/")
                if module.path == ".":
                    module_entries.append(normalized)
                elif normalized == module.path or normalized.startswith(module.path.rstrip("/") + "/"):
                    module_entries.append(normalized)
                else:
                    module_entries.append(f"{module.path.rstrip('/')}/{normalized}")
        entries.extend(module_entries)
    dedup: list[str] = []
    for entry in entries:
        normalized = entry.replace("\\", "/")
        if normalized not in dedup:
            dedup.append(normalized)
    return dedup[:8]


def capability_stage_for_generated(modules: list[ModuleEntry], public_entries: list[str], repo_stage: str) -> tuple[str, str]:
    if repo_stage == "seed":
        return "provisional", "provisional"
    if any(module.layer == "shared-capability" for module in modules) and len(modules) >= 2:
        return "stable", "stable"
    if repo_stage in {"structured", "governed"} and len(modules) >= 2 and public_entries and any(module.owner not in {"unassigned"} and not module.owner.startswith("provisional:") for module in modules):
        return "stable", "stable"
    if repo_stage == "emerging" and public_entries:
        return "candidate", "candidate"
    return "provisional", "provisional"


def public_entry_semantics(entries: list[str], repo_stage: str, profile_backed: bool) -> dict[str, Any]:
    heuristic_entries = [entry for entry in entries if entry.split("/")[-1].lower() in {"__init__.py", "index.ts", "index.js", "index.tsx", "index.jsx"}]
    if profile_backed:
        return {"kind": "declared_public_entry", "heuristic_entries": heuristic_entries}
    if repo_stage in {"seed", "emerging"}:
        return {"kind": "heuristic_public_entry", "heuristic_entries": heuristic_entries}
    return {"kind": "stable_public_entry", "heuristic_entries": heuristic_entries}


def infer_extension_points(repo_root: Path, modules: list[ModuleEntry], ignore_patterns: Iterable[str]) -> list[str]:
    extension_points: list[str] = []
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if not module_root.exists():
            continue
        for file in iter_source_files(module_root, ignore_patterns):
            rel = normalize_rel_path(repo_root, file)
            stem = file.stem.lower()
            if any(marker in stem for marker in EXTENSION_FILE_MARKERS):
                extension_points.append(rel)
    dedup: list[str] = []
    for item in extension_points:
        if item not in dedup:
            dedup.append(item)
    return dedup[:12]


def infer_related_tests(
    repo_root: Path,
    modules: list[ModuleEntry],
    ignore_patterns: Iterable[str] = (),
) -> list[str]:
    tests: list[str] = []
    candidates = []
    effective_ignores = list(
        dict.fromkeys(DEFAULT_IGNORE_GLOBS + list(ignore_patterns))
    )
    for base in ("tests", "test", "src/test", "src/tests"):
        root = repo_root / base
        if root.exists():
            candidates.extend(sorted(root.rglob("*")))
    module_tokens = set()
    for module in modules:
        module_tokens.update(text_tokens(module.domain))
        module_tokens.update(text_tokens(Path(module.path).name))
    for file in candidates:
        if (
            not file.is_file()
            or should_ignore_path(file, effective_ignores, repo_root)
            or file.suffix.lower() in {".pyc", ".pyo"}
        ):
            continue
        rel = normalize_rel_path(repo_root, file)
        if any(token and token in rel.lower() for token in module_tokens):
            tests.append(rel)
    return tests[:12]


def generic_capability_id(domain: str) -> str:
    return stable_slug(domain)


def virtual_modules_from_profile_capability(repo_root: Path, item: dict[str, Any], profile: dict[str, Any]) -> list[ModuleEntry]:
    if not item.get("allow_non_code_paths"):
        return []
    paths: list[str] = []
    for pattern in item.get("path_patterns", []):
        normalized = str(pattern).replace("\\", "/").strip()
        if not normalized:
            continue
        candidate = normalized.split("*", 1)[0].rstrip("/")
        if not candidate:
            continue
        if (repo_root / candidate).exists() and candidate not in paths:
            paths.append(candidate)
    modules: list[ModuleEntry] = []
    for path in paths:
        domain = item.get("domain") or stable_slug(Path(path).name or item["id"])
        owner = profile_ownership_for_path(path, profile) or item.get("owner") or "profile-declared"
        modules.append(
            ModuleEntry(
                id=f"module-{stable_slug(path)}",
                path=path,
                layer=item.get("layer", "governance"),
                domain=domain,
                purpose=item.get("purpose", f"Profile-declared non-code surface for {item['id']}"),
                public_api=(item.get("public_entries") or [None])[0],
                source_of_truth="profile",
                key_files=item.get("public_entries", []),
                generated=False,
                index_sources=["profile.capabilities.allow_non_code_paths"],
                owner=owner,
                lifecycle={
                    "virtual_module": True,
                    "profile_id": profile.get("profile_id"),
                    "path_patterns": item.get("path_patterns", []),
                },
            )
        )
    return modules


def apply_profile_capabilities(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any]) -> tuple[list[CapabilityEntry], set[str]]:
    ignore_patterns = default_ignore_patterns(profile.get("discovery", {}))
    capabilities: list[CapabilityEntry] = []
    consumed_modules: set[str] = set()
    for item in profile.get("capabilities", []):
        patterns = item.get("path_patterns", [])
        matched = [module for module in modules if patterns and glob_match(patterns, module.path)]
        if not matched:
            matched = virtual_modules_from_profile_capability(repo_root, item, profile)
        if not matched:
            continue
        consumed_modules.update(module.path for module in matched)
        profile_stage = item.get("stage", "governed-capability" if item.get("status", "stable") == "stable" else "stable")
        profile_status = item.get("status", "stable")
        item_lifecycle = dict(item.get("lifecycle", {}))
        item_lifecycle.setdefault("profile_id", profile.get("profile_id"))
        item_lifecycle.setdefault("definition_version", item.get("version", "1.0"))
        item_lifecycle.setdefault("status", profile_status)
        item_lifecycle.setdefault("stage", profile_stage)
        item_lifecycle.setdefault("changelog", item.get("changelog", []))
        if item.get("superseded_by"):
            item_lifecycle["superseded_by"] = item["superseded_by"]
        if item.get("deprecation_date"):
            item_lifecycle["deprecation_date"] = item["deprecation_date"]
        if item.get("migration_note"):
            item_lifecycle["migration_note"] = item["migration_note"]
        declared_public_entries = list(
            dict.fromkeys(item.get("public_entries", []))
        )
        inferred_public_entries = infer_public_entries_from_modules(matched)
        public_entries = (
            declared_public_entries
            if item_lifecycle.get("replace_snapshot_boundaries")
            else list(dict.fromkeys(declared_public_entries + inferred_public_entries))
        )
        item_lifecycle["public_entry_semantics"] = public_entry_semantics(
            public_entries,
            "governed",
            True,
        )
        capabilities.append(
            CapabilityEntry(
                id=item["id"],
                name=item.get("name", title_from_slug(item["id"])),
                status=profile_status,
                maturity=item.get("maturity", "curated"),
                stage=profile_stage,
                source_of_truth="profile",
                intent_keywords=list(dict.fromkeys(item.get("keywords", []) + item.get("intent_keywords", []))),
                aliases=item.get("aliases", []),
                business_intents=item.get("business_intents", []),
                scope={
                    "domains": sorted({module.domain for module in matched}),
                    "layers": sorted({module.layer for module in matched}),
                    "paths": [module.path for module in matched],
                },
                owner_modules=[module.path for module in matched],
                public_entries=public_entries,
                extension_points=list(dict.fromkeys(item.get("extension_points", []) + infer_extension_points(repo_root, matched, ignore_patterns))),
                route_defaults=item.get("route_defaults", {"preferred_action": "reuse"}),
                contracts=item.get("contracts", []),
                related_tests=list(dict.fromkeys(item.get("related_tests", []) + infer_related_tests(repo_root, matched, ignore_patterns))),
                test_bindings=item.get("test_bindings", []),
                forbidden_patterns=item.get("forbidden_patterns", []),
                dependent_modules=[],
                anti_patterns=item.get("anti_patterns", []),
                lifecycle=item_lifecycle,
                last_verified_at=today_date(),
            )
        )
    return capabilities, consumed_modules


def infer_capabilities_from_modules(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any], repo_stage: str, feedback_items: Optional[list[dict[str, Any]]] = None) -> list[CapabilityEntry]:
    feedback_items = feedback_items or []
    feedback_meta = feedback_summary(feedback_items)
    confirmation_counts = feedback_meta["capability_confirmation_counts"]
    profile_caps, consumed = apply_profile_capabilities(repo_root, modules, profile)
    used_capability_ids = {str(item.get("id")) for item in profile.get("capabilities", []) if item.get("id")}
    grouped: dict[str, list[ModuleEntry]] = defaultdict(list)
    for module in modules:
        if module.path in consumed:
            continue
        grouped[generic_capability_id(module.domain)].append(module)
    ignore_patterns = default_ignore_patterns(profile.get("discovery", {}))
    capabilities = list(profile_caps)
    reverse_deps: dict[str, list[str]] = defaultdict(list)
    for module in modules:
        for dep in module.depends_on:
            reverse_deps[dep].append(module.path)
    for cap_id, grouped_modules in sorted(grouped.items()):
        if not grouped_modules:
            continue
        generated_cap_id = disambiguate_generated_capability_id(cap_id, used_capability_ids)
        used_capability_ids.add(generated_cap_id)
        profile_collision = generated_cap_id != cap_id
        domain = grouped_modules[0].domain
        public_entries = infer_public_entries_from_modules(grouped_modules)
        extension_points = infer_extension_points(repo_root, grouped_modules, ignore_patterns)
        related_tests = infer_related_tests(repo_root, grouped_modules, ignore_patterns)
        dependent_modules: set[str] = set()
        for module in grouped_modules:
            dependent_modules.update(reverse_deps.get(module.path, []))
        flat_keywords: list[str] = [domain]
        for module in grouped_modules:
            flat_keywords.append(Path(module.path).name.replace("-", " "))
            flat_keywords.append(module.domain)
            flat_keywords.extend(public_import_names(module))
        keywords = sorted({keyword for keyword in flat_keywords if keyword})
        stage, maturity = ("provisional", "provisional") if profile_collision else capability_stage_for_generated(grouped_modules, public_entries, repo_stage)
        confirmation_count = int(confirmation_counts.get(generated_cap_id, 0))
        if stage == "provisional" and confirmation_count >= 1 and repo_stage in {"emerging", "structured", "governed"}:
            stage, maturity = "candidate", "candidate"
        if stage == "candidate" and confirmation_count >= 2 and repo_stage in {"structured", "governed"}:
            stage, maturity = "stable", "stable"
        status = "stable" if stage in {"stable", "governed-capability"} else "candidate"
        capabilities.append(
            CapabilityEntry(
                id=generated_cap_id,
                name=f"{title_from_slug(domain)} Capability",
                status=status,
                maturity=maturity,
                stage=stage,
                source_of_truth="generated",
                intent_keywords=list(dict.fromkeys(text_tokens(" ".join(flat_keywords))))[:20],
                aliases=sorted({Path(module.path).name for module in grouped_modules})[:8],
                business_intents=sorted({f"{domain}-change", f"{domain}-reuse", f"{domain}-extension"}),
                scope={
                    "domains": sorted({module.domain for module in grouped_modules}),
                    "layers": sorted({module.layer for module in grouped_modules}),
                    "paths": [module.path for module in grouped_modules],
                },
                owner_modules=[module.path for module in grouped_modules],
                public_entries=public_entries,
                extension_points=extension_points,
                route_defaults={"preferred_action": "reuse" if stage in {"stable", "governed-capability"} else "review"},
                contracts=[],
                related_tests=related_tests,
                test_bindings=[
                    {
                        "id": f"tests-{generated_cap_id}",
                        "label": f"Run tests related to {generated_cap_id}",
                        "when_actions": ["extend", "extract", "review"],
                        "when_changed_paths": [f"{module.path}/**" for module in grouped_modules if module.path != "."],
                        "related_tests": related_tests,
                    }
                ] if related_tests else [],
                forbidden_patterns=[],
                dependent_modules=sorted(dependent_modules),
                anti_patterns=["copying core logic outside owner modules"] if stage in {"stable", "governed-capability"} else [],
                lifecycle={
                    "generated_from": [module.path for module in grouped_modules],
                    "definition_version": "1.0",
                    "status": status,
                    "stage": stage,
                    "changelog": [
                        {
                            "date": today_date(),
                            "event": "generated_from_repository_structure",
                        }
                    ],
                    "public_entry_semantics": public_entry_semantics(public_entries, repo_stage, False),
                    "confirmation_count": confirmation_count,
                    "profile_capability_collision": cap_id if profile_collision else None,
                    "promotion_criteria": [
                        "profile-backed ownership rule",
                        "confirmed public entry",
                        "at least two successful route confirmations",
                        "curated evaluation case coverage",
                    ],
                },
                last_verified_at=today_date(),
            )
        )
    return capabilities


def capability_entries(bundle: dict[str, Any]) -> list[CapabilityEntry]:
    return [CapabilityEntry(**item) for item in bundle.get("capability_catalog", {}).get("capabilities", [])]


def module_entries(bundle: dict[str, Any]) -> list[ModuleEntry]:
    return [ModuleEntry(**item) for item in bundle.get("module_map", {}).get("modules", [])]


def build_module_map(repo_root: Path, config: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    modules = discover_modules(repo_root, config, profile)
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "modules": [module.to_dict() for module in modules],
    }


def build_capability_catalog(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any], repo_stage: str) -> dict[str, Any]:
    capabilities = infer_capabilities_from_modules(repo_root, modules, profile, repo_stage)
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "capabilities": [capability.to_dict() for capability in capabilities],
    }


def looks_like_file_path(path: str) -> bool:
    normalized = path.replace("\\", "/").strip("/")
    if not normalized or normalized == ".":
        return False
    repository_surface_kind = standard_repository_surface_kind(normalized)
    if repository_surface_kind:
        return repository_surface_kind == "file"
    name = normalized.rsplit("/", 1)[-1]
    if Path(name).suffix:
        return True
    if name.startswith(".") and len(name) > 1:
        return True
    return name in set(MANIFEST_FILES) | {"LICENSE", "NOTICE", "README", "Makefile", "Dockerfile"}


def module_path_pattern(module_path: str) -> str:
    normalized = module_path.replace("\\", "/").strip("/")
    if not normalized or normalized == ".":
        return "**"
    if looks_like_file_path(normalized):
        return normalized
    return f"{normalized}/**"


def root_owner_fallback_modules(capability: CapabilityEntry, modules: list[ModuleEntry]) -> list[str]:
    """Use same-domain modules when a broad root owner would otherwise claim the repo."""
    if not any(module.path != "." for module in modules):
        return []
    capability_id = stable_slug(capability.id)
    matches = [
        module.path
        for module in modules
        if module.path != "." and stable_slug(module.domain) == capability_id
    ]
    return sorted(dict.fromkeys(matches))


def build_path_to_capability_map(
    repo_root: Path,
    capabilities: list[CapabilityEntry],
    modules: list[ModuleEntry],
    profile: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    module_by_path = {module.path: module for module in modules}
    claims: dict[str, list[dict[str, Any]]] = defaultdict(list)
    capability_by_id = {capability.id: capability for capability in capabilities}

    for capability in capabilities:
        for owner in capability.owner_modules:
            if owner == ".":
                fallback_modules = root_owner_fallback_modules(capability, modules)
                if fallback_modules:
                    for fallback_module in fallback_modules:
                        claims[module_path_pattern(fallback_module)].append(
                            {
                                "capability": capability.id,
                                "source": "domain_fallback_from_root_owner",
                                "module": fallback_module,
                            }
                        )
                    continue
            claims[module_path_pattern(owner)].append(
                {
                    "capability": capability.id,
                    "source": "owner_modules",
                    "module": owner,
                }
            )
        for path in capability.scope.get("paths", []):
            pattern = module_path_pattern(str(path))
            if not any(item["capability"] == capability.id for item in claims.get(pattern, [])):
                claims[pattern].append(
                    {
                        "capability": capability.id,
                        "source": "scope.paths",
                        "module": str(path),
                    }
                )
        for raw_pattern in capability.lifecycle.get("consumer_path_patterns", []):
            normalized = str(raw_pattern).replace("\\", "/").strip("/")
            if not normalized:
                continue
            claims[normalized].append(
                {
                    "capability": None,
                    "consumer_capability": capability.id,
                    "source": "capability.consumer_path_patterns",
                    "module": None,
                }
            )

    for rule in (profile or {}).get("ownership_rules", []):
        owner = str(rule.get("owner") or "")
        for raw_pattern in rule.get("path_patterns", []):
            normalized = str(raw_pattern).replace("\\", "/").strip("/")
            if not normalized:
                continue
            pattern = normalized if any(marker in normalized for marker in "*?[") else module_path_pattern(normalized)
            module = normalized.split("*", 1)[0].rstrip("/") or normalized
            claims[pattern].append(
                {
                    "capability": owner if owner in capability_by_id else None,
                    "source": "profile.ownership_rules",
                    "module": module,
                }
            )

    for retired_path, capability_id in retired_profile_path_routes(profile or {}):
        if capability_id not in capability_by_id:
            continue
        claims[retired_path].append(
            {
                "capability": capability_id,
                "source": "profile_lifecycle.migrations",
                "module": None,
            }
        )

    covered_modules = {
        item["module"]
        for claim_items in claims.values()
        for item in claim_items
        if item.get("module") in module_by_path
    }
    uncovered_modules = sorted(module.path for module in modules if module.path not in covered_modules)
    for module_path in uncovered_modules:
        claims[module_path_pattern(module_path)].append(
            {
                "capability": None,
                "source": "uncovered_module",
                "module": module_path,
            }
        )

    dependency_impacts: dict[str, list[str]] = defaultdict(list)
    for capability in capabilities:
        for dependent in capability.dependent_modules:
            dependency_impacts[module_path_pattern(dependent)].append(capability.id)

    path_index: list[dict[str, Any]] = []
    lookup: dict[str, list[str]] = {}
    for pattern, claim_items in sorted(claims.items()):
        capability_ids = sorted({str(item["capability"]) for item in claim_items if item.get("capability")})
        consumer_capability_ids = sorted(
            {
                str(item["consumer_capability"])
                for item in claim_items
                if item.get("consumer_capability")
            }
        )
        sources = sorted({str(item["source"]) for item in claim_items})
        modules_for_pattern = sorted({str(item["module"]) for item in claim_items if item.get("module")})
        code_file_count = 0
        for module_path in modules_for_pattern:
            module = module_by_path.get(module_path)
            if not module:
                continue
            code_file_count += code_file_count_for_rel_path(repo_root, module.path)
        relationship = "unmapped"
        if len(capability_ids) == 1:
            relationship = "unique"
        elif len(capability_ids) > 1:
            relationship = "shared"
        entry = {
            "path_pattern": pattern,
            "capabilities": capability_ids,
            "consumer_capabilities": consumer_capability_ids,
            "relationship": relationship,
            "sources": sources,
            "modules": modules_for_pattern,
            "code_file_count": code_file_count,
            "dependent_capabilities": sorted(set(dependency_impacts.get(pattern, []))),
        }
        if len(capability_ids) == 1:
            capability = capability_by_id.get(capability_ids[0])
            if capability:
                entry["capability_stage"] = capability.stage
                entry["capability_source_of_truth"] = capability.source_of_truth
        path_index.append(entry)
        lookup[pattern] = capability_ids

    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "path_index": path_index,
        "lookup": lookup,
        "ambiguous_patterns": [entry for entry in path_index if entry["relationship"] == "shared"],
        "uncovered_modules": uncovered_modules,
    }


def infer_dependency_priority(capabilities: list[CapabilityEntry], profile: dict[str, Any]) -> dict[str, int]:
    configured = profile.get("dependency_priority") or profile.get("routing", {}).get("dependency_priority") or {}
    if configured:
        return {str(key): int(value) for key, value in configured.items()}
    layer_priority = {
        "infra": 0,
        "shared-capability": 1,
        "domain-service": 2,
        "feature-module": 3,
        "adapter": 4,
        "ui": 5,
    }
    module_to_capability = {
        module: capability.id
        for capability in capabilities
        for module in capability.owner_modules
    }
    dependency_targets = {
        module_to_capability[module]
        for capability in capabilities
        for module in capability.dependent_modules
        if module in module_to_capability
    }
    priorities: dict[str, int] = {}
    for capability in capabilities:
        layers = capability.scope.get("layers", [])
        base = min((layer_priority.get(str(layer), 3) for layer in layers), default=3)
        if capability.id in dependency_targets:
            base = min(base, 1)
        priorities[capability.id] = base
    return dict(sorted(priorities.items(), key=lambda item: (item[1], item[0])))


def high_risk_capability_ids(capabilities: list[CapabilityEntry], profile: dict[str, Any]) -> list[str]:
    ids = set(profile.get("risk", {}).get("capability_ids", []))
    for capability in capabilities:
        signals = capability.intent_keywords + capability.aliases + capability.business_intents + [capability.id, capability.name]
        if match_strength(" ".join(signals), DEFAULT_HIGH_RISK_KEYWORDS) >= 1.0:
            ids.add(capability.id)
    return sorted(ids)


def build_change_rules(capabilities: list[CapabilityEntry], profile: dict[str, Any], repo_stage: str) -> dict[str, Any]:
    risk_profile = profile.get("risk", {})
    if repo_stage == "seed":
        auto_threshold = 0.95
        guarded_threshold = 0.80
    elif repo_stage == "emerging":
        auto_threshold = 0.88
        guarded_threshold = 0.68
    else:
        auto_threshold = 0.78
        guarded_threshold = 0.58
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "confidence": {
            "auto_route_threshold": auto_threshold,
            "guarded_route_threshold": guarded_threshold,
        },
        "high_risk_conditions": list(
            dict.fromkeys(
                [
                    "auth-or-payment-change",
                    "public-contract-change",
                    "schema-migration",
                    "multi-capability-core-change",
                    *risk_profile.get("conditions", []),
                ]
            )
        ),
        "high_risk_capability_ids": high_risk_capability_ids(capabilities, profile),
        "high_risk_module_patterns": risk_profile.get("path_patterns", []),
        "sensitive_review_phrases": risk_profile.get("review_phrases", []),
        "dependency_priority": infer_dependency_priority(capabilities, profile),
        "new_capability_policy": {
            "minimum_positive_conditions": 2,
            "positive_conditions": [
                "new service or package boundary contains at least two source modules",
                "path patterns do not overlap any existing non-deprecated capability",
                "independent tests or evaluation cases can be attached to the new boundary",
                "the new boundary exposes a public entry that other capabilities can reuse",
            ],
            "non_qualifying_patterns": [
                "single CRUD shell without domain behavior",
                "facade-only route that delegates entirely to an existing capability",
                "temporary bootstrap or migration scaffold",
                "name similarity without path, owner, or public-entry evidence",
            ],
            "required_sections": [
                "id",
                "name",
                "path_patterns",
                "owner_modules",
                "public_entries",
                "contracts",
                "test_bindings",
                "lifecycle",
            ],
            "default_action_when_conditions_not_met": "review",
        },
        "contract_quality_policy": {
            "recommended_contract_types": [
                "scope",
                "boundary",
                "cross-capability",
                "risk",
            ],
            "min_contracts_for_profile_capability": 3,
            "min_contracts_for_large_capability": 4,
            "large_capability_file_threshold": 10,
            "recommended_contract_chars": {"min": 50, "max": 240},
        },
        "reuse_scan_budget": {
            **dataclasses.asdict(ReuseScanBudget()),
            **profile.get("reuse_scan_budget", {}),
            **profile.get("guardrails", {}).get("reuse_scan_budget", {}),
        },
        "reuse_scan_scope": {
            "include_dependency_neighbors": True,
            "repository_wide_mapping_policy": "ignore_when_specific_or_unresolved",
            "unresolved_changed_path_policy": "return_incomplete_without_full_scan",
            **profile.get("reuse_scan_scope", {}),
            **profile.get("guardrails", {}).get("reuse_scan_scope", {}),
        },
        "reuse_scan_runtime": {
            "soft_timeout_seconds": 60.0,
            "hard_timeout_seconds": 75.0,
            "checkpoint_interval_seconds": 5.0,
            "cache_mode": "auto",
            "diagnostics_mode": "auto",
            "persist_reports": True,
            "slow_scan_diagnostic_seconds": 10.0,
            **profile.get("reuse_scan_runtime", {}),
            **profile.get("guardrails", {}).get("reuse_scan_runtime", {}),
        },
        "reuse_scan_retention": {
            "canonical_max_age_days": 90,
            "canonical_max_count": 500,
            "checkpoint_max_age_days": 7,
            "diagnostic_max_age_days": 3,
            "diagnostic_max_count": 200,
            "max_cache_entries": 50_000,
            "max_runtime_bytes": 536_870_912,
            **profile.get("reuse_scan_retention", {}),
            **profile.get("guardrails", {}).get("reuse_scan_retention", {}),
        },
        "architecture_baseline": list(profile.get("guardrails", {}).get("architecture_baseline", [])),
        "central_growth_baseline": list(profile.get("guardrails", {}).get("central_growth_baseline", [])),
        "forbidden_implementation_roots": list(profile.get("guardrails", {}).get("forbidden_implementation_roots", [])),
        "exclusive_source_owners": list(profile.get("guardrails", {}).get("exclusive_source_owners", [])),
        "capability_lifecycle_policy": {
            "stages": ["provisional", "candidate", "stable", "governed-capability", "deprecated"],
            "promotion_rules": [
                "provisional -> candidate requires a profile-backed owner or one confirmed route",
                "candidate -> stable requires confirmed public entries and at least two successful route confirmations",
                "stable -> governed-capability requires curated evaluation coverage and active guardrails",
                "deprecated capabilities must set superseded_by, deprecation_date, and migration_note",
            ],
        },
        "capability_retirement_policy": {
            "delete_requires_review": True,
            "merge_requires_review": True,
            "deprecate_requires_metadata": ["superseded_by", "deprecation_date", "migration_note", "affected_callers", "regression_tests"],
            "must_check_before_removal": [
                "public_entries",
                "dependent_modules",
                "related_tests",
                "path_to_capability_map",
                "evaluation_cases",
            ],
        },
        "composite_route_policy": {
            "primary_selection_order": ["dependency_priority", "profile_backed", "path_proximity", "public_entry", "stage"],
            "facade_and_ui_changes_should_delegate_to_core": True,
            "multi_capability_core_changes_require_review": True,
            "allowed_roles": ["primary", "facade", "adapter", "ui", "test", "migration", "governance"],
        },
        "post_change_closeout_policy": {
            "required_steps": [
                "rebuild_index_if_boundary_changed",
                "validate_bundle",
                "structure_guardrails",
                "governance_audit",
                "route_evaluation",
                "record_feedback_after_review_or_override",
            ],
            "report_required_fields": [
                "capability_changed",
                "public_entry_changed",
                "owner_changed",
                "evaluation_case_added",
                "generated_files_gitignore_checked",
            ],
        },
        "regression_capture_policy": {
            "capture_on": ["review", "override", "false_positive", "false_negative", "manual_capability_correction"],
            "case_sources": ["route_report", "manual_feedback", "governance_finding"],
            "minimum_case_fields": ["id", "request", "expected_action", "expected_capabilities", "changed_paths", "risk_level"],
        },
        "route_rules": [
            {
                "name": "prefer-reuse-for-stable-capability",
                "when": {"capability_stage": "stable", "matching_intent": True, "path_proximity_gte": 0.6},
                "action": "reuse",
            },
            {
                "name": "prefer-extend-when-additive-change-is-clear",
                "when": {"capability_stage": "stable", "extension_point_or_public_api": True, "request_has_change_verb": True},
                "action": "extend",
            },
            {
                "name": "prefer-extract-when-duplicate-signal-is-strong",
                "when": {"duplicate_signal": True, "repeated_occurrence_gte": 2},
                "action": "extract",
            },
            {
                "name": "require-review-for-low-confidence-or-overlap",
                "when": {"confidence_below": 0.58, "candidate_capabilities_overlap_gte": 0.82},
                "action": "review",
            },
        ],
        "decision_policy": {
            "tie_breaker": "review",
            "high_risk_override": "review",
            "human_override_allowed": True,
            "human_override_must_record_reason": True,
            "repo_stage": repo_stage,
        },
    }


def build_router_config(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any], stage_info: dict[str, Any]) -> dict[str, Any]:
    manifest_kind = detect_repo_manifest_kind(repo_root)
    supported_languages = discover_languages(repo_root, modules)
    discovery_profile = profile.get("discovery", {})
    evaluation_profile = profile.get("evaluation", {})
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "repo_id": stable_slug(repo_root.name),
        "repositories": discover_repositories(repo_root, modules),
        "protected_branch_patterns": profile.get("protected_branch_patterns", ["main", "master", "release/*", "hotfix/*"]),
        "ignore_paths": list(dict.fromkeys(DEFAULT_IGNORE_GLOBS + discovery_profile.get("ignore_paths", []))),
        "supported_languages": supported_languages,
        "module_discovery": {
            "primary_manifest": manifest_kind,
            "strategies": ["maven", "node", "python", "generic"],
            "profile_id": profile.get("profile_id"),
        },
        "repo_stage": stage_info["repo_stage"],
        "repo_stage_score": stage_info["stage_score"],
        "repo_stage_reasons": stage_info["stage_reasons"],
        "repo_stage_signals": stage_info["signals"],
        "freshness_windows": {
            "capability_catalog_days": 30,
            "module_map_days": 30,
            "exception_registry_days": 30,
            "evaluation_set_days": 30,
        },
        "evaluation": {
            "enforcement_enabled": evaluation_profile.get("enforcement_enabled", True),
            "top1_accuracy_threshold": evaluation_profile.get("top1_accuracy_threshold", 0.85),
            "top1_capability_accuracy_threshold": evaluation_profile.get("top1_capability_accuracy_threshold", 0.85),
            "review_precision_threshold": evaluation_profile.get("review_precision_threshold", 0.90),
            "review_recall_threshold": evaluation_profile.get("review_recall_threshold", 1.0),
            "secondary_contract_accuracy_threshold": evaluation_profile.get("secondary_contract_accuracy_threshold", 1.0),
            "minimum_case_count": evaluation_profile.get("minimum_case_count", 30),
            "minimum_capability_coverage_ratio": evaluation_profile.get("minimum_capability_coverage_ratio", 0.80),
            "mode": stage_info["signals"].get("evaluation_mode", "generated_only"),
        },
        "route_reports_dir": "reports/route-decisions",
        "rebuild_reports_dir": "reports/index-rebuild",
        "guardrail_reports_dir": "reports/guardrail-results",
        "evaluation_reports_dir": "reports/evaluation",
    }


def build_exception_registry(repo_root: Path, profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "exceptions": profile.get("exceptions", []),
    }


def build_evaluation_set(capabilities: list[CapabilityEntry], module_map: dict[str, Any], repo_stage: str) -> dict[str, Any]:
    modules = [ModuleEntry(**item) for item in module_map.get("modules", [])]
    stable_caps = [cap for cap in capabilities if cap.stage in {"stable", "governed-capability"} or cap.status == "stable"] or capabilities[:]
    cases: list[dict[str, Any]] = []
    for capability in stable_caps:
        is_stable = capability.stage in {"stable", "governed-capability"} or capability.status == "stable"
        is_risky = match_strength(capability.id, DEFAULT_HIGH_RISK_KEYWORDS) >= 1.0
        cases.append(
            {
                "id": f"{capability.id}-reuse",
                "request": f"Reuse the existing {capability.name.lower()} entry point without changing its core behavior.",
                "expected_action": "reuse" if is_stable and repo_stage != "seed" else "review",
                "expected_capabilities": [capability.id],
                "expected_modules": capability.owner_modules[:2],
                "expected_reads": capability.public_entries[:2],
                "changed_paths": capability.owner_modules[:1],
                "risk_level": "medium",
            }
        )
        cases.append(
            {
                "id": f"{capability.id}-extend",
                "request": f"Extend the existing {capability.name.lower()} capability with a compatible new behavior.",
                "expected_action": "extend" if is_stable and not is_risky and repo_stage in {"structured", "governed"} else "review",
                "expected_capabilities": [capability.id],
                "expected_modules": capability.owner_modules[:2],
                "expected_reads": capability.public_entries[:2],
                "changed_paths": capability.owner_modules[:1],
                "risk_level": "high",
            }
        )
    for capability in stable_caps:
        is_stable = capability.stage in {"stable", "governed-capability"} or capability.status == "stable"
        is_risky = match_strength(capability.id, DEFAULT_HIGH_RISK_KEYWORDS) >= 1.0
        can_extract = is_stable and len(capability.owner_modules) >= 2
        if len(capability.owner_modules) >= 2:
            changed = capability.owner_modules[:2]
        else:
            changed = capability.owner_modules[:1]
        cases.append(
            {
                "id": f"{capability.id}-extract",
                "request": f"Extract repeated {capability.name.lower()} logic into a shared reusable entry point.",
                "expected_action": "extract" if can_extract and not is_risky and repo_stage in {"structured", "governed"} else "review",
                "expected_capabilities": [capability.id],
                "expected_modules": capability.owner_modules[:2],
                "expected_reads": capability.public_entries[:2],
                "changed_paths": changed,
                "risk_level": "high",
            }
        )
    if len(stable_caps) >= 2:
        first, second = stable_caps[0], stable_caps[1]
        cases.append(
            {
                "id": "review-multi-capability",
                "request": f"Modify {first.name.lower()} and {second.name.lower()} together in one change.",
                "expected_action": "review",
                "expected_capabilities": [first.id, second.id],
                "expected_modules": list(dict.fromkeys(first.owner_modules[:1] + second.owner_modules[:1])),
                "expected_reads": list(dict.fromkeys(first.public_entries[:1] + second.public_entries[:1])),
                "changed_paths": list(dict.fromkeys(first.owner_modules[:1] + second.owner_modules[:1])),
                "risk_level": "critical",
            }
        )
    cases.extend(
        [
            {
                "id": "new-capability",
                "request": "Introduce a brand-new workflow area that does not map to any existing capability.",
                "expected_action": "new",
                "expected_capabilities": [],
                "expected_modules": [],
                "expected_reads": [],
                "changed_paths": [],
                "risk_level": "medium",
            },
            {
                "id": "review-ambiguous",
                "request": "Review a broad cross-cutting behavior that touches multiple existing modules and is not clearly owned by one capability.",
                "expected_action": "review",
                "expected_capabilities": [],
                "expected_modules": [module.path for module in modules[:2]],
                "expected_reads": [],
                "changed_paths": [module.path for module in modules[:2]],
                "risk_level": "high",
            },
        ]
    )
    while len(cases) < 12 and stable_caps:
        capability = stable_caps[len(cases) % len(stable_caps)]
        cases.append(
            {
                "id": f"extra-{len(cases)+1}",
                "request": f"Reuse the existing {capability.name.lower()} capability from a nearby integration point.",
                "expected_action": "reuse" if (capability.stage in {"stable", "governed-capability"} or capability.status == "stable") and repo_stage != "seed" else "review",
                "expected_capabilities": [capability.id],
                "expected_modules": capability.owner_modules[:2],
                "expected_reads": capability.public_entries[:2],
                "changed_paths": capability.owner_modules[:1],
                "risk_level": "medium",
            }
        )
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "mode": "generated_only",
        "curated_case_ids": [],
        "cases": cases,
    }


def merge_curated_evaluation(existing: dict[str, Any], generated: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    profile_eval = profile.get("evaluation", {})
    profile_cases = list(profile_eval.get("cases", []))
    existing_cases = list(existing.get("cases", [])) if existing.get("mode") in {"curated", "hybrid"} else []
    raw_existing_ids = existing.get("curated_case_ids", [])
    existing_ids = {
        case_id for case_id in raw_existing_ids if isinstance(case_id, str)
    } if isinstance(raw_existing_ids, list) else set()
    curated_cases = profile_cases + [
        case for case in existing_cases if str(case.get("id")) in existing_ids
    ]
    if profile_eval.get("mode") == "curated" and profile_cases:
        mode = "curated"
    elif curated_cases:
        mode = "hybrid"
    elif existing_cases:
        mode = "hybrid"
    else:
        mode = generated.get("mode", "generated_only")
    merged = dict(generated)
    merged["mode"] = mode
    merged["curated_case_ids"] = list(dict.fromkeys(
        str(case.get("id")) for case in curated_cases if case.get("id")
    ))
    if curated_cases or existing_cases:
        seen: set[str] = set()
        ordered_cases = []
        case_sources = curated_cases if mode == "curated" else curated_cases + existing_cases + generated.get("cases", [])
        for case in case_sources:
            case_id = str(case.get("id"))
            if case_id in seen:
                continue
            seen.add(case_id)
            ordered_cases.append(case)
        merged["cases"] = ordered_cases
    return merged


def merge_curated_records(existing: dict[str, Any], generated: dict[str, Any], collection: str, identity: str) -> dict[str, Any]:
    profile_backed = {
        str(item.get(identity)): item
        for item in generated.get(collection, [])
        if item.get("source_of_truth") == "profile" and item.get(identity)
    }
    profile_modules_by_id = {
        str(item.get("id")): item
        for item in generated.get(collection, [])
        if collection == "modules"
        and item.get("source_of_truth") == "profile"
        and item.get("id")
    }
    preserved = []
    for item in existing.get(collection, []):
        replacement = profile_backed.get(str(item.get(identity)))
        if replacement is not None:
            replace_boundaries = bool(
                replacement.get("lifecycle", {}).get("replace_snapshot_boundaries")
            )
            current = (
                dict(replacement)
                if collection == "modules" and replace_boundaries
                else deep_merge(dict(item), replacement)
            )
            if collection == "modules":
                replacement_lifecycle = replacement.get("lifecycle", {})
                if "declared_allowed_outbound_to" not in replacement_lifecycle:
                    current_lifecycle = dict(current.get("lifecycle", {}))
                    current_lifecycle.pop("declared_allowed_outbound_to", None)
                    current["lifecycle"] = current_lifecycle
            if collection == "capabilities" and replace_boundaries:
                for field_name in (
                    "intent_keywords",
                    "aliases",
                    "business_intents",
                    "scope",
                    "owner_modules",
                    "public_entries",
                    "extension_points",
                    "route_defaults",
                    "contracts",
                    "related_tests",
                    "test_bindings",
                    "forbidden_patterns",
                    "dependent_modules",
                    "anti_patterns",
                ):
                    if field_name in replacement:
                        current[field_name] = replacement[field_name]
                replacement_lifecycle = replacement.get("lifecycle", {})
                current_lifecycle = dict(current.get("lifecycle", {}))
                current_lifecycle.update(replacement_lifecycle)
                current["lifecycle"] = current_lifecycle
            preserved.append(current)
            continue
        if collection == "modules":
            same_id = profile_modules_by_id.get(str(item.get("id")))
            if same_id is not None and same_id.get(identity) != item.get(identity):
                continue
        if item.get("source_of_truth") == "generated":
            continue
        preserved.append(dict(item))
    if collection == "capabilities":
        for item in preserved:
            lifecycle = dict(item.get("lifecycle", {}))
            lifecycle.setdefault("definition_version", "1.0")
            lifecycle.setdefault("status", item.get("status", "candidate"))
            lifecycle.setdefault("stage", item.get("stage", lifecycle["status"]))
            lifecycle.setdefault("changelog", [{"date": today_date(), "event": "curated_bundle_lifecycle_calibrated"}])
            item["lifecycle"] = lifecycle
    seen = {str(item.get(identity)) for item in preserved if item.get(identity)}
    curated_paths = set(seen)
    if collection == "modules":
        curated_paths.update(
            str(path)
            for item in preserved
            for field_name in ("key_files", "index_sources")
            for path in item.get(field_name, [])
            if path
        )
    curated_owner_modules = {
        str(owner)
        for item in preserved
        for owner in item.get("owner_modules", [])
        if owner
    }
    merged_items = list(preserved)
    for item in generated.get(collection, []):
        item_id = str(item.get(identity))
        if not item_id or item_id in seen:
            continue
        if collection == "modules" and item.get("source_of_truth") == "generated":
            prefix = item_id.rstrip("/") + "/"
            if any(path.startswith(prefix) for path in curated_paths):
                continue
        if collection == "capabilities" and item.get("source_of_truth") == "generated":
            generated_owners = {str(owner) for owner in item.get("owner_modules", []) if owner}
            if generated_owners and generated_owners <= curated_owner_modules:
                continue
        seen.add(item_id)
        merged_items.append(item)
    if collection == "capabilities":
        for item in merged_items:
            item["related_tests"] = [
                path
                for path in item.get("related_tests", [])
                if "__pycache__" not in Path(str(path).replace("\\", "/")).parts
                and Path(str(path)).suffix.lower() not in {".pyc", ".pyo"}
            ]
    merged = dict(generated)
    merged[collection] = merged_items
    return merged


def code_file_count_for_rel_path(repo_root: Path, rel_path: str) -> int:
    path = repo_root / rel_path
    if rel_path == ".":
        path = repo_root
    if path.is_file():
        return 1 if path.suffix.lower() in CODE_SUFFIXES else 0
    if path.is_dir():
        return len(directory_code_files(path, CODE_SUFFIXES))
    return 0


def capability_code_file_count(repo_root: Path, capability: CapabilityEntry) -> int:
    files: set[str] = set()
    for module_path in capability.owner_modules:
        path = repo_root / module_path
        if module_path == ".":
            path = repo_root
        if path.is_file() and path.suffix.lower() in CODE_SUFFIXES:
            files.add(path.resolve().as_posix())
        elif path.is_dir():
            files.update(
                candidate.resolve().as_posix()
                for candidate in directory_code_files(path, CODE_SUFFIXES)
            )
    return len(files)


def profile_capability_ids(profile: dict[str, Any]) -> set[str]:
    return {str(item.get("id")) for item in profile.get("capabilities", []) if item.get("id")}


def add_governance_finding(
    findings: list[dict[str, Any]],
    severity: str,
    rule: str,
    message: str,
    target: str,
    recommendation: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    findings.append(
        {
            "severity": severity,
            "rule": rule,
            "target": target,
            "message": message,
            "recommendation": recommendation,
            "details": details or {},
        }
    )


def ownership_rule_granularity(pattern: str) -> str:
    normalized = pattern.replace("\\", "/")
    if normalized in {"**", "**/*", "*"}:
        return "repository"
    if normalized.endswith("/**"):
        depth = len([part for part in normalized[:-3].split("/") if part])
        if depth <= 1:
            return "broad-directory"
        return "directory"
    if Path(normalized).suffix:
        return "file"
    return "path"


def audit_bundle_governance(repo_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    profile = load_active_profile(repo_root)
    capabilities = capability_entries(bundle)
    modules = module_entries(bundle)
    capability_ids = {capability.id for capability in capabilities}
    profile_ids = profile_capability_ids(profile)
    generated_ids = {capability.id for capability in capabilities if capability.source_of_truth == "generated"}
    profile_backed_ids = {capability.id for capability in capabilities if capability.source_of_truth == "profile"}
    findings = profile_source_lifecycle_findings(repo_root)
    for issue in validate_generated_output_rules(profile, repo_root=repo_root):
        add_governance_finding(
            findings,
            "P0",
            str(issue.get("diagnostic_code") or "generated-output-baseline-invalid"),
            str(issue.get("message") or "Generated output baseline is invalid."),
            str(issue.get("source") or "profile.guardrails.generated_output_baseline"),
            "Repair the exact pinned generated-output metadata before trusting structure results.",
            {
                key: value
                for key, value in issue.items()
                if key not in {"severity", "rule", "source", "blocking", "message"}
            },
        )

    capability_owner_targets = [
        str(item.get("target") or "")
        for item in profile.get("capability_ownership", [])
        if isinstance(item, dict)
    ]
    duplicate_owner_targets = sorted(
        target
        for target in set(capability_owner_targets)
        if target and capability_owner_targets.count(target) > 1
    )
    unknown_owner_targets = sorted(
        target
        for target in set(capability_owner_targets)
        if target and target not in capability_ids
    )
    missing_owner_target_count = capability_owner_targets.count("")
    if duplicate_owner_targets or unknown_owner_targets or missing_owner_target_count:
        add_governance_finding(
            findings,
            "P0",
            "capability-ownership-profile-invalid",
            "Capability ownership records must target one existing capability exactly once.",
            "profile.capability_ownership",
            "Remove duplicate or stale owner records and declare one exact target per capability owner.",
            {
                "duplicate_targets": duplicate_owner_targets,
                "unknown_targets": unknown_owner_targets,
                "missing_target_count": missing_owner_target_count,
            },
        )
    ownership_conflicts = [
        conflict
        for conflict in capability_conflicts(bundle)
        if conflict.startswith("capability ") and " conflicts with module " in conflict
    ]
    if ownership_conflicts:
        add_governance_finding(
            findings,
            "P0",
            "capability-ownership-conflict",
            "Capability and module ownership records disagree for the same canonical surface.",
            "references/ownership.yaml",
            "Resolve the owner conflict in the canonical profile and rebuild before routing writes.",
            {"conflicts": ownership_conflicts},
        )

    profile_missing_from_catalog = sorted(profile_ids - capability_ids)
    if profile_missing_from_catalog:
        add_governance_finding(
            findings,
            "P0",
            "profile-capability-not-in-catalog",
            "Profile declares capabilities that are absent from the generated capability catalog.",
            "profile.capabilities",
            "Fix path_patterns or module discovery so profile capabilities match real modules, then rebuild the bundle.",
            {"missing_capabilities": profile_missing_from_catalog},
        )

    referenced_capabilities = set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    referenced_capabilities.update(str(key) for key in bundle.get("change_rules", {}).get("dependency_priority", {}).keys())
    unknown_references = sorted(referenced_capabilities - capability_ids)
    if unknown_references:
        add_governance_finding(
            findings,
            "P0",
            "change-rule-references-unknown-capability",
            "Change rules reference capabilities that are not present in the capability catalog.",
            "references/change-rules.yaml",
            "Remove stale references or add the missing capabilities to the profile/catalog before trusting route rules.",
            {"unknown_capabilities": unknown_references},
        )

    if profile and generated_ids:
        severity = "P1" if bundle.get("config", {}).get("repo_stage") in {"structured", "governed"} else "P2"
        add_governance_finding(
            findings,
            severity,
            "catalog-has-unprofiled-capabilities",
            "The capability catalog contains generated capabilities that are not profile-backed.",
            "references/capability-catalog.yaml",
            "Review generated capabilities and promote stable boundaries into the repository profile.",
            {
                "generated_capability_count": len(generated_ids),
                "generated_capabilities": sorted(generated_ids)[:20],
            },
        )

    path_map = bundle.get("path_to_capability_map", {})
    path_map_references = {
        str(capability_id)
        for entry in path_map.get("path_index", [])
        for field in (
            "capabilities",
            "consumer_capabilities",
            "dependent_capabilities",
        )
        for capability_id in entry.get(field, [])
        if str(capability_id).strip()
    }
    unknown_path_map_references = sorted(path_map_references - capability_ids)
    if unknown_path_map_references:
        add_governance_finding(
            findings,
            "P0",
            "path-map-references-unknown-capability",
            "The path-to-capability map references capabilities absent from the catalog.",
            "references/path-to-capability-map.yaml",
            "Remove stale references or restore the curated capability, then rebuild and validate before routing writes.",
            {"unknown_capabilities": unknown_path_map_references},
        )
    if capabilities and not path_map.get("path_index"):
        add_governance_finding(
            findings,
            "P0",
            "path-to-capability-map-missing",
            "The bundle does not include a path-to-capability map.",
            "references/path-to-capability-map.yaml",
            "Rebuild the bundle with the current skill version so path ownership can be audited.",
        )
    uncovered_modules = list(path_map.get("uncovered_modules", []))
    if uncovered_modules:
        add_governance_finding(
            findings,
            "P0",
            "module-without-capability-path-index",
            "Some discovered modules are not covered by the path-to-capability map.",
            "references/path-to-capability-map.yaml",
            "Add profile capability or ownership rules for uncovered modules, then rebuild the bundle.",
            {"uncovered_modules": uncovered_modules[:50]},
        )

    ambiguous_patterns = list(path_map.get("ambiguous_patterns", []))
    if ambiguous_patterns:
        add_governance_finding(
            findings,
            "P1",
            "ambiguous-path-capability-ownership",
            "Some path patterns are claimed by multiple capabilities.",
            "references/path-to-capability-map.yaml",
            "Split broad capabilities or mark shared ownership explicitly in profile contracts.",
            {"ambiguous_pattern_count": len(ambiguous_patterns), "examples": ambiguous_patterns[:10]},
        )

    non_root_modules = [module.path for module in modules if module.path != "."]
    root_owner_capabilities = [
        {
            "capability": capability.id,
            "source_of_truth": capability.source_of_truth,
            "fallback_modules": root_owner_fallback_modules(capability, modules),
        }
        for capability in capabilities
        if "." in capability.owner_modules and non_root_modules
    ]
    if root_owner_capabilities:
        add_governance_finding(
            findings,
            "P1",
            "capability-root-owner-too-broad",
            "Some capabilities claim the repository root while narrower discovered modules exist.",
            "references/capability-catalog.yaml",
            "Replace owner_modules: [.] and public_entries: [.] with concrete capability roots or explicit profile path patterns.",
            {
                "capabilities": [item["capability"] for item in root_owner_capabilities[:20]],
                "examples": root_owner_capabilities[:10],
                "non_root_module_count": len(non_root_modules),
            },
        )

    repo_wide_capability_patterns = [
        entry
        for entry in path_map.get("path_index", [])
        if str(entry.get("path_pattern")) in {"**", "**/*", "*"} and entry.get("capabilities")
    ]
    if repo_wide_capability_patterns and non_root_modules:
        add_governance_finding(
            findings,
            "P1",
            "path-map-repository-wide-capability",
            "The path-to-capability map routes the entire repository to one or more concrete capabilities.",
            "references/path-to-capability-map.yaml",
            "Regenerate or repair the bundle so repo-wide patterns are used only for root-only repositories or explicit governance surfaces.",
            {
                "capabilities": sorted(
                    {
                        str(capability)
                        for entry in repo_wide_capability_patterns
                        for capability in entry.get("capabilities", [])
                    }
                ),
                "examples": repo_wide_capability_patterns[:10],
            },
        )

    owner_rules = profile.get("ownership_rules", [])
    capability_by_id = {capability.id: capability for capability in capabilities}
    module_by_path = {module.path: module for module in modules}
    profile_capability_patterns = {
        str(item.get("id")): {
            str(pattern).replace("\\", "/").strip()
            for pattern in item.get("path_patterns", [])
        }
        for item in profile.get("capabilities", [])
        if item.get("id")
    }
    broad_rules = []
    file_rules = []
    for rule in owner_rules:
        for pattern in rule.get("path_patterns", []):
            granularity = ownership_rule_granularity(str(pattern))
            if granularity in {"repository", "broad-directory"}:
                root = str(pattern).replace("\\", "/").removesuffix("/**").rstrip("/")
                module = module_by_path.get(root)
                stable_capabilities = [
                    capability
                    for capability in capability_by_id.values()
                    if root in capability.owner_modules
                    and capability.status == "stable"
                    and capability.source_of_truth == "profile"
                    and str(pattern).replace("\\", "/").strip()
                    in profile_capability_patterns.get(capability.id, set())
                ]
                owner = str(rule.get("owner") or "")
                declared_stable_root = bool(
                    granularity == "broad-directory"
                    and len(stable_capabilities) == 1
                    and module
                    and owner == str(module.owner)
                    and owner.lower() not in {"", "unknown", "unassigned", "none"}
                    and not owner.lower().startswith("provisional:")
                    and module.layer in {"governance", "infra"}
                )
                if not declared_stable_root:
                    broad_rules.append(pattern)
            elif granularity == "file":
                file_rules.append(pattern)
    if broad_rules:
        add_governance_finding(
            findings,
            "P1",
            "ownership-rule-too-broad",
            "Ownership rules include broad repository or top-level directory patterns.",
            "profile.ownership_rules",
            "Prefer domain-level directory globs so routing can distinguish affected capabilities.",
            {"patterns": broad_rules[:20]},
        )
    if file_rules and len(file_rules) > max(3, len(owner_rules)):
        add_governance_finding(
            findings,
            "P2",
            "ownership-rule-too-file-grained",
            "Ownership rules rely heavily on file-level patterns and may miss sibling files.",
            "profile.ownership_rules",
            "Use stable directory-level globs for modules with multiple source files.",
            {"file_patterns": file_rules[:20]},
        )

    contract_policy = bundle.get("change_rules", {}).get("contract_quality_policy", {})
    min_profile_contracts = int(contract_policy.get("min_contracts_for_profile_capability", 3))
    min_large_contracts = int(contract_policy.get("min_contracts_for_large_capability", 4))
    large_threshold = int(contract_policy.get("large_capability_file_threshold", 10))
    char_policy = contract_policy.get("recommended_contract_chars", {})
    min_chars = int(char_policy.get("min", 50))
    max_chars = int(char_policy.get("max", 240))
    for capability in capabilities:
        file_count = capability_code_file_count(repo_root, capability)
        contract_count = len(capability.contracts)
        if capability.source_of_truth == "profile" and contract_count < min_profile_contracts:
            add_governance_finding(
                findings,
                "P1",
                "profile-capability-contracts-too-thin",
                "A profile-backed capability does not have enough explicit contracts.",
                capability.id,
                "Add scope, boundary, cross-capability, and risk contracts to the capability profile.",
                {"contract_count": contract_count, "minimum": min_profile_contracts},
            )
        if file_count >= large_threshold and contract_count < min_large_contracts:
            add_governance_finding(
                findings,
                "P1",
                "large-capability-contracts-too-thin",
                "A large capability has too few contracts for its code surface.",
                capability.id,
                "Add concrete boundary and risk contracts before trusting automatic extend/extract decisions.",
                {"code_file_count": file_count, "contract_count": contract_count, "minimum": min_large_contracts},
            )
        if capability.contracts:
            lengths = [
                len(contract_description(contract))
                for contract in capability.contracts
            ]
            avg_len = sum(lengths) / len(lengths)
            if avg_len < min_chars:
                add_governance_finding(
                    findings,
                    "P2",
                    "contracts-too-short",
                    "Capability contracts are unusually short and may read like labels rather than constraints.",
                    capability.id,
                    "Rewrite contracts as concrete scope, boundary, interaction, or risk statements.",
                    {"average_contract_chars": round(avg_len, 1), "recommended_min": min_chars},
                )
            if avg_len > max_chars:
                add_governance_finding(
                    findings,
                    "P2",
                    "contracts-too-long",
                    "Capability contracts are unusually long and may mix explanation with enforceable constraints.",
                    capability.id,
                    "Split long prose into shorter enforceable contract statements.",
                    {"average_contract_chars": round(avg_len, 1), "recommended_max": max_chars},
                )

        forbidden_count = len(capability.forbidden_patterns)
        if file_count >= large_threshold and forbidden_count < 3:
            add_governance_finding(
                findings,
                "P1",
                "large-capability-forbidden-density-too-low",
                "A large capability has very few forbidden patterns or anti-patterns.",
                capability.id,
                "Add forbidden patterns for duplicate implementations, bypassed public APIs, and misplaced local caches.",
                {"code_file_count": file_count, "forbidden_count": forbidden_count},
            )
        if file_count <= 3 and forbidden_count >= 12:
            add_governance_finding(
                findings,
                "P2",
                "small-capability-forbidden-density-too-high",
                "A small capability has unusually many forbidden patterns.",
                capability.id,
                "Review whether broad restrictions belong in shared policies instead of a narrow capability.",
                {"code_file_count": file_count, "forbidden_count": forbidden_count},
            )

        lifecycle = capability.lifecycle or {}
        if not lifecycle.get("definition_version"):
            add_governance_finding(
                findings,
                "P2",
                "capability-lifecycle-version-missing",
                "A capability lacks lifecycle definition_version metadata.",
                capability.id,
                "Add lifecycle.definition_version and changelog when curating the profile entry.",
            )
        if capability.status == "deprecated" or lifecycle.get("status") == "deprecated":
            missing = [field for field in ("superseded_by", "deprecation_date", "migration_note") if not lifecycle.get(field)]
            if missing:
                add_governance_finding(
                    findings,
                    "P1",
                    "deprecated-capability-migration-metadata-missing",
                    "A deprecated capability is missing migration metadata.",
                    capability.id,
                    "Set superseded_by, deprecation_date, and migration_note for deprecated capabilities.",
                    {"missing_fields": missing},
                )

    dependency_priority = bundle.get("change_rules", {}).get("dependency_priority", {})
    missing_dependency_priority = sorted(capability_ids - set(dependency_priority.keys()))
    if missing_dependency_priority:
        add_governance_finding(
            findings,
            "P1",
            "dependency-priority-incomplete",
            "Not every capability has an explicit dependency priority.",
            "references/change-rules.yaml",
            "Add dependency_priority entries so multi-capability changes can identify the primary route.",
            {"missing_capabilities": missing_dependency_priority[:50]},
        )

    eval_cases = bundle.get("evaluation_set", {}).get("cases", [])
    findings.extend(build_stable_capability_governance_findings(bundle))
    if bundle.get("evaluation_set", {}).get("mode") == "generated_only" and bundle.get("config", {}).get("repo_stage") in {"structured", "governed"}:
        add_governance_finding(
            findings,
            "P1",
            "generated-only-evaluation-on-mature-repo",
            "A mature repository is still using generated-only evaluation cases.",
            "references/evaluation-set.yaml",
            "Promote real route regressions and manual feedback into curated evaluation cases.",
        )

    severity_counts = {
        severity: sum(1 for finding in findings if finding["severity"] == severity)
        for severity in ("P0", "P1", "P2")
    }
    repair_suggestions = build_governance_repair_suggestions(findings)
    status = "fail" if severity_counts["P0"] else "warn" if findings else "pass"
    return {
        "report_id": f"governance-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "status": status,
        "severity_counts": severity_counts,
        "summary": {
            "module_count": len(modules),
            "capability_count": len(capabilities),
            "profile_capability_count": len(profile_ids),
            "profile_backed_capability_count": len(profile_backed_ids),
            "generated_capability_count": len(generated_ids),
            "evaluation_case_count": len(eval_cases),
            "path_index_count": len(path_map.get("path_index", [])),
            "repair_suggestion_count": len(repair_suggestions),
        },
        "findings": findings,
        "repair_suggestions": repair_suggestions,
    }


def build_router_bundle(
    repo_root: Path,
    *,
    input_mode: str = "preserve_curated",
) -> dict[str, Any]:
    if input_mode not in {"preserve_curated", "canonical_only"}:
        raise ValueError(f"unsupported router bundle input mode: {input_mode}")
    profile = load_active_profile(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    feedback_items = load_manual_feedback(bundle_root)
    existing_bundle = (
        load_bundle(bundle_root)
        if input_mode == "preserve_curated" and bundle_root.exists()
        else {}
    )
    preliminary_modules = discover_modules(repo_root, {}, profile)
    initial_stage, initial_stage_info = classify_repo_stage(preliminary_modules, [], profile, repo_root, feedback_items)
    config = build_router_config(repo_root, preliminary_modules, profile, initial_stage_info)
    module_map = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "modules": [module.to_dict() for module in preliminary_modules],
    }
    module_map = merge_curated_records(existing_bundle.get("module_map", {}), module_map, "modules", "path")
    modules = [ModuleEntry(**item) for item in module_map["modules"]]
    capability_catalog = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "capabilities": [
            capability.to_dict()
            for capability in infer_capabilities_from_modules(repo_root, modules, profile, initial_stage, feedback_items)
        ],
    }
    capability_catalog = merge_curated_records(
        existing_bundle.get("capability_catalog", {}), capability_catalog, "capabilities", "id"
    )
    capabilities = [CapabilityEntry(**item) for item in capability_catalog["capabilities"]]
    repo_stage, stage_info = classify_repo_stage(modules, capabilities, profile, repo_root, feedback_items)
    config = build_router_config(repo_root, modules, profile, stage_info)
    config["generated_only"] = stage_info["signals"].get("evaluation_mode") == "generated_only"
    config["needs_calibration"] = repo_stage in {"seed", "emerging"} or stage_info["signals"].get("provisional_owner_ratio", 0.0) >= 0.5
    warnings: list[str] = []
    if config["generated_only"]:
        warnings.append("evaluation set is generated-only")
    if repo_stage in {"seed", "emerging"}:
        warnings.append("repository is in an early stage; prefer review over strong auto-routing")
    if stage_info["signals"].get("provisional_owner_ratio", 0.0) >= 0.5:
        warnings.append("ownership is still provisional")
    if stage_info["signals"].get("heuristic_public_entry_ratio", 0.0) >= 0.5:
        warnings.append("public entries are still heuristic")
    if stage_info["signals"].get("manual_feedback_count", 0) == 0:
        warnings.append("no manual feedback confirmations have been recorded yet")
    config["warnings"] = warnings
    ownership = build_ownership(capabilities, modules, repo_stage, profile)
    generated_change_rules = build_change_rules(capabilities, profile, repo_stage)
    existing_change_rules = existing_bundle.get("change_rules", {})
    change_rules = dict(existing_change_rules) if existing_change_rules else dict(generated_change_rules)
    for rule_key, rule_value in generated_change_rules.items():
        change_rules.setdefault(rule_key, rule_value)
    change_rules = refresh_profile_structure_guardrails(change_rules, generated_change_rules)
    change_rules["architecture_baseline"] = generated_change_rules["architecture_baseline"]
    for metadata_key in ("schema_version", "generated_at", "generated_by", "source_repository", "source_commit"):
        change_rules[metadata_key] = generated_change_rules[metadata_key]
    path_to_capability_map = build_path_to_capability_map(repo_root, capabilities, modules, profile)
    exception_registry = existing_bundle.get("exception_registry") or build_exception_registry(repo_root, profile)
    generated_evaluation = build_evaluation_set(capabilities, module_map, repo_stage)
    evaluation_set = merge_curated_evaluation(existing_bundle.get("evaluation_set", {}), generated_evaluation, profile)
    bundle = {
        "config": config,
        "module_map": module_map,
        "capability_catalog": capability_catalog,
        "ownership": ownership,
        "change_rules": change_rules,
        "path_to_capability_map": path_to_capability_map,
        "exception_registry": exception_registry,
        "evaluation_set": evaluation_set,
    }
    bundle["root"] = resolve_bundle_root(repo_root)
    return bundle


def route_bundle_from_repo(repo_root: Path) -> dict[str, Any]:
    bundle_root = resolve_bundle_root(repo_root)
    if bundle_root.exists():
        existing = load_bundle(bundle_root)
        if existing:
            existing["root"] = bundle_root
            return existing
    bundle = build_router_bundle(repo_root)
    bundle["root"] = bundle_root
    return bundle


def request_high_risk(request_text: str, changed_paths: Iterable[str], modules: list[ModuleEntry], bundle: dict[str, Any]) -> bool:
    rules = bundle.get("change_rules", {})
    keywords = list(dict.fromkeys(DEFAULT_HIGH_RISK_KEYWORDS + bundle.get("config", {}).get("high_risk_keywords", [])))
    if _request_has_high_risk_keyword(request_text, keywords):
        return True
    path_patterns = rules.get("high_risk_module_patterns", [])
    for path in changed_paths:
        normalized = path.replace("\\", "/").lower()
        if any(keyword in normalized for keyword in keywords):
            return True
        if path_patterns and glob_match(path_patterns, normalized):
            return True
        module = module_for_path(normalized, modules)
        if module and any(keyword in module.path.lower() for keyword in keywords):
            return True
    return False


def indexed_path_proximity(
    capability_id: str,
    changed_paths: list[str],
    bundle: dict[str, Any],
) -> float:
    if not capability_id or not changed_paths:
        return 0.0
    evidence_paths = _owner_evidence_paths(changed_paths)
    hits = sum(
        capability_id in path_index_evidence_capabilities_for_path(bundle, path)
        for path in evidence_paths
    )
    return hits / max(1, len(evidence_paths))


def capability_path_proximity(
    capability: CapabilityEntry,
    changed_paths: list[str],
    bundle: dict[str, Any],
) -> float:
    discovered = module_path_proximity(capability, changed_paths)
    canonical_root = capability.lifecycle.get("canonical_root", {})
    # A governed root still owns indexed compatibility and test paths outside its module root.
    if canonical_root.get("status") not in {"planned", "active", "verified"}:
        return discovered
    return max(
        discovered,
        indexed_path_proximity(capability.id, changed_paths, bundle),
    )


def capability_match_score(request_text: str, capability: CapabilityEntry) -> float:
    signals = capability.intent_keywords + capability.aliases + capability.business_intents + [capability.id, capability.name]
    score = match_strength(request_text, signals)
    request_words = set(text_tokens(request_text))
    capability_words = set(text_tokens(" ".join(signals)))
    generic_words = {
        "capability",
        "existing",
        "workflow",
        "logic",
        "change",
        "behavior",
        "entry",
        "point",
        "new",
        "brand",
        "area",
        "compatible",
        "current",
    }
    if score == 0.5 and not (request_words & (capability_words - generic_words)):
        return 0.0
    return score


def capability_positive_negative_risk_signals(
    request_text: str,
    capability: CapabilityEntry,
    changed_modules: list[ModuleEntry],
    changed_paths: list[str],
    bundle: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    positive: dict[str, Any] = {}
    negative: dict[str, Any] = {}
    risk: dict[str, Any] = {}

    positive["profile_backed"] = capability.source_of_truth == "profile"
    positive["path_proximity"] = round(
        capability_path_proximity(capability, changed_paths, bundle),
        4,
    )
    positive["dependency_proximity"] = round(dependency_proximity(capability, changed_modules), 4)
    positive["has_public_entries"] = bool(capability.public_entries)
    positive["has_extension_points"] = bool(capability.extension_points)
    positive["owner_modules_count"] = len(capability.owner_modules)
    positive["matching_intent"] = capability_match_score(request_text, capability) >= 0.5
    positive["repo_stage"] = bundle.get("config", {}).get("repo_stage")

    public_semantics = capability.lifecycle.get("public_entry_semantics", {})
    negative["capability_stage"] = capability.stage
    negative["provisional_stage"] = capability.stage == "provisional"
    negative["heuristic_public_entry"] = public_semantics.get("kind") == "heuristic_public_entry"
    negative["owner_unclear"] = not capability.owner_modules
    negative["generated_only"] = capability.source_of_truth == "generated"
    negative["profile_missing"] = capability.source_of_truth != "profile"
    negative["multi_module_span"] = len({module.path for module in changed_modules}) > 1

    risk_keywords = list(dict.fromkeys(DEFAULT_HIGH_RISK_KEYWORDS + bundle.get("config", {}).get("high_risk_keywords", [])))
    risk["keyword_hit"] = _request_has_high_risk_keyword(request_text, risk_keywords)
    risk["high_risk_capability"] = capability.id in set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    risk["repo_stage"] = bundle.get("config", {}).get("repo_stage")
    risk["request_requires_review"] = request_requires_review(request_text)
    risk["request_requires_sensitive_review"] = request_requires_sensitive_review(
        request_text,
        bundle.get("change_rules", {}).get("sensitive_review_phrases", []),
    )
    risk["duplicate_signal"] = request_prefers_extract(request_text)
    return positive, negative, risk


def dependency_proximity(capability: CapabilityEntry, changed_modules: list[ModuleEntry]) -> float:
    if not changed_modules or not capability.owner_modules:
        return 0.0
    owners = set(capability.owner_modules)
    hits = 0
    for module in changed_modules:
        if owners.intersection(module.depends_on):
            hits += 1
    return hits / max(1, len(changed_modules))


def capability_score(request_text: str, capability: CapabilityEntry, changed_modules: list[ModuleEntry], changed_paths: list[str], bundle: dict[str, Any]) -> tuple[float, dict[str, float]]:
    intent_match = capability_match_score(request_text, capability)
    path_proximity = capability_path_proximity(capability, changed_paths, bundle)
    dep_proximity = dependency_proximity(capability, changed_modules)
    public_entry_available = 1.0 if capability.public_entries else 0.0
    extension_available = 1.0 if capability.extension_points else 0.0
    owner_coverage = 1.0 if capability.owner_modules else 0.0
    positive, negative, risk = capability_positive_negative_risk_signals(
        request_text, capability, changed_modules, changed_paths, bundle
    )
    raw = (
        0.40 * intent_match
        + 0.30 * path_proximity
        + 0.10 * dep_proximity
        + 0.10 * public_entry_available
        + 0.05 * extension_available
        + 0.05 * owner_coverage
    )
    penalty = 0.0
    high_risk_ids = set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    if capability.id in high_risk_ids and intent_match < 1.0 and path_proximity == 0.0:
        penalty += 0.15
    if capability.stage == "provisional":
        penalty += 0.20
    elif capability.stage == "candidate" or capability.status == "candidate":
        penalty += 0.10
    if negative["heuristic_public_entry"]:
        penalty += 0.05
    if negative["profile_missing"] and bundle.get("config", {}).get("repo_stage") in {"seed", "emerging"}:
        penalty += 0.05
    score = max(0.0, min(1.0, raw - penalty))
    signals = {
        "intent_match": round(intent_match, 4),
        "path_proximity": round(path_proximity, 4),
        "dependency_proximity": round(dep_proximity, 4),
        "public_entry_available": public_entry_available,
        "extension_point_available": extension_available,
        "owner_coverage": owner_coverage,
        "raw_score": round(raw, 4),
        "penalty": round(penalty, 4),
        "candidate_score": round(score, 4),
        "positive_signals": positive,
        "negative_signals": negative,
        "risk_signals": risk,
    }
    return score, signals


def overlap_score(best: float, second: float) -> float:
    if best <= 0.0:
        return 0.0
    return min(1.0, second / best)


def sort_route_scores(
    route_scores: list[tuple[CapabilityEntry, float, dict[str, Any]]],
    bundle: dict[str, Any],
    close_delta: float = 0.05,
) -> list[tuple[CapabilityEntry, float, dict[str, Any]]]:
    if len(route_scores) <= 1:
        return sorted(route_scores, key=lambda item: item[1], reverse=True)
    priority = bundle.get("change_rules", {}).get("dependency_priority", {})
    sorted_by_score = sorted(route_scores, key=lambda item: item[1], reverse=True)
    best_score = sorted_by_score[0][1]
    close = [item for item in sorted_by_score if best_score - item[1] <= close_delta]
    rest = [item for item in sorted_by_score if best_score - item[1] > close_delta]
    close_sorted = sorted(close, key=lambda item: (int(priority.get(item[0].id, 999)), -item[1], item[0].id))
    score_leader = sorted_by_score[0]
    priority_leader = close_sorted[0]
    if (
        score_leader[0].id != priority_leader[0].id
        and score_leader[2].get("path_proximity", 0.0) > 0.0
        and priority_leader[2].get("path_proximity", 0.0) == 0.0
    ):
        close_sorted.remove(score_leader)
        close_sorted.insert(0, score_leader)
    return close_sorted + rest


def source_of_truth_for(bundle: dict[str, Any], kind: str) -> dict[str, Any]:
    mapping = {
        "capability": bundle.get("capability_catalog", {}),
        "module": bundle.get("module_map", {}),
        "exception": bundle.get("exception_registry", {}),
    }
    payload = mapping.get(kind, {})
    return {
        "generated_by": payload.get("generated_by"),
        "generated_at": payload.get("generated_at"),
        "source_commit": payload.get("source_commit"),
    }


def required_read_paths(capability: Optional[CapabilityEntry], modules: list[ModuleEntry], changed_paths: list[str]) -> list[str]:
    return build_required_read_paths(
        capability,
        modules,
        changed_paths,
        module_for_path=module_for_path,
    )


def forbidden_paths_for(capability: Optional[CapabilityEntry], bundle: dict[str, Any]) -> list[str]:
    if not capability:
        return []
    return list(dict.fromkeys(capability.forbidden_patterns))


def _capability_dependency_closure(
    bundle: dict[str, Any],
    seed_capabilities: set[str],
) -> set[str]:
    if not seed_capabilities:
        return set()
    modules = module_entries(bundle)
    capabilities = capability_entries(bundle)
    capabilities_by_module: dict[str, set[str]] = {}
    for capability in capabilities:
        for owner_module in capability.owner_modules:
            capabilities_by_module.setdefault(owner_module, set()).add(capability.id)

    graph: dict[str, set[str]] = {
        capability.id: set() for capability in capabilities
    }
    for module in modules:
        source_capabilities = capabilities_by_module.get(module.path, set())
        for dependency in module.depends_on:
            target_module = module_for_path(dependency, modules)
            if target_module is None:
                continue
            target_capabilities = capabilities_by_module.get(target_module.path, set())
            for source_capability in source_capabilities:
                graph.setdefault(source_capability, set()).update(target_capabilities)
            for target_capability in target_capabilities:
                graph.setdefault(target_capability, set()).update(source_capabilities)
    for entry in bundle.get("path_to_capability_map", {}).get("path_index", []):
        owners = {
            str(value) for value in entry.get("capabilities", []) if value
        }
        consumers = {
            str(value) for value in entry.get("consumer_capabilities", []) if value
        }
        for capability in owners | consumers:
            graph.setdefault(capability, set()).update((owners | consumers) - {capability})

    closure = set(seed_capabilities)
    pending = list(seed_capabilities)
    while pending:
        current = pending.pop()
        for neighbor in graph.get(current, set()):
            if neighbor not in closure:
                closure.add(neighbor)
                pending.append(neighbor)
    return closure


def _freshness_check_details(
    report: dict[str, Any],
    check_name: str,
) -> dict[str, Any]:
    for check in report.get("checks", []):
        if check.get("name") == check_name:
            details = check.get("details", {})
            return dict(details) if isinstance(details, dict) else {}
    return {}


def _route_freshness_assessment(
    bundle: dict[str, Any],
    report: dict[str, Any],
    route_paths: list[str],
) -> dict[str, Any]:
    normalized_routes = {
        path.replace("\\", "/").strip("/") for path in route_paths if path
    }
    route_capabilities = {
        capability
        for path in normalized_routes
        for capability in path_index_evidence_capabilities_for_path(bundle, path)
    }
    relevant_capabilities = _capability_dependency_closure(
        bundle, route_capabilities
    )
    repository_paths = {
        str(path).replace("\\", "/").strip("/")
        for path in report.get("repository_changed_paths", [])
        if path
    }
    indexed_details = _freshness_check_details(report, "indexed_paths")
    repository_paths.update(
        str(path).replace("\\", "/").strip("/")
        for key in ("missing_from_index", "stale_in_index")
        for path in indexed_details.get(key, [])
        if path
    )

    relevant_paths: list[str] = []
    unrelated_paths: list[str] = []
    unknown_paths: list[str] = []
    for path in sorted(repository_paths):
        path_capabilities = set(
            path_index_evidence_capabilities_for_path(bundle, path)
        )
        if not path_capabilities:
            unknown_paths.append(path)
        elif path_capabilities & relevant_capabilities:
            relevant_paths.append(path)
        else:
            unrelated_paths.append(path)

    route_unmapped = sorted(
        path
        for path in normalized_routes
        if not path_index_evidence_capabilities_for_path(bundle, path)
    )
    for path in route_unmapped:
        if path not in unknown_paths:
            unknown_paths.append(path)
    failure_reasons = set(report.get("failure_reasons", []))
    localizable_failures = {
        "source_commit",
        "structure_digest",
        "indexed_paths",
    }
    if report.get("status") != "fail":
        classification = "baseline_unchanged"
        route_status = "pass"
        reasons = ["global freshness evidence is current"]
    elif relevant_paths:
        classification = "task_local_new"
        route_status = "fail"
        reasons = ["freshness delta intersects the routed capability closure"]
    elif unknown_paths:
        classification = "unknown"
        route_status = "fail"
        reasons = ["freshness delta contains paths with unresolved capability relevance"]
    elif (
        repository_paths
        and failure_reasons <= localizable_failures
        and (
            "source_commit" not in failure_reasons
            or report.get("comparison_delta_complete") is True
        )
    ):
        classification = "baseline_unchanged"
        route_status = "pass"
        reasons = ["global freshness debt is proven outside the routed capability closure"]
    else:
        classification = "unknown"
        route_status = "fail"
        reasons = ["global freshness failure cannot be localized safely"]
    return {
        "status": route_status,
        "classification": classification,
        "blocking": route_status == "fail",
        "route_paths": sorted(normalized_routes),
        "route_capabilities": sorted(route_capabilities),
        "relevant_capabilities": sorted(relevant_capabilities),
        "relevant_changed_paths": relevant_paths,
        "unrelated_changed_paths": unrelated_paths,
        "unknown_changed_paths": sorted(unknown_paths),
        "global_failure_reasons": sorted(failure_reasons),
        "reasons": reasons,
    }


def _resolution_freshness(
    bundle_root: Path,
    bundle: dict[str, Any],
    changed_paths: list[str],
    *,
    context: str,
) -> dict[str, Any]:
    if context in {"bootstrap", "evaluation"}:
        return {
            "status": "skipped",
            "route_status": "skipped",
            "context": context,
            "failure_reasons": [],
            "changed_paths": list(changed_paths),
        }
    if context != "route":
        raise ValueError(f"unsupported freshness context: {context}")
    routed_bundle = dict(bundle)
    routed_bundle["root"] = bundle_root
    report = freshness_report(bundle_root.parent, routed_bundle, changed_paths)
    report["context"] = "route"
    route_assessment = _route_freshness_assessment(
        bundle, report, changed_paths
    )
    report["route_assessment"] = route_assessment
    report["route_status"] = route_assessment["status"]
    return report


def build_route_report(decision: RouteDecision) -> dict[str, Any]:
    return decision.to_dict()


def build_why_not_actions(
    chosen_action: str,
    repo_stage: str,
    capability: Optional[CapabilityEntry],
    confidence_level: str,
    request_has_change_verb: bool,
    extract_intent: bool,
    changed_paths: list[str],
    duplicate_signal: bool,
    high_risk: bool,
    overlap: float,
    explicit_review: bool,
    negative_signals: dict[str, Any],
) -> dict[str, list[str]]:
    explanations: dict[str, list[str]] = {}
    for candidate_action in ["reuse", "extend", "extract", "new", "review"]:
        if candidate_action == chosen_action:
            continue
        reasons: list[str] = []
        if candidate_action == "reuse":
            if request_has_change_verb:
                reasons.append("request asks for behavior change, not just reuse")
            if repo_stage == "seed":
                reasons.append("seed-stage repositories do not trust existing boundaries enough for auto-reuse")
            if negative_signals.get("provisional_stage"):
                reasons.append("target capability is still provisional")
        elif candidate_action == "extend":
            if repo_stage in {"seed", "emerging"}:
                reasons.append("early-stage repositories restrict automatic extension")
            if not request_has_change_verb:
                reasons.append("request does not clearly describe an additive change")
            if capability and capability.stage not in {"stable", "governed-capability"}:
                reasons.append("capability stage is not stable enough for trusted extension")
        elif candidate_action == "extract":
            if repo_stage in {"seed", "emerging"}:
                reasons.append("early-stage repositories avoid auto-extraction")
            if not extract_intent and not duplicate_signal:
                reasons.append("request does not provide strong extraction or duplicate signals")
            if len(changed_paths) < 2:
                reasons.append("not enough repeated changed surfaces to justify extraction")
        elif candidate_action == "new":
            if repo_stage != "seed" and confidence_level != "low":
                reasons.append("existing structure evidence is strong enough to avoid creating a brand-new capability")
            if negative_signals.get("multi_module_span"):
                reasons.append("cross-module change should be reviewed before creating a new capability")
        elif candidate_action == "review":
            if chosen_action in {"reuse", "extend", "extract", "new"} and not (high_risk or explicit_review or overlap >= 0.82):
                reasons.append("no hard veto condition forced manual review")
        explanations[candidate_action] = reasons
    return explanations


def build_recommended_next_action(
    action: str,
    repo_stage: str,
    confidence_level: str,
    required_reads: list[str],
    required_checks: list[str],
    negative_signals: dict[str, Any],
    veto_reasons: list[str],
) -> tuple[str, list[str]]:
    steps: list[str] = []
    if action == "review":
        next_action = "request_human_review"
        steps.extend(f"Read {path}" for path in required_reads[:3])
        if negative_signals.get("profile_missing"):
            steps.append("Add or refine a repository profile before trusting automatic routing")
        if negative_signals.get("heuristic_public_entry"):
            steps.append("Confirm the real public entry before enabling stronger guardrails")
        steps.append("Record the final decision with sync_feedback.py after human review")
    elif action == "new":
        next_action = "create_new_capability_or_module"
        steps.extend(f"Read {path}" for path in required_reads[:2])
        steps.append("Create the new capability in an isolated module boundary first")
        steps.append("Update profile or ownership rules once the boundary is confirmed")
    elif action == "reuse":
        next_action = "modify_call_site_only"
        steps.extend(f"Read {path}" for path in required_reads[:3])
        steps.extend(f"Run {check}" for check in required_checks[:2])
        steps.append("Avoid changing the routed capability core unless review says otherwise")
    elif action == "extend":
        next_action = "modify_routed_capability"
        steps.extend(f"Read {path}" for path in required_reads[:3])
        steps.extend(f"Run {check}" for check in required_checks[:3])
        steps.append("Apply the change only inside the routed capability boundary")
    else:
        next_action = "extract_shared_capability_first"
        steps.extend(f"Read {path}" for path in required_reads[:3])
        steps.extend(f"Run {check}" for check in required_checks[:3])
        steps.append("Extract shared logic before applying downstream feature changes")

    if confidence_level == "low":
        steps.append("Treat this route as advisory and require manual confirmation before editing")
    if repo_stage in {"seed", "emerging"}:
        steps.append("Keep repository-local routing data provisional until boundaries stabilize")
    for veto_reason in veto_reasons[:2]:
        steps.append(f"Reason for caution: {veto_reason}")
    deduped: list[str] = []
    for step in steps:
        if step not in deduped:
            deduped.append(step)
    return next_action, deduped[:8]


def _path_index_capabilities_for_path(
    bundle: dict[str, Any],
    path: str,
    fields: tuple[str, ...],
) -> list[str]:
    normalized = path.replace("\\", "/").strip("/")
    matches: list[tuple[int, list[str]]] = []
    for entry in bundle.get("path_to_capability_map", {}).get("path_index", []):
        pattern = str(entry.get("path_pattern", "")).replace("\\", "/").strip("/")
        root = pattern[:-3].rstrip("/") if pattern.endswith("/**") else pattern
        if normalized == root or glob_match([pattern], normalized):
            specificity = len(re.sub(r"[*?\[\]]", "", pattern))
            capabilities = list(
                dict.fromkeys(
                    str(capability)
                    for field in fields
                    for capability in entry.get(field, [])
                    if capability
                )
            )
            matches.append((specificity, capabilities))
    if not matches:
        return []
    most_specific = max(score for score, _ in matches)
    return sorted(
        {
            capability
            for score, capabilities in matches
            if score == most_specific
            for capability in capabilities
        }
    )


def path_index_capabilities_for_path(bundle: dict[str, Any], path: str) -> list[str]:
    return _path_index_capabilities_for_path(bundle, path, ("capabilities",))


def path_index_evidence_capabilities_for_path(
    bundle: dict[str, Any],
    path: str,
) -> list[str]:
    return _path_index_capabilities_for_path(
        bundle,
        path,
        ("capabilities", "consumer_capabilities"),
    )


def changed_paths_without_index(bundle: dict[str, Any], changed_paths: list[str]) -> list[str]:
    if not changed_paths:
        return []
    return [path for path in changed_paths if not path_index_capabilities_for_path(bundle, path)]


def build_block_reason(
    action: str,
    repo_stage: str,
    veto_reasons: list[str],
    routing_confidence_level: str,
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    negative_signals: dict[str, Any],
    high_risk: bool,
    overlap: float,
    bundle: dict[str, Any],
    request_text: str,
) -> dict[str, Any]:
    if bundle.get("_runtime", {}).get("stale_bundle", False):
        return {
            "code": "stale_bundle",
            "severity": "P0",
            "summary": "The routing bundle freshness evidence is missing or stale.",
        }
    unindexed_paths = changed_paths_without_index(bundle, changed_paths)
    if unindexed_paths:
        return {
            "code": "path_not_indexed",
            "severity": "P0",
            "summary": "At least one changed path is not covered by the path-to-capability map.",
        }
    shared_paths = [
        path for path in changed_paths if len(path_index_capabilities_for_path(bundle, path)) > 1
    ]
    if shared_paths:
        return {
            "code": "path_not_indexed",
            "severity": "P0",
            "summary": "At least one changed path is not uniquely covered by the path-to-capability map.",
        }
    if action != "review":
        return {"code": "not_blocked", "severity": "none", "summary": "Route does not require manual review."}
    joined = " | ".join(veto_reasons).lower()
    lifecycle_intent = request_lifecycle_intent(request_text)
    if lifecycle_intent:
        code = "capability_lifecycle_change"
        summary = f"Capability {lifecycle_intent} requires explicit lifecycle review."
    elif "no capability candidates" in joined or (not primary_capability and changed_paths):
        code = "missing_capability_candidate"
        summary = "No capability candidate was discovered for the changed surface."
    elif "evaluation threshold not met" in joined:
        code = "evaluation_threshold_not_met"
        summary = "PCR evaluation evidence is missing, stale, or below the approved thresholds."
    elif "bundle is stale" in joined:
        code = "stale_bundle"
        summary = "The routing bundle is stale or internally inconsistent."
    elif high_risk or "high-risk" in joined:
        code = "high_risk_surface"
        summary = "The request touches a high-risk surface."
    elif repo_stage in {"seed", "emerging"} and "repo_stage" in joined:
        code = "early_repo_policy_guardrail"
        summary = "Early repository policy blocks automatic routing."
    elif overlap >= 0.82 or "overlap" in joined or "multi-capability" in joined:
        code = "multi_capability_overlap"
        summary = "Multiple capability candidates overlap too strongly."
    elif negative_signals.get("owner_unclear") or "owner governance" in joined:
        code = "unclear_owner"
        summary = "The candidate capability owner is unclear."
    elif negative_signals.get("provisional_stage") or "provisional" in joined:
        code = "provisional_capability_boundary"
        summary = "The candidate capability boundary is still provisional."
    elif negative_signals.get("heuristic_public_entry") or (primary_capability and not primary_capability.public_entries):
        code = "missing_public_entry"
        summary = "The route lacks a confirmed public entry."
    elif routing_confidence_level == "low" or "confidence_level=low" in joined:
        code = "low_routing_confidence"
        summary = "Routing confidence is too low for automatic editing."
    else:
        code = "manual_review_required"
        summary = "Manual review is required before editing."
    severity = "P0" if code in {"missing_capability_candidate", "path_not_indexed", "stale_bundle", "high_risk_surface", "capability_lifecycle_change", "evaluation_threshold_not_met"} else "P1"
    return {"code": code, "severity": severity, "summary": summary}


def build_missing_evidence(
    action: str,
    block_reason: dict[str, Any],
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    negative_signals: dict[str, Any],
    bundle: dict[str, Any],
    request_text: str,
) -> list[dict[str, Any]]:
    if action != "review":
        return []
    evidence: list[dict[str, Any]] = []
    unindexed_paths = changed_paths_without_index(bundle, changed_paths)
    for path in unindexed_paths:
        evidence.append(
            {
                "type": "path_index",
                "target": path,
                "why_it_matters": "Changed path is not mapped to any capability in path-to-capability-map.yaml.",
            }
        )
    if block_reason.get("code") == "missing_capability_candidate":
        target = ", ".join(changed_paths) if changed_paths else "<request>"
        evidence.append(
            {
                "type": "capability_mapping",
                "target": target,
                "why_it_matters": "The router cannot identify a canonical capability boundary for this change.",
            }
        )
    if negative_signals.get("profile_missing"):
        evidence.append(
            {
                "type": "capability_mapping",
                "target": primary_capability.id if primary_capability else "<unknown>",
                "why_it_matters": "The candidate is generated or heuristic rather than profile-backed.",
            }
        )
    if negative_signals.get("owner_unclear") or not (primary_capability and primary_capability.owner_modules):
        evidence.append(
            {
                "type": "owner_rule",
                "target": primary_capability.id if primary_capability else "<unknown>",
                "why_it_matters": "Automatic editing needs a stable owner or canonical root.",
            }
        )
    if negative_signals.get("heuristic_public_entry") or (primary_capability and not primary_capability.public_entries):
        evidence.append(
            {
                "type": "public_entry",
                "target": primary_capability.id if primary_capability else "<unknown>",
                "why_it_matters": "Reuse or extension is unsafe without a confirmed public entry.",
            }
        )
    if block_reason.get("code") == "multi_capability_overlap":
        evidence.append(
            {
                "type": "dependency_priority",
                "target": "references/change-rules.yaml",
                "why_it_matters": "A multi-capability change needs a primary route before implementation.",
            }
        )
    if request_lifecycle_intent(request_text):
        evidence.append(
            {
                "type": "lifecycle_metadata",
                "target": primary_capability.id if primary_capability else "<unknown>",
                "why_it_matters": "Deleting, merging, or deprecating a capability requires replacement and migration metadata.",
            }
        )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence:
        key = (str(item["type"]), str(item["target"]))
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def build_analysis_directions(
    action: str,
    block_reason: dict[str, Any],
    primary_capability: Optional[CapabilityEntry],
    secondary_capabilities: list[str],
    changed_paths: list[str],
    request_text: str,
) -> list[str]:
    if action != "review":
        return []
    directions = [
        "Inspect the path-to-capability map and capability catalog before making any code changes.",
        "Classify the changed surface as core capability, facade, adapter, UI transport, test, or governance metadata.",
    ]
    code = block_reason.get("code")
    if code in {"missing_capability_candidate", "path_not_indexed"}:
        directions.append("Determine whether the changed paths should map to an existing capability or a new capability boundary.")
    if code == "multi_capability_overlap" or secondary_capabilities:
        directions.append("Compare candidate capabilities by owner_modules, public_entries, contracts, and dependency_priority.")
    if code in {"provisional_capability_boundary", "early_repo_policy_guardrail"}:
        directions.append("Confirm whether the candidate boundary is provisional scaffolding or a stable long-term capability.")
    if code == "missing_public_entry":
        directions.append("Find the real public entry or adapter boundary before deciding between reuse and extension.")
    if code == "capability_lifecycle_change" or request_lifecycle_intent(request_text):
        directions.append("Identify superseded_by, migration impact, callers, tests, and rollback path before changing lifecycle metadata.")
    if primary_capability:
        directions.append(f"Review contracts and forbidden patterns for {primary_capability.id} before proposing implementation work.")
    if changed_paths:
        directions.append("Trace imports and callers for the changed paths to verify whether this is reuse, extension, extraction, or a new boundary.")
    return list(dict.fromkeys(directions))[:8]


def build_safe_next_steps(
    action: str,
    required_reads: list[str],
    required_checks: list[str],
    changed_paths: list[str],
    block_reason: dict[str, Any],
) -> list[str]:
    steps: list[str] = []
    if action == "review":
        steps.append("Read project-change-router/references/path-to-capability-map.yaml for the changed paths.")
        steps.append("Read project-change-router/references/capability-catalog.yaml for candidate capabilities.")
        steps.extend(f"Read {path}" for path in required_reads[:4])
        steps.append("Run python scripts/check_bundle_governance.py --repo <repo-root> --format json before editing.")
        steps.append("Run python scripts/validate_router_bundle.py --repo <repo-root> --format json if the bundle may be stale.")
        if block_reason.get("code") == "capability_lifecycle_change":
            steps.append("Inspect callers, tests, and migration notes before proposing any delete or merge operation.")
    else:
        steps.extend(f"Read {path}" for path in required_reads[:4])
        steps.extend(f"Run {check}" for check in required_checks[:4])
        if action == "new":
            steps.append("Choose and name the isolated new capability boundary before writing code.")
    deduped = [step for step in dict.fromkeys(steps) if step]
    return deduped[:8]


def build_suggested_questions(
    action: str,
    block_reason: dict[str, Any],
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    secondary_capabilities: list[str],
) -> list[str]:
    if action != "review":
        return []
    target = ", ".join(changed_paths[:3]) if changed_paths else "this request"
    questions: list[str] = []
    code = block_reason.get("code")
    if code in {"missing_capability_candidate", "path_not_indexed"}:
        questions.append(f"Which capability should own {target}, or should this become a new capability boundary?")
    if code == "multi_capability_overlap" or secondary_capabilities:
        caps = ", ".join(([primary_capability.id] if primary_capability else []) + secondary_capabilities[:3])
        questions.append(f"Which candidate is the primary route for this change: {caps}?")
    if code in {"missing_public_entry", "provisional_capability_boundary", "unclear_owner"}:
        cap = primary_capability.id if primary_capability else "the candidate capability"
        questions.append(f"What is the confirmed owner and public entry for {cap}?")
    if code == "capability_lifecycle_change":
        questions.append("What capability supersedes this one, and what migration note should be recorded?")
    questions.append("Is this phase limited to routing/governance scaffolding, or is product behavior implementation allowed?")
    return list(dict.fromkeys(questions))[:3]


def build_profile_repair_hints(
    action: str,
    block_reason: dict[str, Any],
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    negative_signals: dict[str, Any],
    request_text: str,
) -> list[dict[str, Any]]:
    if action != "review":
        return []
    hints: list[dict[str, Any]] = []
    if block_reason.get("code") in {"missing_capability_candidate", "path_not_indexed"} and changed_paths:
        hints.append(
            {
                "kind": "ownership_rule",
                "suggestion": f"After confirming ownership, add an ownership rule for {changed_paths[0]} or its stable directory root.",
                "confidence": "medium",
            }
        )
        hints.append(
            {
                "kind": "capability",
                "suggestion": "If this is a new long-term boundary, add a capability entry with contracts, public_entries, test_bindings, and lifecycle metadata.",
                "confidence": "medium",
            }
        )
    if negative_signals.get("profile_missing") and primary_capability:
        hints.append(
            {
                "kind": "capability_profile",
                "suggestion": f"Promote {primary_capability.id} from generated evidence into the repository profile after human confirmation.",
                "confidence": "medium",
            }
        )
    if (negative_signals.get("heuristic_public_entry") or (primary_capability and not primary_capability.public_entries)) and primary_capability:
        hints.append(
            {
                "kind": "public_entry",
                "suggestion": f"Confirm and record public_entries for {primary_capability.id} before allowing automatic reuse or extension.",
                "confidence": "high",
            }
        )
    if request_lifecycle_intent(request_text) and primary_capability:
        hints.append(
            {
                "kind": "lifecycle",
                "suggestion": f"Record superseded_by, deprecation_date, migration_note, and evaluation cases before changing {primary_capability.id}.",
                "confidence": "high",
            }
        )
    hints.append(
        {
            "kind": "evaluation_case",
            "suggestion": "After the human decision, add a curated evaluation case for this routing scenario.",
            "confidence": "high" if action == "review" else "medium",
        }
    )
    return hints[:6]


def build_override_requirements(
    action: str,
    block_reason: dict[str, Any],
    changed_paths: list[str],
    request_text: str,
) -> list[dict[str, Any]]:
    if action != "review":
        return []
    requirements = [
        {
            "scope": "current_task",
            "required_text": "I authorize overriding this router stop only for the current task after recording the reason.",
            "must_record_reason": True,
            "expires_after": "current_task",
        }
    ]
    if changed_paths:
        requirements.append(
            {
                "scope": "paths",
                "allowed_paths": changed_paths,
                "must_record_reason": True,
                "expires_after": "current_task",
            }
        )
    if request_lifecycle_intent(request_text):
        requirements.append(
            {
                "scope": "capability_lifecycle",
                "required_text": "I authorize this lifecycle change with superseded_by, migration_note, and test impact recorded.",
                "must_record_reason": True,
                "expires_after": "current_task",
            }
        )
    if block_reason.get("code") in {"early_repo_policy_guardrail", "path_not_indexed"}:
        requirements.append(
            {
                "scope": "phase",
                "required_text": "I authorize this phase-specific router stop override and do not extend it to later phases.",
                "must_record_reason": True,
                "expires_after": "current_phase",
            }
        )
    return requirements[:4]


def build_write_constraints(
    action: str,
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    forbidden_paths: list[str],
    required_reads: Optional[list[str]] = None,
) -> tuple[list[str], list[str], list[str]]:
    must_read = []
    allowed: list[str] = []
    forbidden = list(forbidden_paths)
    if required_reads is not None:
        must_read.extend(required_reads)
    elif primary_capability:
        must_read.extend(primary_capability.public_entries)
        must_read.extend(primary_capability.owner_modules[:3])
    if action == "review":
        forbidden.append("**")
    elif action == "reuse":
        allowed.extend(changed_paths)
        if primary_capability:
            forbidden.extend(module_path_pattern(path) for path in primary_capability.owner_modules)
    elif action in {"extend", "extract"}:
        if primary_capability:
            allowed.extend(
                module_path_pattern(path)
                for path in scoped_owner_modules(
                    primary_capability.owner_modules,
                    changed_paths,
                )
            )
        allowed.extend(changed_paths)
    elif action == "new":
        allowed.extend(changed_paths)
        if not allowed:
            allowed.append("<new-isolated-capability-boundary-after-confirmation>")
    return (
        [item for item in dict.fromkeys(allowed) if item],
        [item for item in dict.fromkeys(forbidden) if item],
        [item for item in dict.fromkeys(must_read) if item],
    )


def build_post_change_closeout(
    action: str,
    repo_stage: str,
    primary_capability: Optional[CapabilityEntry],
    changed_paths: list[str],
    request_text: str,
) -> list[dict[str, Any]]:
    steps = [
        {
            "step": "validate_bundle",
            "command": "python scripts/validate_router_bundle.py --repo <repo-root> --format json",
            "when": "after any routed change",
        },
        {
            "step": "structure_guardrails",
            "command": "python scripts/check_structure.py --repo <repo-root> --format json",
            "when": "after any product, structure, owner, or baseline change",
        },
        {
            "step": "governance_audit",
            "command": "python scripts/check_bundle_governance.py --repo <repo-root> --format json",
            "when": "after capability, ownership, public entry, lifecycle, or path boundary changes",
        },
        {
            "step": "route_evaluation",
            "command": "python scripts/run_evaluation.py --repo <repo-root> --format json",
            "when": "after route-affecting changes or before committing router metadata",
        },
    ]
    if action in {"new", "extend", "extract"} or request_lifecycle_intent(request_text):
        steps.insert(
            0,
            {
                "step": "rebuild_index_if_boundary_changed",
                "command": "python scripts/rebuild_index.py --repo <repo-root>",
                "when": "after confirmed capability, module, public entry, or lifecycle boundary changes",
            },
        )
    if action == "review" or repo_stage in {"seed", "emerging"}:
        steps.append(
            {
                "step": "record_feedback",
                "command": "python scripts/sync_feedback.py --repo <repo-root> --feedback-file <feedback.json> --format json",
                "when": "after human review or override",
            }
        )
    if primary_capability:
        steps.append(
            {
                "step": "capability_summary",
                "command": "Report whether owner_modules, public_entries, contracts, lifecycle, or evaluation cases changed.",
                "when": f"before closing work on {primary_capability.id}",
            }
        )
    if changed_paths:
        steps.append(
            {
                "step": "gitignore_inclusion_check",
                "command": "Check whether generated or report directories should be ignored before commit.",
                "when": "after creating files",
            }
        )
    return steps[:8]


def build_composite_route(
    action: str,
    primary_capability: Optional[CapabilityEntry],
    candidate_capabilities: list[dict[str, Any]],
    secondary_capabilities: list[str],
    composite_required: bool,
) -> dict[str, Any]:
    participants = []
    candidates = {candidate["id"]: candidate for candidate in candidate_capabilities}
    participant_ids = list(
        dict.fromkeys(
            ([primary_capability.id] if primary_capability else [])
            + secondary_capabilities
        )
    )
    for capability_id in participant_ids:
        candidate = candidates.get(capability_id, {"id": capability_id})
        role = (
            "primary"
            if primary_capability and capability_id == primary_capability.id
            else "secondary"
        )
        participants.append(
            {
                "capability": candidate["id"],
                "role": role,
                "stage": candidate.get("stage"),
                "score": candidate.get("score"),
            }
        )
    return {
        "required": bool(composite_required),
        "primary": primary_capability.id if primary_capability else None,
        "secondary": secondary_capabilities,
        "participants": participants,
        "coordination_policy": "review_before_write" if action == "review" and composite_required else "single_route_or_not_required",
    }


def build_capability_lifecycle_action(
    request_text: str,
    action: str,
    primary_capability: Optional[CapabilityEntry],
) -> dict[str, Any]:
    intent = request_lifecycle_intent(request_text)
    if not intent:
        return {"intent": "none", "review_required": False, "required_metadata": []}
    target_capability = request_lifecycle_target(request_text)
    return {
        "intent": intent,
        "review_required": True,
        "target_capability": target_capability or (primary_capability.id if primary_capability else None),
        "required_metadata": [
            "superseded_by",
            "deprecation_date",
            "migration_note",
            "affected_callers",
            "regression_tests",
            "rollback_plan",
        ],
        "allowed_without_override": action != "review" and intent in {"migrate"},
    }


def build_evaluation_regression_hints(
    action: str,
    request_text: str,
    changed_paths: list[str],
    primary_capability: Optional[CapabilityEntry],
    block_reason: dict[str, Any],
) -> list[dict[str, Any]]:
    if action != "review" and block_reason.get("code") == "not_blocked":
        return []
    expected_capabilities = [primary_capability.id] if primary_capability else []
    return [
        {
            "kind": "route_regression_case",
            "suggested_id": stable_slug(f"{block_reason.get('code', 'route')}-{request_text[:48]}")[:80],
            "expected_action": action,
            "expected_capabilities": expected_capabilities,
            "changed_paths": changed_paths,
            "reason": "Capture this route outcome after human confirmation so future agents do not repeat the same ambiguity.",
        }
    ]


def determine_action(
    request_text: str,
    changed_paths: list[str],
    changed_modules: list[ModuleEntry],
    route_scores: list[tuple[CapabilityEntry, float, dict[str, float]]],
    high_risk: bool,
    bundle: dict[str, Any],
) -> tuple[str, Optional[CapabilityEntry], list[str], float, str, float, bool, bool, list[str], list[str], list[str]]:
    reasoning: list[str] = []
    confidence_reasons: list[str] = []
    veto_reasons: list[str] = []
    if not route_scores:
        action = "review" if high_risk or changed_paths else "new"
        reasoning.append("no capability candidates were discovered")
        confidence_reasons.append("no candidate capabilities were discovered")
        if action == "review":
            veto_reasons.append("no capability candidates were discovered for a changed surface")
        return action, None, [], 0.0, "low", 0.0, False, False, reasoning, confidence_reasons, veto_reasons
    score_sorted = sorted(route_scores, key=lambda item: item[1], reverse=True)
    sorted_scores = sort_route_scores(route_scores, bundle)
    best_cap, best_score, _ = sorted_scores[0]
    best_signals = sorted_scores[0][2]
    if score_sorted and score_sorted[0][0].id != best_cap.id:
        reasoning.append("dependency_priority selected the primary capability among close-scoring candidates")
        confidence_reasons.append("dependency priority resolved close capability candidates")
    confidence_level = confidence_level_for(best_score)
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    ov = overlap_score(best_score, second_score)
    threshold = bundle.get("change_rules", {}).get("confidence", {})
    auto_threshold = float(threshold.get("auto_route_threshold", 0.78))
    guarded_threshold = float(threshold.get("guarded_route_threshold", 0.58))
    repo_stage = bundle.get("config", {}).get("repo_stage", "emerging")
    duplicate_signal, duplicate_count = request_duplicate_signal(request_text, changed_paths)
    request_has_change_verb = request_additive_intent(request_text) or request_prefers_extract(request_text)
    stable_candidates = [
        cap
        for cap, score, _ in sorted_scores
        if score >= guarded_threshold and (cap.stage in {"stable", "governed-capability"} or cap.status == "stable")
    ]
    coordination_required = len(stable_candidates) > 1
    non_core_layers = {"interface", "governance", "test", "docs", "tooling"}
    core_roots: list[str] = []
    for module in changed_modules:
        if module.layer in non_core_layers:
            continue
        module_path = module.path.replace("\\", "/").rstrip("/")
        root = str(Path(module_path).parent).replace("\\", "/") if Path(module_path).suffix in CODE_SUFFIXES else module_path
        if root and root not in core_roots:
            core_roots.append(root)
    collapsed_core_roots = [
        root
        for root in core_roots
        if not any(root != other and root.startswith(other.rstrip("/") + "/") for other in core_roots)
    ]
    primary_owned_modules = set(best_cap.owner_modules)
    changed_modules_within_primary = bool(changed_modules) and all(
        module.path in primary_owned_modules for module in changed_modules
    )
    composite_required = len(collapsed_core_roots) > 1 and coordination_required and not changed_modules_within_primary
    secondary = ordered_secondary_capabilities(
        primary_capability=best_cap.id,
        changed_paths=changed_paths,
        scored_capabilities={
            capability.id: score for capability, score, _ in sorted_scores
        },
        guarded_threshold=guarded_threshold,
        dependency_priority=bundle.get("change_rules", {}).get(
            "dependency_priority", {}
        ),
        path_capabilities=lambda path: path_index_capabilities_for_path(bundle, path),
    )
    high_risk_ids = set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    stale_bundle = bundle.get("_runtime", {}).get("stale_bundle", False)
    has_conflict = bundle.get("_runtime", {}).get("has_conflict", False)
    targets_existing = request_targets_existing_capability(request_text)
    extract_intent = request_prefers_extract(request_text)
    explicit_review = request_requires_review(request_text)
    owner_duplication = request_duplicates_existing_owner(request_text)
    sensitive_review = request_requires_sensitive_review(
        request_text,
        bundle.get("change_rules", {}).get("sensitive_review_phrases", []),
    )
    lifecycle_intent = request_lifecycle_intent(request_text)

    if best_signals["positive_signals"].get("profile_backed"):
        confidence_reasons.append("profile-backed capability mapping")
    if best_signals.get("path_proximity", 0.0) >= 0.8:
        confidence_reasons.append("strong path proximity to owner module")
    if best_signals["positive_signals"].get("has_public_entries"):
        confidence_reasons.append("public entry evidence exists")
    if best_signals["negative_signals"].get("provisional_stage"):
        confidence_reasons.append("capability is only provisional")
    if best_signals["negative_signals"].get("heuristic_public_entry"):
        confidence_reasons.append("public entry is heuristic only")
    if best_signals["negative_signals"].get("profile_missing"):
        confidence_reasons.append("no explicit profile mapping supports this route")

    boundary_matches = matching_capability_contract_boundaries(
        _positive_request_scope(request_text),
        best_cap.forbidden_patterns,
        best_cap.anti_patterns,
    )
    if boundary_matches:
        reasoning.append("capability contract boundary matched: " + ", ".join(boundary_matches[:3]))
        veto_reasons.append("capability contract boundary requires review")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons

    if owner_duplication:
        reasoning.append("request duplicates an existing canonical owner or local substrate")
        veto_reasons.append("duplicate owner implementation requires boundary review")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if sensitive_review:
        reasoning.append("sensitive persistence or trace surface requires manual review")
        veto_reasons.append("sensitive persistence or trace surface requires review")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if high_risk and (best_cap.id in high_risk_ids or ov >= 0.75):
        reasoning.append("high-risk request requires manual review")
        veto_reasons.append("high-risk capability or overlapping high-risk candidates")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if stale_bundle or has_conflict:
        reasoning.append("routing bundle is stale or internally inconsistent")
        veto_reasons.append("bundle is stale or conflicts exist")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if lifecycle_intent:
        reasoning.append(f"capability lifecycle intent detected: {lifecycle_intent}")
        veto_reasons.append("capability lifecycle changes require review")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if extract_intent:
        if repo_stage in {"seed", "emerging"}:
            reasoning.append("early-stage repository requires manual review before extraction")
            veto_reasons.append("extract is blocked in early-stage repositories")
            return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        if len(changed_paths) >= 2 or len({module.path for module in changed_modules}) >= 2:
            reasoning.append("explicit extraction intent with repeated changed surfaces")
            return "extract", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("explicit extraction intent without enough repeated surface evidence")
        veto_reasons.append("extract lacks enough repeated-surface evidence")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if not changed_paths and not targets_existing and best_score < auto_threshold:
        reasoning.append("request is not anchored to an existing capability or changed surface")
        confidence_reasons.append("request lacks changed-path anchoring")
        return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if not changed_paths and not targets_existing and best_score == 0.0:
        reasoning.append("request does not align with any existing capability signals")
        confidence_reasons.append("no existing capability signals were matched")
        return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if explicit_review or composite_required:
        reasoning.append("request spans multiple capability surfaces or explicitly asks for review")
        veto_reasons.append("explicit review requested or multi-capability request detected")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if repo_stage == "seed":
        if not targets_existing and not composite_required and len(changed_paths) <= 1:
            reasoning.append("seed-stage repository defaults to new capability suggestions")
            confidence_reasons.append("seed-stage repositories do not trust auto-reuse without changed surfaces")
            return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("seed-stage repository does not auto-route into existing capability boundaries")
        veto_reasons.append("repo_stage=seed blocks auto-route into existing boundaries")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if repo_stage == "emerging" and best_cap.stage == "provisional":
        if not changed_paths and not targets_existing:
            reasoning.append("emerging repository avoids promoting provisional capability guesses into new boundaries")
            confidence_reasons.append("provisional capability lacks enough structure evidence")
            return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("emerging repository treats provisional capabilities as review-only")
        veto_reasons.append("repo_stage=emerging blocks auto-routing to provisional capability")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if duplicate_signal and duplicate_count >= 2 and (
        len(changed_paths) >= 2 or len({module.path for module in changed_modules}) >= 2
    ):
        if repo_stage in {"seed", "emerging"}:
            reasoning.append("early-stage repository defers duplicate extraction to manual review")
            veto_reasons.append("duplicate-based extract is blocked in early-stage repositories")
            return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("duplicate signal indicates shared extraction work")
        return "extract", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if ov >= 0.82 and not changed_paths:
        reasoning.append("multiple capability candidates overlap too heavily")
        veto_reasons.append("overlap between top capability candidates is too high")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if confidence_level == "low":
        reasoning.append("low confidence route is downgraded to review")
        veto_reasons.append("confidence_level=low")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if best_score < guarded_threshold:
        if changed_paths and best_signals.get("path_proximity", 0.0) >= 0.8 and not high_risk and repo_stage in {"emerging", "structured", "governed"}:
            if request_has_change_verb:
                if repo_stage == "emerging" and best_cap.stage not in {"stable", "governed-capability"}:
                    reasoning.append("emerging repository only allows path-anchored extend on stable capabilities")
                    veto_reasons.append("emerging path-anchored extend requires stable capability")
                    return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
                reasoning.append("path proximity strongly anchors the request to an existing module surface")
                return "extend", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
            reasoning.append("path proximity strongly anchors the request to an existing module surface")
            return "reuse", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        action = "review" if high_risk else "new"
        reasoning.append("no candidate exceeded the guarded routing threshold")
        confidence_reasons.append("candidate score is below guarded threshold")
        return action, best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if best_cap.stage in {"stable", "governed-capability"} or best_cap.status == "stable":
        if request_has_change_verb and (best_cap.extension_points or best_cap.public_entries) and (best_score >= auto_threshold or targets_existing):
            if repo_stage == "emerging" and best_cap.stage == "candidate":
                reasoning.append("emerging repository will not extend candidate capability boundaries automatically")
                veto_reasons.append("emerging repo blocks extend on candidate capability")
                return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
            reasoning.append("stable capability selected for additive extension")
            return "extend", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("stable capability selected for reuse")
        return "reuse", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if repo_stage in {"structured", "governed"} and request_has_change_verb and (best_cap.extension_points or best_cap.public_entries):
        reasoning.append("candidate capability can be extended but still needs caution")
        return "extend", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    reasoning.append("capability remains below the maturity threshold for automatic routing")
    veto_reasons.append("capability maturity is below automatic routing threshold")
    return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons


def resolve_request(
    request_text: str,
    changed_paths: list[str],
    bundle: dict[str, Any],
    bundle_root: Path,
    *,
    enforce_evaluation_policy: bool = True,
    freshness_context: Optional[str] = None,
) -> RouteDecision:
    capabilities = capability_entries(bundle)
    modules = module_entries(bundle)
    normalized_changed_paths = list(
        dict.fromkeys(path.replace("\\", "/") for path in changed_paths)
    )
    changed_modules = [module_for_path(path, modules) for path in normalized_changed_paths]
    changed_modules = [module for module in changed_modules if module is not None]
    high_risk = request_high_risk(request_text, normalized_changed_paths, modules, bundle)
    route_scores: list[tuple[CapabilityEntry, float, dict[str, float]]] = []
    for capability in capabilities:
        score, signals = capability_score(request_text, capability, changed_modules, normalized_changed_paths, bundle)
        if score > 0.0 or capability.status == "stable":
            route_scores.append((capability, score, signals))
    effective_freshness_context = freshness_context
    if effective_freshness_context is None:
        if not enforce_evaluation_policy:
            effective_freshness_context = "evaluation"
        elif bundle.get("_resolution_context") == "bootstrap":
            effective_freshness_context = "bootstrap"
        elif bundle_root.name == "project-change-router":
            effective_freshness_context = "route"
        else:
            effective_freshness_context = "evaluation"
    freshness = _resolution_freshness(
        bundle_root,
        bundle,
        normalized_changed_paths,
        context=effective_freshness_context,
    )
    bundle["_runtime"] = {
        "stale_bundle": freshness.get("route_status", freshness["status"]) == "fail",
        "freshness": freshness,
        "has_conflict": bool(capability_conflicts(bundle)),
    }
    action, primary_capability, secondary_capabilities, routing_confidence, routing_confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons = determine_action(
        request_text,
        normalized_changed_paths,
        changed_modules,
        route_scores,
        high_risk,
        bundle,
    )
    if freshness.get("route_status", freshness["status"]) == "fail":
        action = "review"
        if "routing bundle freshness evidence failed" not in reasoning:
            reasoning.append("routing bundle freshness evidence failed")
        if "bundle is stale or freshness evidence is missing" not in veto_reasons:
            veto_reasons.append("bundle is stale or freshness evidence is missing")
    owner_assessment = capabilities_owner_assessment(
        bundle,
        ([primary_capability.id] if primary_capability else [])
        + secondary_capabilities,
    )
    if action != "review" and not owner_assessment["trusted"]:
        action = "review"
        reasoning.append("capability owner governance blocks automatic write eligibility")
        veto_reasons.append(
            "capability owner governance is incomplete: "
            + ", ".join(owner_assessment["reasons"])
        )
    evaluation_decision = policy_for_bundle(bundle)
    if enforce_evaluation_policy and action != "review" and not evaluation_decision.passed:
        action = "review"
        reasoning.append("PCR evaluation policy blocks automatic write eligibility")
        veto_reasons.append(
            "evaluation threshold not met: " + ", ".join(evaluation_decision.reasons)
        )
    sorted_scores = sort_route_scores(route_scores, bundle)
    best_signals = sorted_scores[0][2] if sorted_scores else {}
    candidate_capabilities = [
        {
            "id": capability.id,
            "name": capability.name,
            "status": capability.status,
            "stage": capability.stage,
            "score": round(score, 4),
            "signals": signals,
        }
        for capability, score, signals in sorted_scores
    ]
    candidate_modules = [
        {"path": module.path, "id": module.id, "layer": module.layer, "domain": module.domain}
        for module in changed_modules
    ]
    if not candidate_modules and modules:
        candidate_modules = [{"path": module.path, "id": module.id, "layer": module.layer, "domain": module.domain} for module in modules[:3]]
    required_reads = required_read_paths(primary_capability, modules, normalized_changed_paths)
    required_checks = required_checks_for(
        primary_capability,
        action,
        bundle,
        normalized_changed_paths,
    )
    forbidden_paths = forbidden_paths_for(primary_capability, bundle)
    decision_id = f"route-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1((request_text + '|' + '|'.join(normalized_changed_paths)).encode('utf-8')).hexdigest()[:8]}"
    positive_signals = best_signals.get("positive_signals", {}) if route_scores else {}
    negative_signals = best_signals.get("negative_signals", {}) if route_scores else {}
    if not owner_assessment["trusted"]:
        negative_signals["owner_unclear"] = True
    risk_signals = best_signals.get("risk_signals", {}) if route_scores else {}
    decision_confidence, decision_confidence_level, decision_basis = decision_confidence_for(
        action,
        bundle.get("config", {}).get("repo_stage", "emerging"),
        routing_confidence,
        veto_reasons,
        high_risk,
    )
    request_has_change_verb = any(word in request_text.lower() for word in CHANGE_VERBS)
    why_not_actions = build_why_not_actions(
        action,
        bundle.get("config", {}).get("repo_stage", "emerging"),
        primary_capability,
        routing_confidence_level,
        request_has_change_verb,
        request_prefers_extract(request_text),
        normalized_changed_paths,
        request_duplicate_signal(request_text, normalized_changed_paths)[0],
        high_risk,
        ov,
        request_requires_review(request_text),
        negative_signals,
    )
    recommended_next_action, recommended_next_steps = build_recommended_next_action(
        action,
        bundle.get("config", {}).get("repo_stage", "emerging"),
        routing_confidence_level,
        required_reads,
        required_checks,
        negative_signals,
        veto_reasons,
    )
    block_reason = build_block_reason(
        action,
        bundle.get("config", {}).get("repo_stage", "emerging"),
        veto_reasons,
        routing_confidence_level,
        primary_capability,
        normalized_changed_paths,
        negative_signals,
        high_risk,
        ov,
        bundle,
        request_text,
    )
    mandatory_review_codes = {
        "missing_capability_candidate",
        "path_not_indexed",
        "stale_bundle",
        "high_risk_surface",
        "capability_lifecycle_change",
        "evaluation_threshold_not_met",
    }
    guardrail_review_required = action == "review" or block_reason.get("code") in mandatory_review_codes
    governance_action = "review" if guardrail_review_required else action
    if governance_action != action:
        recommended_next_action, recommended_next_steps = build_recommended_next_action(
            governance_action,
            bundle.get("config", {}).get("repo_stage", "emerging"),
            routing_confidence_level,
            required_reads,
            required_checks,
            negative_signals,
            veto_reasons,
        )
    missing_evidence = build_missing_evidence(
        governance_action,
        block_reason,
        primary_capability,
        normalized_changed_paths,
        negative_signals,
        bundle,
        request_text,
    )
    analysis_directions = build_analysis_directions(
        governance_action,
        block_reason,
        primary_capability,
        secondary_capabilities,
        normalized_changed_paths,
        request_text,
    )
    safe_next_steps = build_safe_next_steps(
        governance_action,
        required_reads,
        required_checks,
        normalized_changed_paths,
        block_reason,
    )
    suggested_questions = build_suggested_questions(
        governance_action,
        block_reason,
        primary_capability,
        normalized_changed_paths,
        secondary_capabilities,
    )
    profile_repair_hints = build_profile_repair_hints(
        governance_action,
        block_reason,
        primary_capability,
        normalized_changed_paths,
        negative_signals,
        request_text,
    )
    override_requirements = build_override_requirements(
        governance_action,
        block_reason,
        normalized_changed_paths,
        request_text,
    )
    allowed_write_paths, forbidden_write_paths, must_read_before_edit = build_write_constraints(
        governance_action,
        primary_capability,
        normalized_changed_paths,
        forbidden_paths,
        required_reads,
    )
    post_change_closeout = build_post_change_closeout(
        governance_action,
        bundle.get("config", {}).get("repo_stage", "emerging"),
        primary_capability,
        normalized_changed_paths,
        request_text,
    )
    composite_route = build_composite_route(
        action,
        primary_capability,
        candidate_capabilities,
        secondary_capabilities,
        composite_required,
    )
    capability_lifecycle_action = build_capability_lifecycle_action(
        request_text,
        action,
        primary_capability,
    )
    evaluation_regression_hints = build_evaluation_regression_hints(
        action,
        request_text,
        normalized_changed_paths,
        primary_capability,
        block_reason,
    )
    source_of_truths = {
        "capability_catalog": source_of_truth_for(bundle, "capability"),
        "module_map": source_of_truth_for(bundle, "module"),
        "exception_registry": source_of_truth_for(bundle, "exception"),
    }
    authorization_context = {
        "source_commit": freshness.get("source_commit"),
        "structure_digest": freshness.get("structure_digest"),
        "routing_truth_digest": routing_truth_digest(bundle),
        "freshness_classification": freshness.get(
            "route_assessment", {}
        ).get("classification", freshness.get("status")),
    }
    decision = RouteDecision(
        decision_id=decision_id,
        timestamp=iso_now(),
        request_type=parse_request_type(request_text),
        request_summary=request_text.strip().splitlines()[0][:180] if request_text.strip() else "",
        changed_paths=normalized_changed_paths,
        repo_stage=bundle.get("config", {}).get("repo_stage", "emerging"),
        action=action,
        decision_basis=decision_basis,
        routing_confidence=round(routing_confidence, 4),
        routing_confidence_level=routing_confidence_level,
        decision_confidence=round(decision_confidence, 4),
        decision_confidence_level=decision_confidence_level,
        confidence=round(routing_confidence, 4),
        confidence_level=routing_confidence_level,
        overlap_score=round(ov, 4),
        primary_capability=primary_capability.id if primary_capability else None,
        primary_capability_stage=primary_capability.stage if primary_capability else None,
        secondary_capabilities=secondary_capabilities,
        candidate_capabilities=candidate_capabilities,
        candidate_modules=candidate_modules,
        required_reads=required_reads,
        required_checks=required_checks,
        forbidden_paths=forbidden_paths,
        review_required=guardrail_review_required,
        coordination_required=coordination_required,
        composite_route_required=composite_required,
        recommended_next_action=recommended_next_action,
        recommended_next_steps=recommended_next_steps,
        why_not_actions=why_not_actions,
        block_reason=block_reason,
        missing_evidence=missing_evidence,
        analysis_directions=analysis_directions,
        safe_next_steps=safe_next_steps,
        suggested_questions=suggested_questions,
        profile_repair_hints=profile_repair_hints,
        override_requirements=override_requirements,
        allowed_write_paths=allowed_write_paths,
        forbidden_write_paths=forbidden_write_paths,
        must_read_before_edit=must_read_before_edit,
        post_change_closeout=post_change_closeout,
        composite_route=composite_route,
        capability_lifecycle_action=capability_lifecycle_action,
        evaluation_regression_hints=evaluation_regression_hints,
        confidence_reasons=confidence_reasons,
        veto_reasons=veto_reasons,
        positive_signals=positive_signals,
        negative_signals=negative_signals,
        risk_signals=risk_signals,
        reasoning=reasoning,
        authorization_context=authorization_context,
        route_fingerprint="",
        source_of_truths=source_of_truths,
    )
    decision.route_fingerprint = route_authorization_fingerprint(decision.to_dict())
    return decision


def normalized_code(text: str) -> str:
    text = re.sub(r"//.*?$|/\*.*?\*/|#.*?$", " ", text, flags=re.M | re.S)
    text = re.sub(r"--.*?$", " ", text, flags=re.M)
    string_pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''  # noqa: W605
    text = re.sub(string_pattern, '"STR"', text)
    text = re.sub(r"\b\d+(\.\d+)?\b", "NUM", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def similarity(a: Path, b: Path) -> float:
    a_text = normalized_code(a.read_text(encoding="utf-8", errors="ignore"))
    b_text = normalized_code(b.read_text(encoding="utf-8", errors="ignore"))
    return difflib.SequenceMatcher(None, a_text, b_text).ratio()


def matches_dependency(
    source: ModuleEntry,
    target: ModuleEntry,
    dependency_path: Optional[str] = None,
) -> bool:
    strict_nested_boundary = bool(source.lifecycle.get("nested_module_boundary"))
    has_declared_paths = "declared_allowed_outbound_to" in source.lifecycle
    configured_paths = (
        source.lifecycle.get("declared_allowed_outbound_to", [])
        if strict_nested_boundary
        else source.allowed_outbound_to
    )
    allowed_paths = [pattern.replace("\\", "/") for pattern in configured_paths]
    target_paths = [target.path.replace("\\", "/")]
    if dependency_path:
        target_paths.append(dependency_path.replace("\\", "/"))
    if strict_nested_boundary and has_declared_paths:
        return bool(
            allowed_paths
            and any(glob_match(allowed_paths, path) for path in target_paths)
        )
    if not strict_nested_boundary and target.path in source.depends_on:
        return True
    if allowed_paths and any(glob_match(allowed_paths, path) for path in target_paths):
        return True
    allowed_layers = source.lifecycle.get("allowed_outbound_layers", [])
    return target.layer in allowed_layers


def _module_for_source_path(path: str, modules: list[ModuleEntry]) -> Optional[ModuleEntry]:
    normalized = path.replace("\\", "/").strip("/")
    candidates = []
    for module in modules:
        module_path = module.path.replace("\\", "/").strip("/")
        if any(marker in module_path for marker in "*?["):
            continue
        if module_path in {"", "."} or normalized == module_path or normalized.startswith(module_path.rstrip("/") + "/"):
            candidates.append(module)
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item.path.replace("\\", "/").strip("/")))


def _guardrail_source_files(
    repo_root: Path, modules: list[ModuleEntry], ignore_patterns: Iterable[str]
) -> list[Path]:
    files: dict[str, Path] = {}
    for module in modules:
        module_root = repo_root if module.path == "." else repo_root / module.path
        if not module_root.exists() or any(marker in module.path for marker in "*?["):
            continue
        candidates = [module_root] if module_root.is_file() else iter_source_files(module_root, ignore_patterns)
        for path in candidates:
            if path.is_file() and path.suffix.lower() in CODE_SUFFIXES and not should_ignore_path(path, ignore_patterns, repo_root):
                files[normalize_rel_path(repo_root, path)] = path
    return [files[key] for key in sorted(files)]


def gather_dependency_findings(repo_root: Path, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    source_files = _guardrail_source_files(repo_root, modules, ignore_patterns)
    resolution_files = iter_source_files(repo_root, ignore_patterns)
    snapshot = build_import_graph(repo_root, source_files, resolution_paths=resolution_files)
    findings: list[dict[str, Any]] = []
    for edge in snapshot.edges:
        source = _module_for_source_path(edge.source, modules)
        target = _module_for_source_path(edge.target, modules)
        if source is None or target is None or source.path == target.path:
            continue
        if not matches_dependency(source, target, dependency_path=edge.target):
            findings.append(
                {
                    "severity": "P1",
                    "rule": "dependency-direction",
                    "source": edge.source,
                    "target": edge.target,
                    "source_file": edge.source,
                    "source_module": source.path,
                    "target_module": target.path,
                    "import": edge.import_name,
                    "language": edge.language,
                    "runtime": edge.runtime,
                    "message": f"{source.path} imports {target.path} outside its allowed dependency surface",
                }
            )
    for cycle in snapshot.cycles:
        findings.append(
            {
                "severity": "P1" if cycle.runtime else "P2",
                "rule": "runtime-cycle" if cycle.runtime else "type-only-cycle",
                "language": cycle.language,
                "members": list(cycle.members),
                "message": f"{cycle.language} {'runtime' if cycle.runtime else 'type-only'} cycle: {' -> '.join(cycle.members)}",
            }
        )
    for diagnostic in snapshot.diagnostics:
        findings.append(
            {
                "severity": "P1" if diagnostic.blocking else "P2",
                "rule": "import-graph-diagnostic",
                "source": diagnostic.path,
                "language": diagnostic.language,
                "diagnostic_code": diagnostic.code,
                "message": diagnostic.message,
            }
        )
    for source_file in source_files:
        if file_suffix_kind(source_file) != "java":
            continue
        source = _module_for_source_path(normalize_rel_path(repo_root, source_file), modules)
        if source is None:
            continue
        for imported in parse_java_imports(source_file):
            target = resolve_import_to_module(imported, source, modules, repo_root, source_file)
            if target and target.path != source.path and not matches_dependency(source, target):
                findings.append(
                    {
                        "severity": "P1",
                        "rule": "dependency-direction",
                        "source": normalize_rel_path(repo_root, source_file),
                        "target": target.path,
                        "source_file": normalize_rel_path(repo_root, source_file),
                        "source_module": source.path,
                        "target_module": target.path,
                        "import": imported,
                        "language": "java",
                        "runtime": True,
                        "message": f"{source.path} imports {target.path} outside its allowed dependency surface",
                    }
                )
    baseline = bundle.get("change_rules", {}).get("architecture_baseline", [])
    return classify_findings_against_baseline(
        findings,
        baseline,
        governed_rules={"dependency-direction", "runtime-cycle", "type-only-cycle"},
    )


def import_reaches_private_surface(import_name: str, resolved_path: Optional[str]) -> bool:
    lowered = import_name.lower()
    if any(f".{segment}." in lowered or f"/{segment}/" in lowered for segment in PRIVATE_SEGMENTS):
        return True
    if resolved_path:
        rel = resolved_path.lower().replace("\\", "/")
        if any(f"/{segment}/" in rel for segment in PRIVATE_SEGMENTS):
            return True
    return False


def import_matches_public_surface(import_name: str, target: ModuleEntry, resolved_path: Optional[str]) -> bool:
    lowered = import_name.lower()
    for name in public_import_names(target):
        public_name = name.lower()
        if lowered == public_name or lowered.startswith(public_name + ".") or lowered.startswith(public_name + "/"):
            if not import_reaches_private_surface(import_name, resolved_path):
                return True
    if resolved_path and target.public_api:
        expected_prefix = f"{target.path}/{target.public_api}".replace("\\", "/").strip("/")
        normalized = resolved_path.replace("\\", "/").strip("/")
        if normalized == expected_prefix or normalized.startswith(expected_prefix.rstrip("/") + "/"):
            return True
    return False


def gather_public_api_findings(repo_root: Path, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    source_files = _guardrail_source_files(repo_root, modules, ignore_patterns)
    resolution_files = iter_source_files(repo_root, ignore_patterns)
    snapshot = build_import_graph(repo_root, source_files, resolution_paths=resolution_files)
    findings: list[dict[str, Any]] = []
    for module in modules:
        if not module.public_api:
            continue
        public_api = module.public_api.replace("\\", "/").strip("/")
        module_path = module.path.replace("\\", "/").strip("/")
        public_path = public_api if public_api.startswith(module_path + "/") else f"{module_path}/{public_api}"
        exports = [item for item in snapshot.exports if item.source == public_path]
        if exports:
            findings.append(
                {
                    "severity": "P1",
                    "rule": "public-export-count",
                    "module": exports[0].module,
                    "count": len({item.symbol for item in exports}),
                    "source": public_path,
                    "owner": module.owner,
                    "message": f"{public_path} exports {len({item.symbol for item in exports})} public symbols",
                }
            )
    for edge in snapshot.edges:
        source = _module_for_source_path(edge.source, modules)
        target = _module_for_source_path(edge.target, modules)
        if source is None or target is None or source.path == target.path or not target.public_api:
            continue
        if not import_matches_public_surface(edge.import_name, target, edge.target):
            findings.append(
                {
                    "severity": "P1",
                    "rule": "public-api-bypass",
                    "source": edge.source,
                    "target": edge.target,
                    "source_file": edge.source,
                    "source_module": source.path,
                    "target_module": target.path,
                    "import": edge.import_name,
                    "imported_symbols": list(edge.imported_symbols),
                    "message": f"{source.path} reaches {target.path} through a non-public import path",
                }
            )
    for source_file in source_files:
        if file_suffix_kind(source_file) != "java":
            continue
        source = _module_for_source_path(normalize_rel_path(repo_root, source_file), modules)
        if source is None:
            continue
        for imported in parse_java_imports(source_file):
            target, resolved_path = infer_import_reference(imported, source, modules, repo_root, source_file)
            if target and target.path != source.path and target.public_api and not import_matches_public_surface(imported, target, resolved_path):
                findings.append(
                    {
                        "severity": "P1",
                        "rule": "public-api-bypass",
                        "source": normalize_rel_path(repo_root, source_file),
                        "target": resolved_path or target.path,
                        "source_file": normalize_rel_path(repo_root, source_file),
                        "source_module": source.path,
                        "target_module": target.path,
                        "import": imported,
                        "message": f"{source.path} reaches {target.path} through a non-public import path",
                    }
                )
    baseline = bundle.get("change_rules", {}).get("architecture_baseline", [])
    return classify_findings_against_baseline(
        findings,
        baseline,
        governed_rules={"public-api-bypass", "public-export-count"},
    )


def guardrail_finding_is_blocking(finding: dict[str, Any]) -> bool:
    if "blocking" in finding:
        return bool(finding["blocking"])
    return finding.get("severity") in {"P0", "P1"}


def guardrail_status(findings: list[dict[str, Any]]) -> tuple[str, bool]:
    blocking = any(guardrail_finding_is_blocking(finding) for finding in findings)
    return ("fail" if blocking else "warn" if findings else "pass"), blocking


def _reuse_scan_environment() -> ReuseScanEnvironment:
    return ReuseScanEnvironment(
        normalize_rel_path=normalize_rel_path,
        should_ignore_path=should_ignore_path,
        iter_source_files=iter_source_files,
        source_files_for_modules=source_files_for_modules,
        root_owner_fallback_modules=root_owner_fallback_modules,
        derive_path_tokens=derive_path_tokens,
        normalized_code=normalized_code,
        text_tokens=text_tokens,
        code_suffixes=frozenset(CODE_SUFFIXES),
        generic_path_tokens=frozenset(GENERIC_PATH_TOKENS),
    )


def changed_path_candidate_files(
    repo_root: Path,
    changed_paths: list[str],
    ignore_patterns: Iterable[str],
) -> list[Path]:
    return _changed_path_candidate_files(
        _reuse_scan_environment(), repo_root, changed_paths, ignore_patterns
    )


def gather_reuse_report(
    repo_root: Path,
    bundle: dict[str, Any],
    changed_paths: Optional[list[str]] = None,
    budget_overrides: Optional[dict[str, Any]] = None,
    runtime_options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return _gather_reuse_report(
        _reuse_scan_environment(),
        repo_root,
        bundle,
        module_entries(bundle),
        capability_entries(bundle),
        default_ignore_patterns(bundle.get("config", {})),
        changed_paths,
        budget_overrides,
        runtime_options,
    )


def gather_reuse_findings(
    repo_root: Path,
    bundle: dict[str, Any],
    changed_paths: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    return gather_reuse_report(repo_root, bundle, changed_paths)["findings"]


def bundle_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    config = bundle.get("config", {})
    return {
        "repo_id": config.get("repo_id"),
        "repositories": config.get("repositories", []),
        "protected_branch_patterns": config.get("protected_branch_patterns", []),
        "freshness_windows": config.get("freshness_windows", {}),
    }


def create_bundle_directory(repo_root: Path) -> Path:
    bundle_root = resolve_bundle_root(repo_root)
    for rel in [
        ".",
        "references",
        "schemas",
        "reports/route-decisions",
        "reports/index-rebuild",
        "reports/guardrail-results",
        "reports/evaluation",
    ]:
        (bundle_root / rel).mkdir(parents=True, exist_ok=True)
    return bundle_root


def copy_skill_schemas_to_bundle(bundle_root: Path) -> None:
    target = bundle_root / "schemas"
    target.mkdir(parents=True, exist_ok=True)
    for schema_file in schema_dir().glob("*.json"):
        target_file = target / schema_file.name
        content = schema_file.read_text(encoding="utf-8")
        if target_file.exists() and target_file.read_text(encoding="utf-8") == content:
            continue
        write_text_in_chunks(target_file, content)


def clear_core_reference_files(bundle_root: Path) -> None:
    for rel in [
        "router-config.yaml",
        "references/capability-catalog.yaml",
        "references/module-map.yaml",
        "references/ownership.yaml",
        "references/change-rules.yaml",
        "references/path-to-capability-map.yaml",
        "references/exception-registry.yaml",
        "references/evaluation-set.yaml",
    ]:
        path = bundle_root / rel
        if path.exists():
            path.unlink()


def ensure_gitignore_entry(repo_root: Path, entry: str) -> None:
    gitignore_path = repo_root / ".gitignore"
    normalized_entry = entry.replace("\\", "/").strip()
    if gitignore_path.exists():
        lines = gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    else:
        lines = []
    existing = {line.strip().replace("\\", "/") for line in lines if line.strip()}
    if normalized_entry not in existing:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(normalized_entry)
        gitignore_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def bootstrap_bundle(repo_root: Path, write: bool = True) -> dict[str, Any]:
    bundle = build_router_bundle(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    bundle["root"] = bundle_root
    bundle["_resolution_context"] = "bootstrap"
    if write:
        assert_bootstrap_write_allowed(repo_root, load_active_profile(repo_root))
        create_bundle_directory(repo_root)
        clear_core_reference_files(bundle_root)
        write_bundle(bundle_root, bundle)
        copy_skill_schemas_to_bundle(bundle_root)
        ensure_gitignore_entry(repo_root, "project-change-router/")
    return bundle


def write_report(path: Path, report: dict[str, Any]) -> None:
    dump_json_file(path, report)


def locate_bundle_or_raise(repo_root: Path) -> Path:
    bundle_root = resolve_bundle_root(repo_root)
    if not bundle_root.exists():
        raise FileNotFoundError(f"project-change-router bundle not found at {bundle_root}")
    return bundle_root


def evaluate_bundle(bundle: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    evaluation_set = bundle.get("evaluation_set", {})
    evaluations = evaluation_set.get("cases", [])
    capabilities = capability_entries(bundle)
    capability_ids = {capability.id for capability in capabilities}
    coverage_capability_ids = {
        capability.id
        for capability in capabilities
        if capability.status == "stable"
        or capability.stage in {"stable", "governed-capability"}
    } or capability_ids
    results = []
    for case in evaluations:
        decision = resolve_request(
            case["request"],
            case.get("changed_paths", []),
            bundle,
            bundle.get("root", resolve_bundle_root(repo_root)),
            enforce_evaluation_policy=False,
            freshness_context="evaluation",
        )
        action_ok = decision.action == case["expected_action"]
        capability_contract = compare_capability_contract(
            case,
            predicted_primary=decision.primary_capability,
            predicted_secondary=decision.secondary_capabilities,
        )
        primary_ok = capability_contract["primary_ok"]
        results.append(
            {
                "id": case["id"],
                "expected_action": case["expected_action"],
                "predicted_action": decision.action,
                "expected_capabilities": case.get("expected_capabilities", []),
                "predicted_capability": decision.primary_capability,
                "action_ok": action_ok,
                "primary_ok": primary_ok,
                **capability_contract,
            }
        )
    raw_curated_ids = evaluation_set.get("curated_case_ids", [])
    curated_ids = {
        case_id for case_id in raw_curated_ids if isinstance(case_id, str)
    } if isinstance(raw_curated_ids, list) else set()
    metric_results = (
        [result for result in results if result["id"] in curated_ids]
        if evaluation_set.get("mode") in {"curated", "hybrid"} and curated_ids
        else results
    )
    total = max(1, len(metric_results))
    action_matches = sum(int(result["action_ok"]) for result in metric_results)
    primary_matches = sum(int(result["primary_ok"]) for result in metric_results)
    review_expected = sum(result["expected_action"] == "review" for result in metric_results)
    review_predicted = sum(result["predicted_action"] == "review" for result in metric_results)
    review_hits = sum(result["expected_action"] == "review" and result["predicted_action"] == "review" for result in metric_results)
    strict_secondary = [result for result in metric_results if result["strict_secondary"]]
    strict_secondary_cases = len(strict_secondary)
    strict_secondary_matches = sum(int(result["secondary_ok"]) for result in strict_secondary)
    covered_capability_ids = {
        capability
        for result in metric_results
        for capability in (
            [result["expected_primary_capability"]]
            + result["expected_secondary_capabilities"]
        )
        if capability
    }
    evaluation_config = bundle.get("config", {}).get("evaluation", {})
    action_accuracy = action_matches / total
    coverage_ratio = len(coverage_capability_ids & covered_capability_ids) / max(1, len(coverage_capability_ids))
    review_precision = review_hits / max(1, review_predicted)
    review_recall = review_hits / max(1, review_expected)
    secondary_contract_accuracy = (
        strict_secondary_matches / strict_secondary_cases
        if strict_secondary_cases
        else 1.0
    )
    policy_decision = evaluate_configured_policy(
        {
            "top1_action_accuracy": action_accuracy,
            "top1_capability_accuracy": primary_matches / total,
            "review_precision": review_precision,
            "review_recall": review_recall,
            "capability_coverage_ratio": coverage_ratio,
            "secondary_contract_accuracy": secondary_contract_accuracy,
            "case_count": len(metric_results),
            "strict_secondary_case_count": strict_secondary_cases,
        },
        evaluation_config,
        evaluation_set,
        requires_secondary_evidence=len(coverage_capability_ids) > 1,
        valid_capability_ids=capability_ids,
    )
    report = {
        "run_id": f"eval-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "case_count": len(metric_results),
        "top1_action_accuracy": round(action_accuracy, 4),
        "top1_capability_accuracy": round(primary_matches / total, 4),
        "review_precision": round(review_precision, 4),
        "review_recall": round(review_recall, 4),
        "false_positive_count": sum(1 for result in metric_results if result["expected_action"] != "review" and result["predicted_action"] == "review"),
        "false_negative_count": sum(1 for result in metric_results if result["expected_action"] == "review" and result["predicted_action"] != "review"),
        "capability_count": len(coverage_capability_ids),
        "covered_capability_count": len(coverage_capability_ids & covered_capability_ids),
        "capability_coverage_ratio": round(coverage_ratio, 4),
        "secondary_contract_accuracy": round(secondary_contract_accuracy, 4),
        "strict_secondary_case_count": strict_secondary_cases,
        "uncovered_capabilities": sorted(coverage_capability_ids - covered_capability_ids),
        "per_case_results": results,
        "evaluation_mode": bundle.get("evaluation_set", {}).get("mode", evaluation_config.get("mode", "generated_only")),
        "enforcement_mode": policy_decision.enforcement_mode,
        "status": "pass" if policy_decision.passed else "fail",
        "status_reasons": list(policy_decision.reasons),
    }
    return report


def build_write_ready_router_bundle(
    repo_root: Path,
    *,
    input_mode: str = "preserve_curated",
) -> dict[str, Any]:
    bundle = build_router_bundle(repo_root, input_mode=input_mode)
    bundle["root"] = resolve_bundle_root(repo_root)
    evaluation_summary = evaluate_bundle(bundle, repo_root)
    evaluation_config = bundle.get("config", {}).get("evaluation", {})
    if evaluation_summary.get("status") == "pass":
        evaluation_config["attestation"] = make_evaluation_attestation(
            bundle, evaluation_summary
        )
    else:
        evaluation_config.pop("attestation", None)
    return bundle


def rebuild_index(
    repo_root: Path,
    write_back: bool = False,
    *,
    generated_output_initialization_fingerprint: str | None = None,
) -> dict[str, Any]:
    operations = IndexRebuildOperations(
        resolve_bundle_root=resolve_bundle_root,
        load_bundle=load_bundle,
        load_profile=load_active_profile,
        build_bundle=lambda root, ready: (
            build_write_ready_router_bundle(root)
            if ready
            else build_router_bundle(root)
        ),
        create_bundle_directory=create_bundle_directory,
        write_bundle=write_bundle,
        prepare_preserved_bundle=prepare_router_bundle_for_preserved_write,
        copy_schemas=copy_skill_schemas_to_bundle,
        build_snapshot=build_structure_snapshot,
        ignore_patterns=default_ignore_patterns,
        capability_conflicts=capability_conflicts,
        write_report=write_report,
        report_id=lambda: (
            "rebuild-"
            + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
        ),
        timestamp=iso_now,
    )
    return rebuild_router_index(
        repo_root,
        write_back=write_back,
        operations=operations,
        generated_output_initialization_fingerprint=(
            generated_output_initialization_fingerprint
        ),
    )


def freshness_report(
    repo_root: Path,
    bundle: dict[str, Any],
    changed_paths: Optional[list[str]] = None,
) -> dict[str, Any]:
    bundle_root = bundle.get("root", resolve_bundle_root(repo_root))
    return repository_freshness_report(
        repo_root,
        Path(bundle_root),
        default_ignore_patterns(bundle.get("config", {})),
        changed_paths,
    )


def generate_feedback(bundle_root: Path) -> dict[str, Any]:
    route_dir = bundle_root / "reports" / "route-decisions"
    guardrail_dir = bundle_root / "reports" / "guardrail-results"
    proposals: list[dict[str, Any]] = []
    for report_file in sorted(route_dir.glob("*.json")):
        report = load_json_file(report_file)
        if report.get("review_required"):
            proposals.append(
                {
                    "kind": "routing-review",
                    "decision_id": report.get("decision_id"),
                    "reason": report.get("reasoning", []),
                    "suggestion": "Add or refine capability ownership, keywords, or profile overrides for this route.",
                }
            )
    for report_file in sorted(guardrail_dir.glob("*.json")):
        report = load_json_file(report_file)
        for finding in report.get("findings", []):
            proposals.append(
                {
                    "kind": "guardrail-finding",
                    "rule": finding.get("rule"),
                    "severity": finding.get("severity"),
                    "path": finding.get("path") or finding.get("source_file"),
                    "suggestion": "Promote this rule into the profile, module map, or public API contract.",
                }
            )
    return {
        "report_id": f"feedback-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "proposals": proposals,
        "status": "pass",
    }


def record_manual_feedback(bundle_root: Path, feedback: dict[str, Any]) -> dict[str, Any]:
    feedback_dir = bundle_root / "reports" / "manual-feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_id = feedback.get("feedback_id") or f"feedback-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    authorization_fields = authorization_audit_fields(
        bundle_root,
        feedback,
        load_json_file,
    )
    payload = {
        "feedback_id": feedback_id,
        "timestamp": iso_now(),
        "decision_id": feedback.get("decision_id"),
        "final_action": feedback.get("final_action"),
        "final_capability": feedback.get("final_capability"),
        "notes": feedback.get("notes", ""),
        "confirmed_public_entry": feedback.get("confirmed_public_entry"),
        "confirmed_owner": feedback.get("confirmed_owner"),
        "profile_update_recommended": bool(feedback.get("profile_update_recommended")),
        **authorization_fields,
    }
    dump_json_file(feedback_dir / f"{feedback_id}.json", payload)
    return payload
