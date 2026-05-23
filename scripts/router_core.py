from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import yaml
from jsonschema import Draft202012Validator


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

CODE_SUFFIXES = {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
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
    contracts: list[str] = field(default_factory=list)
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
    repo_stage: str
    action: str
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
    confidence_reasons: list[str]
    veto_reasons: list[str]
    positive_signals: dict[str, Any]
    negative_signals: dict[str, Any]
    risk_signals: dict[str, Any]
    reasoning: list[str]
    source_of_truths: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parent.parent


def profile_dir(skill_root: Optional[Path] = None) -> Path:
    return (skill_root or project_root_from_file()) / "profiles"


def schema_dir(skill_root: Optional[Path] = None) -> Path:
    return (skill_root or project_root_from_file()) / "schemas"


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def dump_yaml_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


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


def glob_match(patterns: Iterable[str], value: str) -> bool:
    normalized = value.replace("\\", "/")
    for pattern in patterns:
        normalized_pattern = pattern.replace("\\", "/")
        if fnmatch.fnmatchcase(normalized, normalized_pattern):
            return True
        if normalized_pattern.endswith("/**"):
            root = normalized_pattern[:-3].rstrip("/")
            if normalized == root or normalized.startswith(root + "/"):
                return True
    return False


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


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            merged = list(result[key])
            for item in value:
                if item not in merged:
                    merged.append(item)
            result[key] = merged
        else:
            result[key] = value
    return result


def profile_candidates(repo_root: Path) -> list[Path]:
    candidates = [
        repo_root / ".project-change-router.yaml",
        repo_root / ".project-change-router.yml",
        repo_root / "project-change-router.profile.yaml",
        repo_root / "project-change-router.profile.yml",
    ]
    skill_profiles = profile_dir()
    if skill_profiles.exists():
        candidates.extend(
            [
                skill_profiles / f"{repo_root.name}.yaml",
                skill_profiles / f"{repo_root.name}.yml",
            ]
        )
    return [path for path in candidates if path.exists()]


def load_active_profile(repo_root: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in profile_candidates(repo_root):
        data = load_yaml_file(path)
        if data:
            merged = deep_merge(merged, data)
    return merged


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


def codeowners_candidates(repo_root: Path) -> list[Path]:
    return [
        repo_root / ".github" / "CODEOWNERS",
        repo_root / ".gitlab" / "CODEOWNERS",
        repo_root / "CODEOWNERS",
    ]


def load_codeowners(repo_root: Path) -> list[tuple[str, list[str]]]:
    for path in codeowners_candidates(repo_root):
        if not path.exists():
            continue
        rules: list[tuple[str, list[str]]] = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            rules.append((parts[0], parts[1:]))
        return rules
    return []


def codeowner_for_path(rel_path: str, rules: list[tuple[str, list[str]]]) -> Optional[str]:
    winner: Optional[str] = None
    normalized = rel_path.replace("\\", "/")
    for pattern, owners in rules:
        normalized_pattern = pattern.lstrip("/").replace("\\", "/")
        if normalized_pattern.endswith("/"):
            normalized_pattern += "*"
        if fnmatch.fnmatchcase(normalized, normalized_pattern) or fnmatch.fnmatchcase("/" + normalized, pattern.replace("\\", "/")):
            if owners:
                winner = ",".join(owners)
    return winner


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


def detect_ci(repo_root: Path) -> bool:
    return any(
        path.exists()
        for path in [
            repo_root / ".github" / "workflows",
            repo_root / ".gitlab-ci.yml",
            repo_root / "azure-pipelines.yml",
            repo_root / ".circleci" / "config.yml",
        ]
    )


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
    has_ci = detect_ci(repo_root)
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
    normalized = path.replace("\\", "/").strip("./")
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
    patterns = [
        r"""import\s+(?:type\s+)?(?:[\w*\s{},]+\s+from\s+)?["']([^"']+)["']""",
        r"""export\s+(?:type\s+)?(?:[\w*\s{},]+\s+from\s+)?["']([^"']+)["']""",
        r"""require\(\s*["']([^"']+)["']\s*\)""",
    ]
    imports: list[str] = []
    for pattern in patterns:
        imports.extend(re.findall(pattern, text))
    return imports


def parse_java_imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return re.findall(r"^\s*import\s+([\w\.]+)\s*;", text, flags=re.M)


def infer_import_reference(name: str, source_module: ModuleEntry, modules: list[ModuleEntry], repo_root: Path, source_file: Path) -> tuple[Optional[ModuleEntry], Optional[str]]:
    if not name:
        return None, None
    normalized = name.replace("\\", "/")
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
    lower = name.lower()
    for module in modules:
        for import_name in public_import_names(module):
            if lower == import_name.lower() or lower.startswith(import_name.lower() + ".") or lower.startswith(import_name.lower() + "/"):
                return module, None
        for prefix in module.lifecycle.get("package_prefixes", []):
            if lower == prefix.lower() or lower.startswith(prefix.lower() + "."):
                return module, None
        if module.path != ".":
            basename = Path(module.path).name.lower()
            if lower == basename or lower.startswith(basename + "/") or f"/{basename}/" in lower:
                return module, None
    return None, None


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
    apply_profile_module_overrides(modules, profile)
    infer_module_dependencies(repo_root, modules, merged_config)
    assign_module_ownership(repo_root, modules, profile)
    for module in modules:
        if not module.allowed_outbound_to:
            module.allowed_outbound_to = sorted(set(module.depends_on))
        module.lifecycle.setdefault("allowed_outbound_layers", infer_allowed_layers(module.layer))
    return modules


def apply_profile_module_overrides(modules: list[ModuleEntry], profile: dict[str, Any]) -> None:
    rules = profile.get("module_overrides", [])
    for module in modules:
        for rule in rules:
            patterns = rule.get("path_patterns", [])
            if patterns and not glob_match(patterns, module.path):
                continue
            if "layer" in rule:
                module.layer = rule["layer"]
            if "domain" in rule:
                module.domain = rule["domain"]
            if "public_api" in rule:
                module.public_api = rule["public_api"]
            if "purpose" in rule:
                module.purpose = rule["purpose"]
            if "owner" in rule:
                module.owner = rule["owner"]
            for key in ("import_names", "package_prefixes", "source_roots"):
                if key in rule:
                    module.lifecycle[key] = list(dict.fromkeys(list(module.lifecycle.get(key, [])) + list(rule[key])))


def infer_module_dependencies(repo_root: Path, modules: list[ModuleEntry], config: dict[str, Any]) -> None:
    ignore_patterns = default_ignore_patterns(config)
    path_lookup = {module.path: module for module in modules}
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if not module_root.exists():
            continue
        deps = set(module.depends_on)
        for source_file in iter_source_files(module_root, ignore_patterns):
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


def assign_module_ownership(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any]) -> None:
    rules = load_codeowners(repo_root)
    for module in modules:
        rel = module.path if module.path != "." else ""
        owner = codeowner_for_path(rel, rules) if rules else None
        if not owner:
            owner = profile_ownership_for_path(module.path, profile)
        if not owner:
            owner = default_owner_name(module)
        module.owner = owner


def infer_public_entries_from_modules(modules: list[ModuleEntry]) -> list[str]:
    entries: list[str] = []
    for module in modules:
        if module.public_api:
            entries.append(f"{module.path}/{module.public_api}" if module.path != "." else module.public_api)
        else:
            entries.extend(module.key_files[:1])
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


def infer_related_tests(repo_root: Path, modules: list[ModuleEntry]) -> list[str]:
    tests: list[str] = []
    candidates = []
    for base in ("tests", "test", "src/test", "src/tests"):
        root = repo_root / base
        if root.exists():
            candidates.extend(root.rglob("*"))
    module_tokens = set()
    for module in modules:
        module_tokens.update(text_tokens(module.domain))
        module_tokens.update(text_tokens(Path(module.path).name))
    for file in candidates:
        if not file.is_file():
            continue
        rel = normalize_rel_path(repo_root, file)
        if any(token and token in rel.lower() for token in module_tokens):
            tests.append(rel)
    return tests[:12]


def generic_capability_id(domain: str) -> str:
    return stable_slug(domain)


def apply_profile_capabilities(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any]) -> tuple[list[CapabilityEntry], set[str]]:
    ignore_patterns = default_ignore_patterns(profile.get("discovery", {}))
    capabilities: list[CapabilityEntry] = []
    consumed_modules: set[str] = set()
    for item in profile.get("capabilities", []):
        patterns = item.get("path_patterns", [])
        matched = [module for module in modules if patterns and glob_match(patterns, module.path)]
        if not matched:
            continue
        consumed_modules.update(module.path for module in matched)
        profile_stage = item.get("stage", "governed-capability" if item.get("status", "stable") == "stable" else "stable")
        profile_status = item.get("status", "stable")
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
                public_entries=list(dict.fromkeys(item.get("public_entries", []) + infer_public_entries_from_modules(matched))),
                extension_points=list(dict.fromkeys(item.get("extension_points", []) + infer_extension_points(repo_root, matched, ignore_patterns))),
                route_defaults=item.get("route_defaults", {"preferred_action": "reuse"}),
                contracts=item.get("contracts", []),
                related_tests=list(dict.fromkeys(item.get("related_tests", []) + infer_related_tests(repo_root, matched))),
                test_bindings=item.get("test_bindings", []),
                forbidden_patterns=item.get("forbidden_patterns", []),
                dependent_modules=[],
                anti_patterns=item.get("anti_patterns", []),
                lifecycle={
                    "profile_id": profile.get("profile_id"),
                    "public_entry_semantics": public_entry_semantics(
                        list(dict.fromkeys(item.get("public_entries", []) + infer_public_entries_from_modules(matched))),
                        "governed",
                        True,
                    ),
                },
                last_verified_at=today_date(),
            )
        )
    return capabilities, consumed_modules


def infer_capabilities_from_modules(repo_root: Path, modules: list[ModuleEntry], profile: dict[str, Any], repo_stage: str, feedback_items: Optional[list[dict[str, Any]]] = None) -> list[CapabilityEntry]:
    feedback_items = feedback_items or []
    feedback_meta = feedback_summary(feedback_items)
    confirmation_counts = feedback_meta["capability_confirmation_counts"]
    profile_caps, consumed = apply_profile_capabilities(repo_root, modules, profile)
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
        domain = grouped_modules[0].domain
        public_entries = infer_public_entries_from_modules(grouped_modules)
        extension_points = infer_extension_points(repo_root, grouped_modules, ignore_patterns)
        related_tests = infer_related_tests(repo_root, grouped_modules)
        dependent_modules: set[str] = set()
        for module in grouped_modules:
            dependent_modules.update(reverse_deps.get(module.path, []))
        flat_keywords: list[str] = [domain]
        for module in grouped_modules:
            flat_keywords.append(Path(module.path).name.replace("-", " "))
            flat_keywords.append(module.domain)
            flat_keywords.extend(public_import_names(module))
        keywords = sorted({keyword for keyword in flat_keywords if keyword})
        stage, maturity = capability_stage_for_generated(grouped_modules, public_entries, repo_stage)
        confirmation_count = int(confirmation_counts.get(cap_id, 0))
        if stage == "provisional" and confirmation_count >= 1 and repo_stage in {"emerging", "structured", "governed"}:
            stage, maturity = "candidate", "candidate"
        if stage == "candidate" and confirmation_count >= 2 and repo_stage in {"structured", "governed"}:
            stage, maturity = "stable", "stable"
        status = "stable" if stage in {"stable", "governed-capability"} else "candidate"
        capabilities.append(
            CapabilityEntry(
                id=cap_id,
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
                        "id": f"tests-{cap_id}",
                        "label": f"Run tests related to {cap_id}",
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
                    "public_entry_semantics": public_entry_semantics(public_entries, repo_stage, False),
                    "confirmation_count": confirmation_count,
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


def build_ownership(capabilities: list[CapabilityEntry], modules: list[ModuleEntry], repo_stage: str) -> dict[str, Any]:
    owners: list[dict[str, Any]] = []
    for capability in capabilities:
        primary = modules[0].owner if modules else "unassigned"
        for module in modules:
            if module.path in capability.owner_modules:
                primary = module.owner
                break
        owners.append(
            {
                "scope": "capability",
                "target": capability.id,
                "primary": primary,
                "reviewers": [primary],
                "escalation_group": primary,
                "provisional": repo_stage in {"seed", "emerging"} or primary == "unassigned" or str(primary).startswith("provisional:"),
            }
        )
    for module in modules:
        owners.append(
            {
                "scope": "module",
                "target": module.path,
                "primary": module.owner,
                "reviewers": [module.owner],
                "escalation_group": module.owner,
                "provisional": repo_stage in {"seed", "emerging"} or module.owner == "unassigned" or str(module.owner).startswith("provisional:"),
            }
        )
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "owners": owners,
    }


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
            "top1_accuracy_threshold": 0.80,
            "review_precision_threshold": 0.90,
            "minimum_case_count": 12,
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
    for capability in stable_caps[:10]:
        is_stable = capability.stage in {"stable", "governed-capability"} or capability.status == "stable"
        is_risky = match_strength(capability.id, DEFAULT_HIGH_RISK_KEYWORDS) >= 1.0
        can_extract = is_stable and len(capability.owner_modules) >= 2
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
    for capability in stable_caps[:5]:
        if len(capability.owner_modules) >= 2:
            changed = capability.owner_modules[:2]
        else:
            changed = capability.owner_modules[:1]
        cases.append(
            {
                "id": f"{capability.id}-extract",
                "request": f"Extract repeated {capability.name.lower()} logic into a shared reusable entry point.",
                "expected_action": "extract" if can_extract and not match_strength(capability.id, DEFAULT_HIGH_RISK_KEYWORDS) >= 1.0 and repo_stage in {"structured", "governed"} else "review",
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
        "cases": cases,
    }


def merge_curated_evaluation(existing: dict[str, Any], generated: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    profile_eval = profile.get("evaluation", {})
    curated_cases = list(profile_eval.get("cases", []))
    if existing.get("mode") == "curated":
        curated_cases.extend(existing.get("cases", []))
    if profile_eval.get("mode") == "curated":
        mode = "curated"
    elif curated_cases:
        mode = "hybrid"
    else:
        mode = generated.get("mode", "generated_only")
    merged = dict(generated)
    merged["mode"] = mode
    if curated_cases:
        seen: set[str] = set()
        ordered_cases = []
        for case in curated_cases + generated.get("cases", []):
            case_id = str(case.get("id"))
            if case_id in seen:
                continue
            seen.add(case_id)
            ordered_cases.append(case)
        merged["cases"] = ordered_cases
    return merged


def capability_conflicts(bundle: dict[str, Any]) -> list[str]:
    conflicts: list[str] = []
    owner_to_caps: dict[str, list[str]] = defaultdict(list)
    public_entry_to_caps: dict[str, list[str]] = defaultdict(list)
    for capability in capability_entries(bundle):
        for owner in capability.owner_modules:
            owner_to_caps[owner].append(capability.id)
        for entry in capability.public_entries:
            public_entry_to_caps[entry].append(capability.id)
    for owner, caps in owner_to_caps.items():
        unique = sorted(set(caps))
        if len(unique) > 1:
            conflicts.append(f"module {owner} is owned by multiple capabilities: {', '.join(unique)}")
    for entry, caps in public_entry_to_caps.items():
        unique = sorted(set(caps))
        if len(unique) > 1:
            conflicts.append(f"public entry {entry} is claimed by multiple capabilities: {', '.join(unique)}")
    return conflicts


def build_router_bundle(repo_root: Path) -> dict[str, Any]:
    profile = load_active_profile(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    feedback_items = load_manual_feedback(bundle_root)
    existing_bundle = load_bundle(bundle_root) if bundle_root.exists() else {}
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
    ownership = build_ownership(capabilities, modules, repo_stage)
    change_rules = build_change_rules(capabilities, profile, repo_stage)
    exception_registry = build_exception_registry(repo_root, profile)
    generated_evaluation = build_evaluation_set(capabilities, module_map, repo_stage)
    evaluation_set = merge_curated_evaluation(existing_bundle.get("evaluation_set", {}), generated_evaluation, profile)
    bundle = {
        "config": config,
        "module_map": module_map,
        "capability_catalog": capability_catalog,
        "ownership": ownership,
        "change_rules": change_rules,
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


def parse_request_type(request_text: str) -> str:
    text = request_text.lower()
    if any(word in text for word in ("bug", "fix", "repair", "regression", "修复", "修正")):
        return "bug-fix"
    if any(word in text for word in ("refactor", "extract", "cleanup", "重构", "抽取")):
        return "refactor"
    if any(word in text for word in ("migrate", "migration", "升级", "迁移")):
        return "migration"
    if any(word in text for word in ("add", "new", "create", "introduce", "新增", "创建", "引入")):
        return "feature-addition"
    return "feature-modification"


def request_duplicate_signal(request_text: str, changed_paths: Iterable[str]) -> tuple[bool, int]:
    text = request_text.lower()
    words = ("extract", "duplicate", "shared", "common", "重复", "抽取", "复用", "共享")
    count = 0
    if any(word in text for word in words):
        count += 1
    normalized_paths = [path.replace("\\", "/") for path in changed_paths]
    top_level = {item.split("/")[0] for item in normalized_paths if item}
    if len(top_level) > 1:
        count += 1
    if len(normalized_paths) >= 2:
        count += 1
    return count >= 2, count


def request_high_risk(request_text: str, changed_paths: Iterable[str], modules: list[ModuleEntry], bundle: dict[str, Any]) -> bool:
    text = request_text.lower()
    rules = bundle.get("change_rules", {})
    keywords = list(dict.fromkeys(DEFAULT_HIGH_RISK_KEYWORDS + bundle.get("config", {}).get("high_risk_keywords", [])))
    if any(keyword in text for keyword in keywords):
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


def request_targets_existing_capability(request_text: str) -> bool:
    text = request_text.lower()
    negative_patterns = (
        "no existing",
        "not existing",
        "without existing",
        "does not map to any existing",
        "doesn't map to any existing",
        "不存在现有",
        "没有现有",
        "不属于现有",
    )
    if any(pattern in text for pattern in negative_patterns):
        return False
    phrases = (
        "existing",
        "reuse",
        "extend",
        "current",
        "already",
        "现有",
        "已有",
        "复用",
        "扩展",
    )
    return any(phrase in text for phrase in phrases)


def request_prefers_extract(request_text: str) -> bool:
    text = request_text.lower()
    phrases = (
        "extract",
        "duplicate",
        "shared",
        "common",
        "重复",
        "抽取",
        "复用",
        "共享",
    )
    return any(phrase in text for phrase in phrases)


def request_requires_review(request_text: str) -> bool:
    text = request_text.lower()
    phrases = (
        "review",
        "ambiguous",
        "unclear",
        "cross-cutting",
        "manual",
        "broad",
        "审查",
        "模糊",
        "不明确",
        "跨模块",
    )
    return any(phrase in text for phrase in phrases)


def module_path_proximity(capability: CapabilityEntry, changed_paths: list[str]) -> float:
    owner_paths = {path.replace("\\", "/").lower() for path in capability.owner_modules}
    if not owner_paths or not changed_paths:
        return 0.0
    hits = 0
    for path in changed_paths:
        normalized = path.replace("\\", "/").lower()
        if any(normalized == owner or normalized.startswith(owner.rstrip("/") + "/") for owner in owner_paths):
            hits += 1
    return hits / max(1, len(changed_paths))


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
    positive["path_proximity"] = round(module_path_proximity(capability, changed_paths), 4)
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
    risk["keyword_hit"] = any(keyword in request_text.lower() for keyword in risk_keywords)
    risk["high_risk_capability"] = capability.id in set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    risk["repo_stage"] = bundle.get("config", {}).get("repo_stage")
    risk["request_requires_review"] = request_requires_review(request_text)
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
    path_proximity = module_path_proximity(capability, changed_paths)
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
    paths: list[str] = []
    if capability:
        paths.extend(capability.public_entries[:4])
        for owner in capability.owner_modules:
            module = next((item for item in modules if item.path == owner), None)
            if module:
                if module.public_api:
                    paths.append(f"{module.path}/{module.public_api}" if module.path != "." else module.public_api)
                paths.extend(
                    f"{module.path}/{key}" if module.path != "." else key
                    for key in module.key_files[:2]
                )
    for path in changed_paths[:2]:
        module = module_for_path(path, modules)
        if module and module.public_api:
            paths.append(f"{module.path}/{module.public_api}" if module.path != "." else module.public_api)
    dedup: list[str] = []
    for item in paths:
        normalized = item.replace("\\", "/")
        if normalized not in dedup:
            dedup.append(normalized)
    return dedup[:8]


def required_checks_for(capability: Optional[CapabilityEntry], action: str, bundle: dict[str, Any]) -> list[str]:
    checks = ["check-reuse", "check-deps", "check-public-api", "check-index-freshness"]
    if capability:
        for binding in capability.test_bindings:
            if action in binding.get("when_actions", []):
                checks.append(binding["id"])
    return list(dict.fromkeys(checks))


def forbidden_paths_for(capability: Optional[CapabilityEntry], bundle: dict[str, Any]) -> list[str]:
    if not capability:
        return []
    return list(dict.fromkeys(capability.forbidden_patterns))


def bundle_stale(bundle_root: Path, bundle: dict[str, Any]) -> bool:
    if not bundle_root.exists():
        return True
    config = bundle.get("config", {})
    threshold = int(config.get("freshness_windows", {}).get("module_map_days", 30))
    marker = bundle_root / "references" / "module-map.yaml"
    if not marker.exists():
        return True
    modified = dt.datetime.fromtimestamp(marker.stat().st_mtime, tz=dt.timezone.utc).date()
    return (dt.datetime.now(dt.timezone.utc).date() - modified).days > threshold


def build_route_report(decision: RouteDecision) -> dict[str, Any]:
    return decision.to_dict()


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
    sorted_scores = sorted(route_scores, key=lambda item: item[1], reverse=True)
    best_cap, best_score, _ = sorted_scores[0]
    best_signals = sorted_scores[0][2]
    confidence_level = confidence_level_for(best_score)
    second_score = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    ov = overlap_score(best_score, second_score)
    threshold = bundle.get("change_rules", {}).get("confidence", {})
    auto_threshold = float(threshold.get("auto_route_threshold", 0.78))
    guarded_threshold = float(threshold.get("guarded_route_threshold", 0.58))
    repo_stage = bundle.get("config", {}).get("repo_stage", "emerging")
    duplicate_signal, duplicate_count = request_duplicate_signal(request_text, changed_paths)
    request_has_change_verb = any(word in request_text.lower() for word in CHANGE_VERBS)
    stable_candidates = [
        cap
        for cap, score, _ in sorted_scores
        if score >= guarded_threshold and (cap.stage in {"stable", "governed-capability"} or cap.status == "stable")
    ]
    coordination_required = len(stable_candidates) > 1
    composite_required = len({module.path for module in changed_modules}) > 1 and coordination_required
    secondary = [cap.id for cap, score, _ in sorted_scores[1:] if score >= guarded_threshold]
    high_risk_ids = set(bundle.get("change_rules", {}).get("high_risk_capability_ids", []))
    stale_bundle = bundle.get("_runtime", {}).get("stale_bundle", False)
    has_conflict = bundle.get("_runtime", {}).get("has_conflict", False)
    targets_existing = request_targets_existing_capability(request_text)
    extract_intent = request_prefers_extract(request_text)
    explicit_review = request_requires_review(request_text)

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

    if high_risk and (best_cap.id in high_risk_ids or ov >= 0.75):
        reasoning.append("high-risk request requires manual review")
        veto_reasons.append("high-risk capability or overlapping high-risk candidates")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if stale_bundle or has_conflict:
        reasoning.append("routing bundle is stale or internally inconsistent")
        veto_reasons.append("bundle is stale or conflicts exist")
        return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if repo_stage == "seed":
        if not changed_paths and not targets_existing:
            reasoning.append("seed-stage repository defaults to new capability suggestions")
            confidence_reasons.append("seed-stage repositories do not trust auto-reuse without changed surfaces")
            return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("seed-stage repository does not auto-route into existing capability boundaries")
        veto_reasons.append("repo_stage=seed blocks auto-route into existing boundaries")
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
    if repo_stage == "emerging" and best_cap.stage == "provisional":
        if not changed_paths and not targets_existing:
            reasoning.append("emerging repository avoids promoting provisional capability guesses into new boundaries")
            confidence_reasons.append("provisional capability lacks enough structure evidence")
            return "new", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("emerging repository treats provisional capabilities as review-only")
        veto_reasons.append("repo_stage=emerging blocks auto-routing to provisional capability")
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
    if duplicate_signal and duplicate_count >= 2 and (
        len(changed_paths) >= 2 or len({module.path for module in changed_modules}) >= 2
    ):
        if repo_stage in {"seed", "emerging"}:
            reasoning.append("early-stage repository defers duplicate extraction to manual review")
            veto_reasons.append("duplicate-based extract is blocked in early-stage repositories")
            return "review", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
        reasoning.append("duplicate signal indicates shared extraction work")
        return "extract", best_cap, secondary, best_score, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons
    if ov >= 0.82:
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


def resolve_request(request_text: str, changed_paths: list[str], bundle: dict[str, Any], bundle_root: Path) -> RouteDecision:
    capabilities = capability_entries(bundle)
    modules = module_entries(bundle)
    normalized_changed_paths = [path.replace("\\", "/") for path in changed_paths]
    changed_modules = [module_for_path(path, modules) for path in normalized_changed_paths]
    changed_modules = [module for module in changed_modules if module is not None]
    high_risk = request_high_risk(request_text, normalized_changed_paths, modules, bundle)
    route_scores: list[tuple[CapabilityEntry, float, dict[str, float]]] = []
    for capability in capabilities:
        score, signals = capability_score(request_text, capability, changed_modules, normalized_changed_paths, bundle)
        if score > 0.0 or capability.status == "stable":
            route_scores.append((capability, score, signals))
    bundle["_runtime"] = {
        "stale_bundle": bundle_stale(bundle_root, bundle),
        "has_conflict": bool(capability_conflicts(bundle)),
    }
    action, primary_capability, secondary_capabilities, confidence, confidence_level, ov, coordination_required, composite_required, reasoning, confidence_reasons, veto_reasons = determine_action(
        request_text,
        normalized_changed_paths,
        changed_modules,
        route_scores,
        high_risk,
        bundle,
    )
    sorted_scores = sorted(route_scores, key=lambda item: item[1], reverse=True)
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
    required_checks = required_checks_for(primary_capability, action, bundle)
    forbidden_paths = forbidden_paths_for(primary_capability, bundle)
    decision_id = f"route-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1((request_text + '|' + '|'.join(normalized_changed_paths)).encode('utf-8')).hexdigest()[:8]}"
    positive_signals = best_signals.get("positive_signals", {}) if route_scores else {}
    negative_signals = best_signals.get("negative_signals", {}) if route_scores else {}
    risk_signals = best_signals.get("risk_signals", {}) if route_scores else {}
    return RouteDecision(
        decision_id=decision_id,
        timestamp=iso_now(),
        request_type=parse_request_type(request_text),
        request_summary=request_text.strip().splitlines()[0][:180] if request_text.strip() else "",
        repo_stage=bundle.get("config", {}).get("repo_stage", "emerging"),
        action=action,
        confidence=round(confidence, 4),
        confidence_level=confidence_level,
        overlap_score=round(ov, 4),
        primary_capability=primary_capability.id if primary_capability else None,
        primary_capability_stage=primary_capability.stage if primary_capability else None,
        secondary_capabilities=secondary_capabilities,
        candidate_capabilities=candidate_capabilities,
        candidate_modules=candidate_modules,
        required_reads=required_reads,
        required_checks=required_checks,
        forbidden_paths=forbidden_paths,
        review_required=action == "review",
        coordination_required=coordination_required,
        composite_route_required=composite_required,
        confidence_reasons=confidence_reasons,
        veto_reasons=veto_reasons,
        positive_signals=positive_signals,
        negative_signals=negative_signals,
        risk_signals=risk_signals,
        reasoning=reasoning,
        source_of_truths={
            "capability_catalog": source_of_truth_for(bundle, "capability"),
            "module_map": source_of_truth_for(bundle, "module"),
            "exception_registry": source_of_truth_for(bundle, "exception"),
        },
    )


def normalized_code(text: str) -> str:
    text = re.sub(r"//.*?$|/\*.*?\*/|#.*?$", " ", text, flags=re.M | re.S)
    string_pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''  # noqa: W605
    text = re.sub(string_pattern, '"STR"', text)
    text = re.sub(r"\b\d+(\.\d+)?\b", "NUM", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def similarity(a: Path, b: Path) -> float:
    a_text = normalized_code(a.read_text(encoding="utf-8", errors="ignore"))
    b_text = normalized_code(b.read_text(encoding="utf-8", errors="ignore"))
    return difflib.SequenceMatcher(None, a_text, b_text).ratio()


def matches_dependency(source: ModuleEntry, target: ModuleEntry) -> bool:
    allowed_paths = [pattern.replace("\\", "/") for pattern in source.allowed_outbound_to]
    if target.path in source.depends_on:
        return True
    if allowed_paths and glob_match(allowed_paths, target.path):
        return True
    allowed_layers = source.lifecycle.get("allowed_outbound_layers", [])
    return target.layer in allowed_layers


def gather_dependency_findings(repo_root: Path, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    findings: list[dict[str, Any]] = []
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if not module_root.exists():
            continue
        for source_file in iter_source_files(module_root, ignore_patterns):
            if source_file.suffix.lower() not in CODE_SUFFIXES:
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
                if not target or target.path == module.path:
                    continue
                if not matches_dependency(module, target):
                    findings.append(
                        {
                            "severity": "P1",
                            "rule": "dependency-direction",
                            "source_file": normalize_rel_path(repo_root, source_file),
                            "source_module": module.path,
                            "target_module": target.path,
                            "import": imp,
                            "message": f"{module.path} imports {target.path} outside its allowed dependency surface",
                        }
                    )
    return findings


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
    findings: list[dict[str, Any]] = []
    for module in modules:
        module_root = repo_root / module.path if module.path != "." else repo_root
        if not module_root.exists():
            continue
        for source_file in iter_source_files(module_root, ignore_patterns):
            if source_file.suffix.lower() not in CODE_SUFFIXES:
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
                target, resolved_path = infer_import_reference(imp, module, modules, repo_root, source_file)
                if not target or target.path == module.path:
                    continue
                if target.public_api and not import_matches_public_surface(imp, target, resolved_path):
                    findings.append(
                        {
                            "severity": "P1" if import_reaches_private_surface(imp, resolved_path) else "P2",
                            "rule": "public-api-bypass",
                            "source_file": normalize_rel_path(repo_root, source_file),
                            "source_module": module.path,
                            "target_module": target.path,
                            "import": imp,
                            "message": f"{module.path} reaches {target.path} through a non-public import path",
                        }
                    )
    return findings


def gather_reuse_findings(repo_root: Path, bundle: dict[str, Any], changed_paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    capabilities = capability_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    candidate_files = source_files_for_modules(repo_root, modules, ignore_patterns)
    if changed_paths:
        normalized_paths = [item.replace("\\", "/") for item in changed_paths]
        filtered = []
        for file in candidate_files:
            rel = normalize_rel_path(repo_root, file)
            if any(rel == path or rel.startswith(path.rstrip("/") + "/") for path in normalized_paths):
                filtered.append(file)
        if filtered:
            candidate_files = filtered
    findings: list[dict[str, Any]] = []
    owner_file_cache: dict[str, list[Path]] = {}
    for capability in capabilities:
        for pattern in capability.forbidden_patterns:
            for file in candidate_files:
                rel = normalize_rel_path(repo_root, file)
                if fnmatch.fnmatchcase(rel, pattern.replace("\\", "/")):
                    findings.append(
                        {
                            "severity": "P0",
                            "rule": "forbidden-pattern",
                            "path": rel,
                            "capability": capability.id,
                            "message": f"{rel} matches a forbidden path pattern for {capability.id}",
                        }
                    )
        if not capability.owner_modules:
            continue
        if capability.id not in owner_file_cache:
            owner_files: list[Path] = []
            for owner in capability.owner_modules:
                module = next((item for item in modules if item.path == owner), None)
                if not module:
                    continue
                owner_root = repo_root / module.path if module.path != "." else repo_root
                owner_files.extend([file for file in iter_source_files(owner_root, ignore_patterns) if file.suffix.lower() in CODE_SUFFIXES])
            owner_file_cache[capability.id] = owner_files
        owner_files = owner_file_cache[capability.id]
        for owner_file in owner_files:
            owner_module = module_for_path(normalize_rel_path(repo_root, owner_file), modules)
            for candidate in candidate_files:
                if candidate == owner_file or candidate.suffix.lower() != owner_file.suffix.lower():
                    continue
                candidate_module = module_for_path(normalize_rel_path(repo_root, candidate), modules)
                if candidate_module and owner_module and candidate_module.path == owner_module.path:
                    continue
                score = similarity(owner_file, candidate)
                if score < 0.85:
                    continue
                findings.append(
                    {
                        "severity": "P1" if score >= 0.92 else "P2",
                        "rule": "duplicate-implementation",
                        "path": normalize_rel_path(repo_root, candidate),
                        "capability": capability.id,
                        "score": round(score, 4),
                        "message": f"duplicate implementation signal for {capability.id}",
                    }
                )
    return findings


def bundle_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    config = bundle.get("config", {})
    return {
        "repo_id": config.get("repo_id"),
        "repositories": config.get("repositories", []),
        "protected_branch_patterns": config.get("protected_branch_patterns", []),
        "freshness_windows": config.get("freshness_windows", {}),
    }


def write_bundle(bundle_root: Path, bundle: dict[str, Any]) -> None:
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "references").mkdir(parents=True, exist_ok=True)
    (bundle_root / "schemas").mkdir(parents=True, exist_ok=True)
    (bundle_root / "reports" / "route-decisions").mkdir(parents=True, exist_ok=True)
    (bundle_root / "reports" / "index-rebuild").mkdir(parents=True, exist_ok=True)
    (bundle_root / "reports" / "guardrail-results").mkdir(parents=True, exist_ok=True)
    (bundle_root / "reports" / "evaluation").mkdir(parents=True, exist_ok=True)
    dump_yaml_file(bundle_root / "router-config.yaml", bundle["config"])
    dump_yaml_file(bundle_root / "references" / "capability-catalog.yaml", bundle["capability_catalog"])
    dump_yaml_file(bundle_root / "references" / "module-map.yaml", bundle["module_map"])
    dump_yaml_file(bundle_root / "references" / "ownership.yaml", bundle["ownership"])
    dump_yaml_file(bundle_root / "references" / "change-rules.yaml", bundle["change_rules"])
    dump_yaml_file(bundle_root / "references" / "exception-registry.yaml", bundle["exception_registry"])
    dump_yaml_file(bundle_root / "references" / "evaluation-set.yaml", bundle["evaluation_set"])


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
        shutil.copy2(schema_file, target / schema_file.name)


def clear_core_reference_files(bundle_root: Path) -> None:
    for rel in [
        "router-config.yaml",
        "references/capability-catalog.yaml",
        "references/module-map.yaml",
        "references/ownership.yaml",
        "references/change-rules.yaml",
        "references/exception-registry.yaml",
        "references/evaluation-set.yaml",
    ]:
        path = bundle_root / rel
        if path.exists():
            path.unlink()


def bootstrap_bundle(repo_root: Path, write: bool = True) -> dict[str, Any]:
    bundle = build_router_bundle(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    bundle["root"] = bundle_root
    if write:
        create_bundle_directory(repo_root)
        clear_core_reference_files(bundle_root)
        write_bundle(bundle_root, bundle)
        copy_skill_schemas_to_bundle(bundle_root)
    return bundle


def write_report(path: Path, report: dict[str, Any]) -> None:
    dump_json_file(path, report)


def locate_bundle_or_raise(repo_root: Path) -> Path:
    bundle_root = resolve_bundle_root(repo_root)
    if not bundle_root.exists():
        raise FileNotFoundError(f"project-change-router bundle not found at {bundle_root}")
    return bundle_root


def evaluate_bundle(bundle: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    evaluations = bundle.get("evaluation_set", {}).get("cases", [])
    results = []
    action_matches = 0
    primary_matches = 0
    review_expected = 0
    review_predicted = 0
    for case in evaluations:
        decision = resolve_request(case["request"], case.get("changed_paths", []), bundle, bundle.get("root", resolve_bundle_root(repo_root)))
        action_ok = decision.action == case["expected_action"]
        primary_ok = not case.get("expected_capabilities") or decision.primary_capability in case["expected_capabilities"]
        action_matches += 1 if action_ok else 0
        primary_matches += 1 if primary_ok else 0
        review_expected += 1 if case["expected_action"] == "review" else 0
        review_predicted += 1 if decision.action == "review" else 0
        results.append(
            {
                "id": case["id"],
                "expected_action": case["expected_action"],
                "predicted_action": decision.action,
                "expected_capabilities": case.get("expected_capabilities", []),
                "predicted_capability": decision.primary_capability,
                "action_ok": action_ok,
                "primary_ok": primary_ok,
            }
        )
    total = max(1, len(evaluations))
    review_hits = sum(1 for result in results if result["expected_action"] == "review" and result["predicted_action"] == "review")
    report = {
        "run_id": f"eval-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "case_count": len(evaluations),
        "top1_action_accuracy": round(action_matches / total, 4),
        "top1_capability_accuracy": round(primary_matches / total, 4),
        "review_precision": round(review_hits / max(1, review_predicted), 4),
        "review_recall": round(review_hits / max(1, review_expected), 4),
        "false_positive_count": sum(1 for result in results if result["expected_action"] != "review" and result["predicted_action"] == "review"),
        "false_negative_count": sum(1 for result in results if result["expected_action"] == "review" and result["predicted_action"] != "review"),
        "per_case_results": results,
        "evaluation_mode": bundle.get("evaluation_set", {}).get("mode", bundle.get("config", {}).get("evaluation", {}).get("mode", "generated_only")),
        "status": "pass" if (action_matches / total) >= bundle.get("config", {}).get("evaluation", {}).get("top1_accuracy_threshold", 0.80) else "fail",
    }
    return report


def rebuild_index(repo_root: Path, write_back: bool = False) -> dict[str, Any]:
    bundle_root = resolve_bundle_root(repo_root)
    existing = load_bundle(bundle_root) if bundle_root.exists() else {}
    rebuilt = build_router_bundle(repo_root)
    rebuilt["root"] = bundle_root
    existing_modules = {item["path"] for item in existing.get("module_map", {}).get("modules", [])}
    new_modules = {item["path"] for item in rebuilt["module_map"]["modules"]}
    stale_entries = [{"path": path, "kind": "module"} for path in sorted(existing_modules - new_modules)]
    missing_paths = [item["path"] for item in rebuilt["module_map"]["modules"] if not (repo_root / item["path"]).exists() and item["path"] != "."]
    report = {
        "report_id": f"rebuild-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "source_commit": current_git_commit(repo_root),
        "generated_modules_count": len(rebuilt["module_map"]["modules"]),
        "curated_entries_count": len(rebuilt["capability_catalog"]["capabilities"]),
        "conflicts": capability_conflicts(rebuilt),
        "stale_entries": stale_entries,
        "missing_paths": missing_paths,
        "status": "pass" if not missing_paths and not capability_conflicts(rebuilt) else "fail",
    }
    if write_back:
        create_bundle_directory(repo_root)
        write_bundle(bundle_root, rebuilt)
        copy_skill_schemas_to_bundle(bundle_root)
        write_report(bundle_root / "reports" / "index-rebuild" / "latest.json", report)
    return report


def freshness_report(repo_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    bundle_root = bundle.get("root", resolve_bundle_root(repo_root))
    if not bundle_root.exists():
        return {
            "report_id": f"freshness-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "timestamp": iso_now(),
            "status": "fail",
            "checks": [],
            "missing_references": ["project-change-router/router-config.yaml"],
        }
    freshness = bundle.get("config", {}).get("freshness_windows", {})
    checks = []
    for key, rel in [
        ("capability_catalog_days", "references/capability-catalog.yaml"),
        ("module_map_days", "references/module-map.yaml"),
        ("exception_registry_days", "references/exception-registry.yaml"),
        ("evaluation_set_days", "references/evaluation-set.yaml"),
    ]:
        path = bundle_root / rel
        if not path.exists():
            checks.append({"item": rel, "fresh": False, "reason": "missing file"})
            continue
        age_days = (dt.datetime.now(dt.timezone.utc).date() - dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).date()).days
        checks.append({"item": rel, "fresh": age_days <= int(freshness.get(key, 30)), "age_days": age_days, "threshold_days": int(freshness.get(key, 30))})
    missing_references = []
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        for path in capability.get("owner_modules", []):
            if path != "." and not (repo_root / path).exists():
                missing_references.append(path)
        owner_roots = capability.get("owner_modules", [])
        for public_entry in capability.get("public_entries", []):
            normalized = public_entry.replace("\\", "/")
            candidate_paths: list[Path] = [repo_root / normalized]
            for owner_root in owner_roots:
                owner_normalized = owner_root.replace("\\", "/")
                if owner_normalized == ".":
                    candidate_paths.append(repo_root / normalized)
                elif not normalized.startswith(owner_normalized.rstrip("/") + "/"):
                    candidate_paths.append(repo_root / owner_normalized / normalized)
            if not any(candidate.exists() for candidate in candidate_paths):
                missing_references.append(public_entry)
    return {
        "report_id": f"freshness-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "status": "pass" if all(item.get("fresh", False) for item in checks) and not missing_references else "fail",
        "checks": checks,
        "missing_references": sorted(set(missing_references)),
    }


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
    }
    dump_json_file(feedback_dir / f"{feedback_id}.json", payload)
    return payload
