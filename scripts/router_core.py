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
import sys
import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import yaml
from jsonschema import Draft202012Validator


SHEBANG = "#!/usr/bin/env python3"
DEFAULT_IGNORE_GLOBS = [
    "**/.git/**",
    "**/.idea/**",
    "**/.mvn/**",
    "**/.maven/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/build/**",
    "**/target/**",
    "**/coverage/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/*.class",
    "**/*.log",
]

HIGH_RISK_KEYWORDS = [
    "auth",
    "authentication",
    "authorization",
    "jws",
    "jwks",
    "security",
    "billing",
    "payment",
    "invoice",
    "subscription",
    "entitlement",
    "quota",
    "gateway",
    "tenant",
    "workspace",
    "schema",
    "migration",
    "webhook",
    "token",
    "principal",
]


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
    action: str
    confidence: float
    overlap_score: float
    primary_capability: Optional[str]
    secondary_capabilities: list[str]
    candidate_capabilities: list[dict[str, Any]]
    candidate_modules: list[dict[str, Any]]
    required_reads: list[str]
    required_checks: list[str]
    forbidden_paths: list[str]
    review_required: bool
    coordination_required: bool
    composite_route_required: bool
    reasoning: list[str]
    source_of_truths: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def project_root_from_file() -> Path:
    return Path(__file__).resolve().parent.parent


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
    return Path(path).resolve().relative_to(root.resolve()).as_posix()


def glob_match(patterns: Iterable[str], value: str) -> bool:
    normalized = value.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern.replace("\\", "/")) for pattern in patterns)


def text_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z_\u4e00-\u9fff]+", text.lower()) if token]


def text_contains_any(text: str, keywords: Iterable[str]) -> bool:
    haystack = text.lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def match_strength(text: str, keywords: Iterable[str]) -> float:
    lower = text.lower()
    score = 0.0
    for keyword in keywords:
        k = keyword.lower()
        if not k:
            continue
        if k in lower:
            return 1.0
        if any(part and part in lower for part in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", k)):
            score = max(score, 0.5)
    return score


def stable_slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "item"


def file_suffix_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    if suffix == ".java":
        return "java"
    return "text"


def default_ignore_patterns(config: dict[str, Any]) -> list[str]:
    patterns = list(DEFAULT_IGNORE_GLOBS)
    patterns.extend(config.get("ignore_paths", []))
    return patterns


def should_ignore_path(path: Path, ignore_patterns: Iterable[str], root: Path) -> bool:
    rel = normalize_rel_path(root, path)
    return glob_match(ignore_patterns, rel)


def iter_source_files(root: Path, ignore_patterns: Iterable[str]) -> Iterator[Path]:
    for base, dirs, files in os.walk(root):
        base_path = Path(base)
        dirs[:] = [
            d for d in dirs if not should_ignore_path(base_path / d, ignore_patterns, root)
        ]
        for filename in files:
            path = base_path / filename
            if should_ignore_path(path, ignore_patterns, root):
                continue
            if path.suffix.lower() in {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".xml"}:
                yield path


def repo_root_from(start: Path | str | None = None) -> Path:
    current = Path(start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "project-change-router" / "router-config.yaml").exists():
            return candidate
        if (candidate / "pom.xml").exists() or (candidate / "package.json").exists() or (candidate / "app").exists():
            return candidate
    return current


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


def resolve_bundle_root(repo_root: Path) -> Path:
    return repo_root / "project-change-router"


def schema_dir(skill_root: Optional[Path] = None) -> Path:
    skill_root = skill_root or project_root_from_file()
    return skill_root / "schemas"


def validate_against_schema(data: dict[str, Any], schema_path: Path) -> list[str]:
    schema = load_json_file(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    return [f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}" for error in errors]


def validate_bundle(bundle_root: Path, skill_root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    skill_root = skill_root or project_root_from_file()
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
        errors.extend([f"{file_path.name}: {msg}" for msg in validate_against_schema(load_yaml_file(file_path), schema_path)])

    return errors


def java_package_prefix(module_path: str) -> str:
    tail = Path(module_path).name
    tail = tail.replace("-", ".")
    if tail.startswith("sdk."):
        return "com.saas.sdk"
    if tail == "saas-app":
        return "com.saas.app"
    if tail.startswith("saas-"):
        tail = tail[len("saas-") :]
    return f"com.saas.{tail.replace('-', '.')}"


def classify_layer(path: str) -> str:
    path_lower = path.lower().replace("\\", "/")
    if "/frontend" in path_lower or path_lower.endswith("admin-ui"):
        return "ui"
    if "/sdk-" in path_lower:
        return "adapter"
    if "/gateway" in path_lower or "/ops/" in path_lower or path_lower.endswith("/ops"):
        return "infra"
    if any(token in path_lower for token in ["/security", "/billing", "/tenant", "/entitlement", "/audit", "/application", "/workflow", "/outline", "/lore", "/character", "/skill", "saas-security", "saas-billing", "saas-tenant", "saas-entitlement", "saas-audit", "saas-application"]):
        return "shared-capability"
    if "/app" in path_lower or "/demo" in path_lower:
        return "feature-module"
    return "domain-service"


def classify_domain(path: str) -> str:
    path_lower = path.lower().replace("\\", "/")
    for keyword in [
        "security",
        "tenant",
        "billing",
        "entitlement",
        "gateway",
        "audit",
        "developer",
        "application",
        "workflow",
        "outline",
        "lore",
        "character",
        "skill",
        "context",
        "frontend",
        "api",
        "model",
        "database",
        "agent",
    ]:
        if keyword in path_lower:
            return keyword
    return Path(path).name


def detect_repo_manifest_kind(repo_root: Path) -> str:
    if (repo_root / "pom.xml").exists():
        return "maven"
    if (repo_root / "package.json").exists():
        return "node"
    if (repo_root / "requirements.txt").exists() or (repo_root / "pyproject.toml").exists() or (repo_root / "app").exists():
        return "python"
    return "generic"


def parse_xml_modules(pom_path: Path) -> list[str]:
    tree = ET.parse(pom_path)
    root = tree.getroot()
    ns = {"m": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    modules = []
    for module in root.findall(".//m:modules/m:module", ns) if ns else root.findall(".//modules/module"):
        text = (module.text or "").strip()
        if text:
            modules.append(text)
    return modules


def parse_xml_dependencies(pom_path: Path) -> list[str]:
    tree = ET.parse(pom_path)
    root = tree.getroot()
    ns = {"m": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    deps = []
    for dep in root.findall(".//m:dependencies/m:dependency", ns) if ns else root.findall(".//dependencies/dependency"):
        artifact = dep.findtext("m:artifactId", default="", namespaces=ns) if ns else dep.findtext("artifactId", default="")
        if artifact:
            deps.append(artifact.strip())
    return deps


def maven_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    root_pom = repo_root / "pom.xml"
    if not root_pom.exists():
        return []
    declared = parse_xml_modules(root_pom)
    entries: list[ModuleEntry] = []
    for rel in declared:
        mod_root = (repo_root / rel).resolve()
        if not mod_root.exists():
            continue
        if should_ignore_path(mod_root, ignore_patterns, repo_root):
            continue
        artifact = mod_root.name
        layer = classify_layer(rel)
        domain = classify_domain(rel)
        source_root = mod_root / "src" / "main" / "java"
        public_api = None
        if source_root.exists():
            public_api = source_root.relative_to(mod_root).as_posix()
        elif (mod_root / "src").exists():
            public_api = "src"
        key_files = []
        for candidate in [
            mod_root / "src" / "main" / "java",
            mod_root / "src" / "main" / "resources",
            mod_root / "src" / "test" / "java",
        ]:
            if candidate.exists():
                key_files.append(candidate.relative_to(mod_root).as_posix())
        deps = []
        pom = mod_root / "pom.xml"
        if pom.exists():
            for dep in parse_xml_dependencies(pom):
                for rel_other in declared:
                    if Path(rel_other).name == dep:
                        deps.append((repo_root / rel_other).resolve().relative_to(repo_root).as_posix())
                        break
        entries.append(
            ModuleEntry(
                id=module_id_for_path(rel),
                path=rel.replace("\\", "/"),
                layer=layer,
                domain=domain,
                purpose=f"{domain} module",
                public_api=public_api,
                source_of_truth="generated",
                key_files=key_files,
                depends_on=sorted(set(deps)),
                allowed_inbound_from=[],
                allowed_outbound_to=[],
                generated=True,
                index_sources=["pom.xml"],
                owner="unassigned",
                status="active",
                lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
            )
        )
    return entries


def node_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    for package_json in repo_root.rglob("package.json"):
        if should_ignore_path(package_json, ignore_patterns, repo_root):
            continue
        pkg_root = package_json.parent
        if should_ignore_path(pkg_root, ignore_patterns, repo_root):
            continue
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except Exception:
            continue
        name = data.get("name") or pkg_root.name
        rel = normalize_rel_path(repo_root, pkg_root)
        layer = classify_layer(rel)
        domain = classify_domain(rel)
        key_files = []
        for candidate in [pkg_root / "src" / "index.ts", pkg_root / "src" / "index.js", pkg_root / "src" / "App.tsx", pkg_root / "src" / "main.tsx"]:
            if candidate.exists():
                key_files.append(candidate.relative_to(pkg_root).as_posix())
        public_api = None
        if (pkg_root / "src" / "index.ts").exists():
            public_api = "src/index.ts"
        elif (pkg_root / "src" / "index.js").exists():
            public_api = "src/index.js"
        elif "exports" in data:
            public_api = "package.json"
        entries.append(
            ModuleEntry(
                id=module_id_for_path(rel),
                path=rel,
                layer=layer,
                domain=domain,
                purpose=str(data.get("description") or name),
                public_api=public_api,
                source_of_truth="generated",
                key_files=key_files,
                depends_on=[],
                allowed_inbound_from=[],
                allowed_outbound_to=[],
                generated=True,
                index_sources=["package.json"],
                owner="unassigned",
                status="active",
                lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
            )
        )
    return entries


def python_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    candidates = [
        "app",
        "app/api",
        "app/agents",
        "app/database",
        "app/models",
        "app/services",
        "app/services/workflow_engine.py",
        "app/services/plot_outline_service.py",
        "app/services/setting_agent_service.py",
        "app/services/character_depth_service.py",
        "app/services/skill_service.py",
        "app/services/assistant_context",
        "app/services/workflow_adapters",
        "frontend",
        "skills",
    ]
    for rel_candidate in candidates:
        root_dir = repo_root / rel_candidate
        if not root_dir.exists():
            continue
        rel = normalize_rel_path(repo_root, root_dir)
        layer = classify_layer(rel)
        domain = classify_domain(rel)
        key_files: list[str] = []
        if root_dir.is_file():
            key_files.append(root_dir.name)
        else:
            if rel_candidate in {"app", "frontend", "skills"}:
                for candidate in root_dir.glob("*.py"):
                    key_files.append(candidate.name)
            if rel_candidate == "app/api":
                for candidate in (root_dir / "routes").glob("*.py") if (root_dir / "routes").exists() else []:
                    key_files.append(f"routes/{candidate.name}")
            elif rel_candidate == "app/agents":
                for candidate in root_dir.glob("*.py"):
                    key_files.append(candidate.name)
                for candidate in (root_dir / "director").glob("*.py") if (root_dir / "director").exists() else []:
                    key_files.append(f"director/{candidate.name}")
            elif rel_candidate == "app/database":
                for candidate in root_dir.glob("*.py"):
                    key_files.append(candidate.name)
            elif rel_candidate == "app/models":
                for candidate in root_dir.glob("*.py"):
                    key_files.append(candidate.name)
            elif rel_candidate == "app/services":
                for candidate in root_dir.glob("*.py"):
                    key_files.append(candidate.name)
                for candidate in (root_dir / "assistant_context").glob("*.py") if (root_dir / "assistant_context").exists() else []:
                    key_files.append(f"assistant_context/{candidate.name}")
                for candidate in (root_dir / "workflow_adapters").glob("*.py") if (root_dir / "workflow_adapters").exists() else []:
                    key_files.append(f"workflow_adapters/{candidate.name}")
            elif rel_candidate.startswith("app/services/") and root_dir.is_file():
                key_files.append(root_dir.name)
            elif rel_candidate == "frontend":
                for candidate in root_dir.rglob("*.tsx"):
                    if candidate.name in {"main.tsx", "App.tsx"}:
                        key_files.append(candidate.relative_to(root_dir).as_posix())
            elif rel_candidate == "skills":
                for candidate in root_dir.rglob("*.md"):
                    key_files.append(candidate.relative_to(root_dir).as_posix())
        public_api = None
        if rel_candidate == "app/api":
            public_api = "routes"
        elif rel_candidate == "app/agents":
            public_api = "__init__.py" if (root_dir / "__init__.py").exists() else None
        elif rel_candidate == "app/database":
            public_api = "__init__.py" if (root_dir / "__init__.py").exists() else None
        elif rel_candidate == "app/models":
            public_api = "__init__.py" if (root_dir / "__init__.py").exists() else None
        elif rel_candidate == "app/services":
            public_api = "__init__.py" if (root_dir / "__init__.py").exists() else None
        elif rel_candidate.startswith("app/services/") and root_dir.is_file():
            public_api = root_dir.name
        elif rel_candidate == "frontend":
            public_api = "src/main.tsx" if (root_dir / "src" / "main.tsx").exists() else "src/App.tsx" if (root_dir / "src" / "App.tsx").exists() else None
        elif rel_candidate == "skills":
            public_api = "core"
        entries.append(
            ModuleEntry(
                id=module_id_for_path(rel),
                path=rel,
                layer=layer,
                domain=domain,
                purpose=f"{domain} package",
                public_api=public_api,
                source_of_truth="generated",
                key_files=sorted(set(key_files)),
                depends_on=[],
                allowed_inbound_from=[],
                allowed_outbound_to=[],
                generated=True,
                index_sources=["filesystem"],
                owner="unassigned",
                status="active",
                lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
            )
        )
    return entries


def generic_modules(repo_root: Path, ignore_patterns: Iterable[str]) -> list[ModuleEntry]:
    entries: list[ModuleEntry] = []
    for candidate in repo_root.iterdir():
        if candidate.is_dir() and not should_ignore_path(candidate, ignore_patterns, repo_root):
            rel = normalize_rel_path(repo_root, candidate)
            if rel.startswith("."):
                continue
            layer = classify_layer(rel)
            domain = classify_domain(rel)
            if any(key in rel.lower() for key in ["src", "app", "backend", "frontend", "sdk", "ops", "services", "api", "database", "models", "agents"]):
                entries.append(
                    ModuleEntry(
                        id=module_id_for_path(rel),
                        path=rel,
                        layer=layer,
                        domain=domain,
                        purpose=f"{domain} module",
                        public_api=None,
                        source_of_truth="generated",
                        key_files=[],
                        depends_on=[],
                        allowed_inbound_from=[],
                        allowed_outbound_to=[],
                        generated=True,
                        index_sources=["filesystem"],
                        owner="unassigned",
                        status="active",
                        lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
                    )
                )
    return entries


def discover_modules(repo_root: Path, config: Optional[dict[str, Any]] = None) -> list[ModuleEntry]:
    config = config or {}
    ignore_patterns = default_ignore_patterns(config)
    entries: list[ModuleEntry] = []
    entries.extend(maven_modules(repo_root, ignore_patterns))
    entries.extend(node_modules(repo_root, ignore_patterns))
    entries.extend(python_modules(repo_root, ignore_patterns))
    entries.extend(generic_modules(repo_root, ignore_patterns))

    dedup: dict[str, ModuleEntry] = {}
    for entry in entries:
        rel = entry.path.replace("\\", "/")
        if rel not in dedup or len(entry.key_files) > len(dedup[rel].key_files):
            dedup[rel] = entry
    return sorted(dedup.values(), key=lambda item: item.path)


def module_id_for_path(path: str) -> str:
    parts = [part for part in Path(path).as_posix().split("/") if part]
    return ".".join(stable_slug(part).replace("-", ".") for part in parts)


def matches_module_path(path: str, module_path: str) -> bool:
    path_n = Path(path).as_posix().lower().rstrip("/")
    mod_n = Path(module_path).as_posix().lower().rstrip("/")
    return path_n == mod_n or path_n.startswith(mod_n + "/")


def module_for_path(path: str, modules: list[ModuleEntry]) -> Optional[ModuleEntry]:
    path_n = Path(path).as_posix().lower()
    matches = [m for m in modules if path_n == m.path.lower() or path_n.startswith(m.path.lower().rstrip("/") + "/")]
    if not matches:
        return None
    return max(matches, key=lambda m: len(m.path))


def parse_request_type(request_text: str) -> str:
    text = request_text.lower()
    if any(word in text for word in ["refactor", "extract", "抽取", "重构"]):
        return "refactor"
    if any(word in text for word in ["migrate", "迁移"]):
        return "migration"
    if any(word in text for word in ["fix", "bug", "修复", "resolve", "repair"]):
        return "bugfix"
    if any(word in text for word in ["review", "审查", "audit", "check"]):
        return "review"
    if any(word in text for word in ["add", "create", "introduce", "new", "新增", "创建"]):
        return "feature-add"
    return "modify-feature"


def request_high_risk(request_text: str, changed_paths: Iterable[str], modules: list[ModuleEntry]) -> bool:
    text = request_text.lower()
    risky_verbs = ["change", "modify", "extend", "update", "rotate", "inject", "migrate", "refactor", "修复", "变更", "扩展", "迁移", "重构"]
    if any(verb in text for verb in risky_verbs) and any(keyword in text for keyword in HIGH_RISK_KEYWORDS):
        return True
    for path in changed_paths:
        rel = path.replace("\\", "/").lower()
        if any(keyword in rel for keyword in HIGH_RISK_KEYWORDS):
            return True
        mod = module_for_path(rel, modules)
        if mod and any(keyword in mod.path.lower() for keyword in HIGH_RISK_KEYWORDS):
            return True
    return False


def request_duplicate_signal(request_text: str, changed_paths: Iterable[str]) -> tuple[bool, int]:
    text = request_text.lower()
    repeated_words = ["extract", "duplicate", "shared", "common", "reuse", "重复", "抽取", "复用", "共享"]
    keyword_hit = any(word in text for word in repeated_words)
    count = 0
    if keyword_hit:
        count += 1
    if len({Path(path).as_posix().split("/")[0] for path in changed_paths}) > 1:
        count += 1
    if len(list(changed_paths)) >= 2:
        count += 1
    return keyword_hit or count >= 2, count


def capability_match_score(request_text: str, capability: CapabilityEntry) -> float:
    text = request_text.lower()
    signal_sets = [
        capability.intent_keywords,
        capability.aliases,
        capability.business_intents,
        [capability.id, capability.name],
    ]
    for signal_set in signal_sets:
        if match_strength(text, signal_set) >= 1.0:
            return 1.0
    if any(token in text_tokens(request_text) for token in text_tokens(" ".join(capability.intent_keywords + capability.aliases + capability.business_intents + [capability.id, capability.name]))):
        return 0.5
    return 0.0


def capability_path_proximity(capability: CapabilityEntry, changed_modules: list[ModuleEntry], changed_paths: list[str]) -> float:
    owner_paths = {path.replace("\\", "/").lower() for path in capability.owner_modules}
    if not owner_paths:
        return 0.0
    for module in changed_modules:
        if module.path.lower() in owner_paths:
            return 1.0
        if any(matches_module_path(module.path, owner) or matches_module_path(owner, module.path) for owner in owner_paths):
            return 1.0
    for path in changed_paths:
        normalized = path.replace("\\", "/").lower()
        if any(normalized.startswith(owner.rstrip("/").lower()) for owner in owner_paths):
            return 1.0
    return 0.0


def capability_dependency_proximity(capability: CapabilityEntry, changed_modules: list[ModuleEntry], module_map: list[ModuleEntry]) -> float:
    if not capability.dependent_modules:
        return 0.0
    capability_paths = {p.lower() for p in capability.owner_modules}
    for module in changed_modules:
        for dependency in module.depends_on:
            if dependency.lower() in capability_paths:
                return 1.0
        if module.path.lower() in {p.lower() for p in capability.dependent_modules}:
            return 1.0
    return 0.0


def capability_conflicts(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    module_paths = {m["path"].replace("\\", "/").rstrip("/") for m in bundle.get("module_map", {}).get("modules", [])}
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        for owner in capability.get("owner_modules", []):
            if owner.rstrip("/") not in module_paths and not any(path.startswith(owner.rstrip("/") + "/") for path in module_paths):
                errors.append(f"capability {capability['id']} references missing owner module {owner}")
        for public in capability.get("public_entries", []):
            if not any(public == path or public.startswith(path + "/") for path in module_paths) and not any(public.startswith(path) for path in module_paths):
                errors.append(f"capability {capability['id']} references missing public entry {public}")
    return errors


def source_of_truth_for(bundle: dict[str, Any], concern: str) -> str:
    module_map = bundle.get("module_map", {})
    cap_catalog = bundle.get("capability_catalog", {})
    if concern == "capability":
        return "curated" if cap_catalog else "generated"
    if concern == "module":
        return "generated" if module_map else "curated"
    return "curated"


def capability_entries(bundle: dict[str, Any]) -> list[CapabilityEntry]:
    caps = bundle.get("capability_catalog", {}).get("capabilities", [])
    out: list[CapabilityEntry] = []
    for item in caps:
        out.append(CapabilityEntry(**item))
    return out


def module_entries(bundle: dict[str, Any]) -> list[ModuleEntry]:
    modules = bundle.get("module_map", {}).get("modules", [])
    out: list[ModuleEntry] = []
    for item in modules:
        out.append(ModuleEntry(**item))
    return out


def score_capability(request_text: str, capability: CapabilityEntry, changed_modules: list[ModuleEntry], changed_paths: list[str], stale_index: bool, source_conflict: bool) -> tuple[float, dict[str, float]]:
    intent_match = 1.0 if capability_match_score(request_text, capability) >= 1.0 else 0.5 if capability_match_score(request_text, capability) > 0 else 0.0
    alias_match = 1.0 if match_strength(request_text, capability.aliases) >= 1.0 else 0.5 if match_strength(request_text, capability.aliases) > 0 else 0.0
    path_proximity = capability_path_proximity(capability, changed_modules, changed_paths)
    ownership_proximity = 1.0 if path_proximity >= 1.0 else 0.0
    public_entry_available = 1.0 if capability.public_entries else 0.0
    extension_point_available = 1.0 if capability.extension_points else 0.0
    dependency_proximity = capability_dependency_proximity(capability, changed_modules, changed_modules)
    current_context_match = 1.0 if any(token in request_text.lower() for token in [capability.id.lower(), capability.name.lower()]) else 0.0

    raw_score = (
        0.26 * intent_match
        + 0.12 * alias_match
        + 0.20 * path_proximity
        + 0.08 * ownership_proximity
        + 0.08 * public_entry_available
        + 0.10 * extension_point_available
        + 0.10 * dependency_proximity
        + 0.06 * current_context_match
    )
    high_risk_penalty = 1.0 if any(keyword in capability.id for keyword in HIGH_RISK_KEYWORDS) and path_proximity == 0.0 and intent_match < 1.0 else 0.0
    stale_index_penalty = 1.0 if stale_index else 0.0
    source_conflict_penalty = 1.0 if source_conflict else 0.0
    candidate_lifecycle_penalty = 1.0 if capability.status == "candidate" else 0.0
    deprecated_lifecycle_penalty = 1.0 if capability.status in {"deprecated", "retired"} else 0.0
    penalty = (
        0.10 * high_risk_penalty
        + 0.15 * stale_index_penalty
        + 0.20 * source_conflict_penalty
        + 0.15 * candidate_lifecycle_penalty
        + 0.30 * deprecated_lifecycle_penalty
    )
    candidate_score = max(0.0, min(1.0, raw_score - penalty))
    signals = {
        "intent_match": intent_match,
        "alias_match": alias_match,
        "path_proximity": path_proximity,
        "ownership_proximity": ownership_proximity,
        "public_entry_available": public_entry_available,
        "extension_point_available": extension_point_available,
        "dependency_proximity": dependency_proximity,
        "current_context_match": current_context_match,
        "raw_score": raw_score,
        "penalty": penalty,
        "candidate_score": candidate_score,
    }
    return candidate_score, signals


def overlap_score(best: float, second: float) -> float:
    if best <= 0:
        return 0.0
    return min(1.0, second / best)


def requires_review_override(capability: CapabilityEntry, module: Optional[ModuleEntry], route_confidence: float, overlap: float, high_risk: bool, source_conflict: bool, missing_owner: bool, public_entry_change: bool) -> bool:
    if high_risk:
        return True
    if source_conflict and high_risk:
        return True
    if missing_owner:
        return True
    if public_entry_change:
        return True
    if overlap >= 0.90:
        return True
    if capability.status in {"deprecated", "retired"}:
        return True
    if module and module.status == "retired":
        return True
    return False


def determine_action(
    request_text: str,
    capabilities: list[CapabilityEntry],
    modules: list[ModuleEntry],
    changed_paths: list[str],
    route_scores: list[tuple[CapabilityEntry, float, dict[str, float]]],
    stale_index: bool,
    source_conflict: bool,
    high_risk: bool,
) -> tuple[str, Optional[CapabilityEntry], list[str], float, float, bool, bool, bool, list[str]]:
    reasoning: list[str] = []
    if not route_scores:
        return "new", None, [], 0.0, 0.0, False, False, False, ["no capability candidates matched"]

    sorted_scores = sorted(route_scores, key=lambda item: item[1], reverse=True)
    best_cap, best, best_signals = sorted_scores[0]
    second = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
    ov = overlap_score(best, second)
    route_confidence = max(0.0, min(1.0, best - 0.25 * ov - (0.10 if stale_index else 0.0) - (0.10 if source_conflict else 0.0)))
    route_confidence = max(0.0, min(1.0, route_confidence))

    changed_modules = [module_for_path(path, modules) for path in changed_paths]
    changed_modules = [module for module in changed_modules if module is not None]
    missing_owner = not best_cap.owner_modules
    public_entry_change = any(any(path.replace("\\", "/").startswith(entry.rstrip("/") + "/") or path.replace("\\", "/") == entry for entry in best_cap.public_entries) for path in changed_paths)
    review_override = requires_review_override(best_cap, module_for_path(changed_paths[0], modules) if changed_paths else None, route_confidence, ov, high_risk, source_conflict, missing_owner, public_entry_change)

    duplicate_signal, duplicate_count = request_duplicate_signal(request_text, changed_paths)
    coordination_required = False
    composite_route_required = False
    secondary_caps = [cap.id for cap, score, _ in sorted_scores[1:] if score >= 0.60]
    if len(secondary_caps) >= 1 and any(cap.status == "stable" for cap, score, _ in sorted_scores[1:] if score >= 0.60):
        coordination_required = True
    if len([cap for cap, score, _ in sorted_scores if score >= 0.60 and cap.status == "stable"]) > 1:
        composite_route_required = True

    if review_override:
        action = "review"
        reasoning.append("mandatory review override triggered")
    elif duplicate_signal and duplicate_count >= 2 and route_confidence >= 0.60:
        action = "extract"
        reasoning.append("duplicate signal and repeated occurrence indicate extraction")
    elif best < 0.45:
        action = "review" if high_risk else "new"
        reasoning.append("no suitable capability exceeded the reuse threshold")
    elif best_cap.status == "candidate":
        if route_confidence >= 0.60 and best_cap.extension_points:
            action = "extend"
            reasoning.append("candidate capability can be extended through an existing extension point")
        else:
            action = "review"
            reasoning.append("candidate capability requires review before extension")
    elif best_cap.status == "stable":
        if route_confidence >= 0.60 and best_cap.extension_points and any(word in request_text.lower() for word in ["add", "change", "extend", "modify", "update", "修复", "增加", "变更", "扩展"]):
            action = "extend"
            reasoning.append("stable capability selected for extension")
        else:
            action = "reuse"
            reasoning.append("stable capability selected for reuse")
    else:
        action = "review"
        reasoning.append("fallback review")

    if high_risk and action != "review" and ov >= 0.80:
        action = "review"
        reasoning.append("high-risk overlap requires review")

    return action, best_cap, secondary_caps, route_confidence, ov, coordination_required, composite_route_required, public_entry_change, reasoning


def resolve_request(
    request_text: str,
    changed_paths: list[str],
    bundle: dict[str, Any],
    bundle_root: Path,
) -> RouteDecision:
    caps = capability_entries(bundle)
    modules = module_entries(bundle)
    stale = bundle_stale(bundle_root, bundle)
    source_conflict = bool(capability_conflicts(bundle))
    high_risk = request_high_risk(request_text, changed_paths, modules)
    changed_modules = [module_for_path(path, modules) for path in changed_paths]
    changed_modules = [module for module in changed_modules if module is not None]

    route_scores: list[tuple[CapabilityEntry, float, dict[str, float]]] = []
    for capability in caps:
        score, signals = score_capability(request_text, capability, changed_modules, changed_paths, stale, source_conflict)
        if score > 0 or capability.status == "stable":
            route_scores.append((capability, score, signals))

    action, best_cap, secondary_caps, confidence, ov, coordination_required, composite_route_required, public_entry_change, reasoning = determine_action(
        request_text,
        caps,
        modules,
        changed_paths,
        route_scores,
        stale,
        source_conflict,
        high_risk,
    )

    sorted_scores = sorted(route_scores, key=lambda item: item[1], reverse=True)
    candidate_capabilities = [
        {
            "id": cap.id,
            "name": cap.name,
            "status": cap.status,
            "score": round(score, 4),
            "signals": {k: round(v, 4) if isinstance(v, float) else v for k, v in signals.items()},
        }
        for cap, score, signals in sorted_scores
    ]
    candidate_modules: list[dict[str, Any]] = []
    for path in changed_paths:
        module = module_for_path(path, modules)
        if module:
            candidate_modules.append({"path": module.path, "id": module.id, "layer": module.layer, "domain": module.domain})
    if not candidate_modules:
        candidate_modules = [{"path": module.path, "id": module.id, "layer": module.layer, "domain": module.domain} for module in changed_modules]
    required_reads = required_read_paths(best_cap, modules, changed_paths)
    required_checks = required_checks_for(best_cap, action, bundle)
    forbidden_paths = forbidden_paths_for(best_cap, bundle)
    timestamp = iso_now()
    decision = RouteDecision(
        decision_id=f"route-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-{hashlib.sha1((request_text + '|'.join(changed_paths)).encode('utf-8')).hexdigest()[:8]}",
        timestamp=timestamp,
        request_type=parse_request_type(request_text),
        request_summary=request_text.strip().splitlines()[0][:180] if request_text.strip() else "",
        action=action,
        confidence=round(confidence, 4),
        overlap_score=round(ov, 4),
        primary_capability=best_cap.id if best_cap else None,
        secondary_capabilities=secondary_caps,
        candidate_capabilities=candidate_capabilities,
        candidate_modules=candidate_modules,
        required_reads=required_reads,
        required_checks=required_checks,
        forbidden_paths=forbidden_paths,
        review_required=action == "review",
        coordination_required=coordination_required,
        composite_route_required=composite_route_required,
        reasoning=reasoning,
        source_of_truths={
            "capability_catalog": source_of_truth_for(bundle, "capability"),
            "module_map": source_of_truth_for(bundle, "module"),
            "exception_registry": source_of_truth_for(bundle, "exception"),
        },
    )
    return decision


def required_read_paths(capability: Optional[CapabilityEntry], modules: list[ModuleEntry], changed_paths: list[str]) -> list[str]:
    paths: list[str] = []
    if capability:
        paths.extend(capability.public_entries[:3])
        for owner in capability.owner_modules:
            module = next((m for m in modules if m.path == owner), None)
            if module and module.key_files:
                paths.extend([f"{module.path}/{key}" for key in module.key_files[:2]])
            else:
                paths.append(owner)
    for path in changed_paths:
        module = module_for_path(path, modules)
        if module and module.public_api:
            paths.append(f"{module.path}/{module.public_api}")
    dedup: list[str] = []
    for path in paths:
        if path not in dedup:
            dedup.append(path)
    return dedup[:6]


def required_checks_for(capability: Optional[CapabilityEntry], action: str, bundle: dict[str, Any]) -> list[str]:
    checks: list[str] = ["check-reuse", "check-deps", "check-public-api", "check-index-freshness"]
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
    config = bundle.get("config", {})
    freshness = config.get("freshness_windows", {})
    days = int(freshness.get("module_map_days", 1))
    router_config = bundle_root / "router-config.yaml"
    if not router_config.exists():
        return True
    modified = dt.datetime.fromtimestamp(router_config.stat().st_mtime, tz=dt.timezone.utc).date()
    return (dt.datetime.now(dt.timezone.utc).date() - modified).days > days


def build_route_report(decision: RouteDecision) -> dict[str, Any]:
    return decision.to_dict()


def normalized_code(text: str) -> str:
    text = re.sub(r"//.*?$|/\*.*?\*/|#.*?$", " ", text, flags=re.M | re.S)
    string_pattern = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    text = re.sub(string_pattern, '"STR"', text)
    text = re.sub(r"\b\d+(\.\d+)?\b", "NUM", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def python_tokens(path: Path) -> list[str]:
    try:
        import tokenize
        from io import BytesIO

        tokens: list[str] = []
        data = path.read_bytes()
        for tok in tokenize.tokenize(BytesIO(data).readline):
            if tok.type in {tokenize.NAME, tokenize.OP, tokenize.STRING, tokenize.NUMBER}:
                if tok.string in {"def", "class", "import", "from", "return", "async", "await"}:
                    tokens.append(tok.string)
                else:
                    tokens.append("ID")
        return tokens
    except Exception:
        return text_tokens(path.read_text(encoding="utf-8", errors="ignore"))


def token_signature(path: Path) -> str:
    if path.suffix.lower() == ".py":
        tokens = python_tokens(path)
    else:
        tokens = text_tokens(normalized_code(path.read_text(encoding="utf-8", errors="ignore")))
    return hashlib.sha256(" ".join(tokens).encode("utf-8")).hexdigest()


def similarity(a: Path, b: Path) -> float:
    try:
        a_text = normalized_code(a.read_text(encoding="utf-8", errors="ignore"))
        b_text = normalized_code(b.read_text(encoding="utf-8", errors="ignore"))
        return difflib.SequenceMatcher(None, a_text, b_text).ratio()
    except Exception:
        return 0.0


def source_files_for_modules(repo_root: Path, modules: list[ModuleEntry], ignore_patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for module in modules:
        module_path = repo_root / module.path
        if not module_path.exists():
            continue
        for path in iter_source_files(module_path, ignore_patterns):
            files.append(path)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        rel = normalize_rel_path(repo_root, path)
        if rel not in seen:
            seen.add(rel)
            unique.append(path)
    return unique


def path_to_module_map(path: Path, modules: list[ModuleEntry], repo_root: Path) -> Optional[ModuleEntry]:
    rel = normalize_rel_path(repo_root, path)
    return module_for_path(rel, modules)


def parse_python_imports(path: Path) -> list[str]:
    imports: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def parse_js_imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    imports: list[str] = []
    for match in re.finditer(r"(?:import|export)\s+.*?from\s+['\"]([^'\"]+)['\"]", text):
        imports.append(match.group(1))
    for match in re.finditer(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)", text):
        imports.append(match.group(1))
    return imports


def parse_java_imports(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    imports = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("import "):
            value = line.removeprefix("import ").rstrip(";").strip()
            imports.append(value)
    return imports


def resolve_import_to_module(import_name: str, source_module: ModuleEntry, modules: list[ModuleEntry], repo_root: Path, source_file: Path) -> Optional[ModuleEntry]:
    name = import_name.replace("\\", "/").strip()
    if not name:
        return None
    if name.startswith("."):
        target = (source_file.parent / name).resolve()
        for candidate in modules:
            if target.as_posix().lower().startswith((repo_root / candidate.path).resolve().as_posix().lower()):
                return candidate
        return None
    # Java package heuristic.
    if "." in name and not "/" in name:
        package = name.lower()
        for module in modules:
            package_prefix = java_package_prefix(module.path)
            if package.startswith(package_prefix.lower()):
                return module
    # Path import heuristic for TS/Python.
    normalized = name.replace("@/", "").replace("@", "")
    for module in modules:
        mod_path = module.path.replace("\\", "/")
        if normalized.startswith(mod_path.lower()) or mod_path.lower().split("/")[-1] in normalized.lower():
            return module
    return None


def gather_dependency_findings(repo_root: Path, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    findings: list[dict[str, Any]] = []
    for module in modules:
        module_root = repo_root / module.path
        if not module_root.exists():
            continue
        for source_file in iter_source_files(module_root, ignore_patterns):
            kind = file_suffix_kind(source_file)
            if kind == "python":
                imports = parse_python_imports(source_file)
            elif kind in {"typescript", "javascript"}:
                imports = parse_js_imports(source_file)
            elif kind == "java":
                imports = parse_java_imports(source_file)
            else:
                imports = []
            for imp in imports:
                target = resolve_import_to_module(imp, module, modules, repo_root, source_file)
                if not target or target.path == module.path:
                    continue
                if not matches_dependency(module, target, bundle):
                    findings.append(
                        {
                            "severity": "P1",
                            "rule": "dependency-direction",
                            "source_file": normalize_rel_path(repo_root, source_file),
                            "source_module": module.path,
                            "target_module": target.path,
                            "import": imp,
                            "message": f"{module.path} imports {target.path} outside its declared dependency surface",
                        }
                    )
    return findings


def matches_dependency(source: ModuleEntry, target: ModuleEntry, bundle: dict[str, Any]) -> bool:
    allowed = [pattern.replace("\\", "/") for pattern in source.allowed_outbound_to]
    if allowed and glob_match(allowed, target.path):
        return True
    if target.path in source.depends_on:
        return True
    return False


def gather_public_api_findings(repo_root: Path, bundle: dict[str, Any]) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    findings: list[dict[str, Any]] = []
    for module in modules:
        if not module.public_api:
            continue
        module_root = repo_root / module.path
        if not module_root.exists():
            continue
        for source_file in iter_source_files(module_root, ignore_patterns):
            # Only inspect files outside public API directories.
            rel = normalize_rel_path(repo_root, source_file)
            if rel.startswith(f"{module.path}/{module.public_api}"):
                continue
            text = source_file.read_text(encoding="utf-8", errors="ignore")
            if module.public_api.replace("\\", "/") in text and source_file.is_file():
                findings.append(
                    {
                        "severity": "P2",
                        "rule": "public-api-bypass",
                        "source_file": rel,
                        "module": module.path,
                        "message": f"{rel} references internal public API path for {module.path}",
                    }
                )
    return findings


def gather_reuse_findings(repo_root: Path, bundle: dict[str, Any], changed_paths: Optional[list[str]] = None) -> list[dict[str, Any]]:
    modules = module_entries(bundle)
    capabilities = capability_entries(bundle)
    ignore_patterns = default_ignore_patterns(bundle.get("config", {}))
    candidate_files = source_files_for_modules(repo_root, modules, ignore_patterns)
    if changed_paths:
        filtered: list[Path] = []
        for path in candidate_files:
            rel = normalize_rel_path(repo_root, path)
            if any(rel == cp.replace("\\", "/") or rel.startswith(cp.replace("\\", "/").rstrip("/") + "/") for cp in changed_paths):
                filtered.append(path)
        if filtered:
            candidate_files = filtered

    findings: list[dict[str, Any]] = []
    # Direct forbidden paths first.
    for capability in capabilities:
        for pattern in capability.forbidden_patterns:
            for path in candidate_files:
                rel = normalize_rel_path(repo_root, path)
                if fnmatch.fnmatchcase(rel, pattern.replace("\\", "/")):
                    findings.append(
                        {
                            "severity": "P0",
                            "rule": "forbidden-pattern",
                            "path": rel,
                            "capability": capability.id,
                            "message": f"{rel} matches forbidden pattern for {capability.id}",
                        }
                    )

    # Similarity-based duplicates.
    for capability in capabilities:
        owner_files = []
        for owner in capability.owner_modules:
            module = next((m for m in modules if m.path == owner), None)
            if module:
                owner_root = repo_root / module.path
                owner_files.extend([p for p in iter_source_files(owner_root, ignore_patterns) if p.suffix.lower() in {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}])
        if not owner_files:
            continue
        for owner_file in owner_files:
            for path in candidate_files:
                if path == owner_file:
                    continue
                if path.suffix.lower() != owner_file.suffix.lower():
                    continue
                score = similarity(owner_file, path)
                rel = normalize_rel_path(repo_root, path)
                if score >= 0.92:
                    findings.append(
                        {
                            "severity": "P1",
                            "rule": "duplicate-implementation",
                            "path": rel,
                            "capability": capability.id,
                            "score": round(score, 4),
                            "message": f"strong duplicate candidate for {capability.id}",
                        }
                    )
                elif score >= 0.85:
                    findings.append(
                        {
                            "severity": "P2",
                            "rule": "duplicate-implementation",
                            "path": rel,
                            "capability": capability.id,
                            "score": round(score, 4),
                            "message": f"possible duplicate for {capability.id}",
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


def write_bundle(bundle_root: Path, bundle: dict[str, Any], overwrite: bool = True) -> None:
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


def infer_capabilities_from_modules(modules: list[ModuleEntry], repo_root: Path) -> list[CapabilityEntry]:
    archetypes = capability_archetypes()
    capabilities: list[CapabilityEntry] = []
    repo_name = repo_root.name.lower()
    for archetype in archetypes:
        scope = str(archetype.get("repository_scope", "workspace")).lower()
        if scope != "workspace" and scope != repo_name:
            continue
        matched_modules = []
        for module in modules:
            haystack = " ".join([module.path, module.domain, module.purpose] + module.key_files).lower()
            if match_strength(haystack, archetype["keywords"]) >= 1.0:
                matched_modules.append(module.path)
            elif any(hint.lower() in haystack for hint in archetype.get("path_hints", [])):
                matched_modules.append(module.path)
        if matched_modules:
            public_entries = infer_public_entries_from_modules(matched_modules, modules)
            extension_points = infer_extension_points_from_modules(matched_modules, modules)
            capabilities.append(
                CapabilityEntry(
                    id=archetype["id"],
                    name=archetype["name"],
                    status="stable",
                    maturity="shared",
                    source_of_truth="generated",
                    intent_keywords=list(archetype["keywords"]),
                    aliases=list(archetype.get("aliases", [])),
                    business_intents=list(archetype.get("business_intents", [])),
                    scope={"kind": "capability", "repository": archetype.get("repository_scope", "workspace")},
                    owner_modules=sorted(set(matched_modules)),
                    public_entries=public_entries,
                    extension_points=extension_points,
                    route_defaults={"stable_action": "reuse", "extensible_action": "extend", "low_confidence_action": "review"},
                    contracts=list(archetype.get("contracts", [])),
                    related_tests=list(archetype.get("related_tests", [])),
                    test_bindings=list(archetype.get("test_bindings", [])),
                    forbidden_patterns=list(archetype.get("forbidden_patterns", [])),
                    dependent_modules=list(archetype.get("dependent_modules", [])),
                    anti_patterns=list(archetype.get("anti_patterns", [])),
                    lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
                    last_verified_at=today_date(),
                )
            )
    if capabilities:
        return capabilities

    # Fallback candidate capabilities derived from module names.
    for module in modules:
        capability_id = stable_slug(module.domain or Path(module.path).name)
        capabilities.append(
            CapabilityEntry(
                id=capability_id,
                name=module.purpose.title(),
                status="candidate",
                maturity="local",
                source_of_truth="generated",
                intent_keywords=[module.domain, Path(module.path).name],
                aliases=[],
                business_intents=[module.domain],
                scope={"kind": "capability", "repository": "workspace"},
                owner_modules=[module.path],
                public_entries=[module.public_api] if module.public_api else [],
                extension_points=module.key_files[:3],
                route_defaults={"stable_action": "reuse", "extensible_action": "extend", "low_confidence_action": "review"},
                contracts=[],
                related_tests=[],
                test_bindings=[],
                forbidden_patterns=[],
                dependent_modules=module.depends_on,
                anti_patterns=[],
                lifecycle={"introduced_at": today_date(), "deprecated_at": None, "replaced_by": None},
                last_verified_at=today_date(),
            )
        )
    return capabilities


def infer_public_entries_from_modules(matched_modules: list[str], modules: list[ModuleEntry]) -> list[str]:
    entries: list[str] = []
    for matched in matched_modules:
        module = next((m for m in modules if m.path == matched), None)
        if not module:
            continue
        if module.public_api:
            entries.append(f"{module.path}/{module.public_api}".replace("//", "/"))
        elif module.key_files:
            entries.append(f"{module.path}/{module.key_files[0]}".replace("//", "/"))
        else:
            entries.append(module.path)
    dedup: list[str] = []
    for entry in entries:
        if entry not in dedup:
            dedup.append(entry)
    return dedup[:4]


def infer_extension_points_from_modules(matched_modules: list[str], modules: list[ModuleEntry]) -> list[str]:
    points: list[str] = []
    for matched in matched_modules:
        module = next((m for m in modules if m.path == matched), None)
        if not module:
            continue
        for key_file in module.key_files[:3]:
            name = Path(key_file).stem
            if name and name not in points:
                points.append(name)
    return points[:6]


def capability_archetypes() -> list[dict[str, Any]]:
    return [
        {
            "id": "security-jws",
            "name": "Principal JWS and JWKS Security",
            "keywords": ["jws", "jwks", "principal", "token", "signature", "security", "signer", "verifier"],
            "aliases": ["principal-jws", "token-verifier", "key-rotation"],
            "business_intents": ["principal-injection", "downstream-verification", "key-rotation"],
            "path_hints": ["security", "sdk-java", "sdk-node", "gateway"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "tenant-management",
            "name": "Tenant and Workspace Management",
            "keywords": ["tenant", "workspace", "membership", "isolation"],
            "aliases": ["workspace-management", "tenant-context"],
            "business_intents": ["tenant-isolation", "workspace-membership", "workspace-selection"],
            "path_hints": ["tenant"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "billing-subscription",
            "name": "Billing, Subscription, Invoice, and Payment Processing",
            "keywords": ["billing", "subscription", "invoice", "payment", "refund", "webhook", "stripe"],
            "aliases": ["payment-provider", "subscription-billing"],
            "business_intents": ["subscription-lifecycle", "payment-attempt", "invoice-generation"],
            "path_hints": ["billing", "payment", "invoice", "stripe"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "entitlement-usage",
            "name": "Entitlement and Usage Enforcement",
            "keywords": ["entitlement", "quota", "usage", "limit"],
            "aliases": ["quota-enforcement", "usage-tracking"],
            "business_intents": ["feature-entitlement", "quota-check", "usage-idempotency"],
            "path_hints": ["entitlement", "quota", "usage"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "gateway-access",
            "name": "Gateway Access and Launch Enforcement",
            "keywords": ["gateway", "launch", "session", "access", "route"],
            "aliases": ["launch-flow", "app-gateway"],
            "business_intents": ["application-launch", "access-check", "principal-injection"],
            "path_hints": ["gateway", "launch"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "audit-log",
            "name": "Audit and Trace Recording",
            "keywords": ["audit", "trace", "event log", "logging"],
            "aliases": ["audit-recording", "audit-aspect"],
            "business_intents": ["audit-recording", "trace-export"],
            "path_hints": ["audit", "trace"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "application-launch",
            "name": "Application Registration and Launch Sessions",
            "keywords": ["application", "launch", "registration", "session"],
            "aliases": ["app-launch", "application-registry"],
            "business_intents": ["app-discovery", "launch-session", "registered-application"],
            "path_hints": ["application", "launch"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "developer-conformance",
            "name": "Developer Portal and Conformance Testing",
            "keywords": ["developer", "conformance", "webhook", "portal"],
            "aliases": ["developer-portal", "webhook-test"],
            "business_intents": ["developer-onboarding", "webhook-validation", "conformance-check"],
            "path_hints": ["developer", "conformance", "webhook"],
            "repository_scope": "saas-control-plane",
        },
        {
            "id": "workflow-engine",
            "name": "Workflow Engine",
            "keywords": ["workflow", "execution", "node", "runtime", "graph"],
            "aliases": ["workflow-runtime", "workflow-orchestrator"],
            "business_intents": ["workflow-definition", "workflow-execution", "workflow-recovery"],
            "path_hints": ["workflow", "execution"],
            "repository_scope": "GodView",
        },
        {
            "id": "plot-outline",
            "name": "Plot Outline Management",
            "keywords": ["outline", "chapter", "plot", "readiness"],
            "aliases": ["chapter-outline", "outline-resource"],
            "business_intents": ["outline-generation", "outline-validation", "outline-readiness"],
            "path_hints": ["outline", "chapter", "plot"],
            "repository_scope": "GodView",
        },
        {
            "id": "lore-management",
            "name": "Lore and Setting Management",
            "keywords": ["lore", "setting", "world", "reference"],
            "aliases": ["setting-management", "lore-index"],
            "business_intents": ["lore-crud", "lore-indexing", "lore-reference-resolution"],
            "path_hints": ["lore", "setting", "world"],
            "repository_scope": "GodView",
        },
        {
            "id": "character-management",
            "name": "Character and Character Depth Management",
            "keywords": ["character", "persona", "relationship", "voice"],
            "aliases": ["character-depth", "character-graph"],
            "business_intents": ["character-crud", "character-depth", "character-voice"],
            "path_hints": ["character", "persona"],
            "repository_scope": "GodView",
        },
        {
            "id": "skill-system",
            "name": "Skill Retrieval, Execution, and Registry",
            "keywords": ["skill", "prompt", "retrieval", "execution", "registry"],
            "aliases": ["skill-runtime", "prompt-skill"],
            "business_intents": ["skill-retrieval", "skill-execution", "skill-registry"],
            "path_hints": ["skill", "prompt"],
            "repository_scope": "GodView",
        },
        {
            "id": "assistant-context",
            "name": "Assistant Context Snapshot and Retrieval",
            "keywords": ["assistant context", "session", "snapshot", "retrieval", "delta"],
            "aliases": ["context-fabric", "assistant-session"],
            "business_intents": ["context-snapshot", "session-state", "retrieval-delta"],
            "path_hints": ["context", "snapshot", "session"],
            "repository_scope": "GodView",
        },
    ]


def build_change_rules(capabilities: list[CapabilityEntry]) -> dict[str, Any]:
    high_risk_ids = [cap.id for cap in capabilities if cap.id in {"security-jws", "billing-subscription", "entitlement-usage", "gateway-access", "tenant-management"}]
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "confidence": {"auto_route_threshold": 0.85, "guarded_route_threshold": 0.60},
        "high_risk_conditions": [
            "shared-capability-contract-change",
            "auth-or-billing-module-change",
            "schema-migration",
            "security-sensitive-entry",
            "gateway-claim-change",
            "multi-capability-core-change",
        ],
        "high_risk_capability_ids": high_risk_ids,
        "high_risk_module_patterns": [],
        "route_rules": [
            {
                "name": "prefer-reuse-for-stable-capability",
                "when": {"capability_status": "stable", "public_entry_exists": True, "matching_intent": True},
                "action": "reuse",
            },
            {
                "name": "prefer-extend-when-extension-point-exists",
                "when": {"extension_point_exists": True, "behavior_is_compatible": True},
                "action": "extend",
            },
            {
                "name": "prefer-extract-when-duplicate-signal-is-strong",
                "when": {"duplicate_signal": True, "repeated_occurrence_gte": 2},
                "action": "extract",
            },
            {
                "name": "require-review-for-low-confidence",
                "when": {"confidence_below": 0.60},
                "action": "review",
            },
            {
                "name": "require-review-for-heavy-overlap",
                "when": {"candidate_capabilities_overlap_gte": 0.80},
                "action": "review",
            },
        ],
        "decision_policy": {
            "tie_breaker": "review",
            "high_risk_override": "review",
            "human_override_allowed": True,
            "human_override_must_record_reason": True,
        },
    }


def build_router_config(repo_root: Path) -> dict[str, Any]:
    repo_name = repo_root.name.lower()
    repositories: list[dict[str, Any]] = []
    for candidate in repo_root.iterdir():
        if candidate.is_dir() and not should_ignore_path(candidate, DEFAULT_IGNORE_GLOBS, repo_root):
            if (candidate / "pom.xml").exists() or (candidate / "package.json").exists() or (candidate / "app").exists():
                repositories.append({"id": candidate.name, "path": candidate.name, "type": detect_repo_manifest_kind(candidate)})
    if not repositories:
        repositories.append({"id": repo_name, "path": ".", "type": detect_repo_manifest_kind(repo_root)})
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_name,
        "source_commit": current_git_commit(repo_root),
        "repo_id": repo_name,
        "repositories": repositories,
        "protected_branch_patterns": ["main", "master", "release/*"],
        "ignore_paths": DEFAULT_IGNORE_GLOBS,
        "supported_languages": ["java", "python", "typescript", "javascript"],
        "module_discovery": {"maven": True, "node_workspace": True, "python_package": True},
        "freshness_windows": {
            "capability_catalog_days": 7,
            "module_map_days": 1,
            "exception_registry_days": 1,
            "evaluation_set_days": 30,
        },
        "evaluation": {"minimum_case_count": 30, "top1_accuracy_threshold": 0.85, "review_precision_threshold": 0.90},
        "route_reports_dir": "reports/route-decisions",
        "rebuild_reports_dir": "reports/index-rebuild",
        "guardrail_reports_dir": "reports/guardrail-results",
        "evaluation_reports_dir": "reports/evaluation",
    }


def current_git_commit(path: Path) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
        commit = result.stdout.strip()
        return commit or None
    except Exception:
        return None


def build_ownership(capabilities: list[CapabilityEntry], modules: list[ModuleEntry]) -> dict[str, Any]:
    owners = []
    for cap in capabilities:
        owners.append(
            {
                "scope": "capability",
                "target": cap.id,
                "primary": {
                    "security-jws": "scp-security-team",
                    "tenant-management": "scp-platform-team",
                    "billing-subscription": "scp-billing-team",
                    "entitlement-usage": "scp-platform-team",
                    "gateway-access": "scp-security-team",
                    "audit-log": "scp-platform-team",
                    "application-launch": "scp-platform-team",
                    "developer-conformance": "scp-platform-team",
                    "workflow-engine": "godview-workflow-team",
                    "plot-outline": "godview-story-engine-team",
                    "lore-management": "godview-knowledge-team",
                    "character-management": "godview-character-team",
                    "skill-system": "godview-platform-team",
                    "assistant-context": "godview-platform-team",
                }.get(cap.id, "platform-team"),
                "reviewers": ["architecture-board"],
                "escalation_group": "architecture-board",
            }
        )
    for module in modules:
        owners.append(
            {
                "scope": "module",
                "target": module.path,
                "primary": module.owner if module.owner != "unassigned" else "platform-team",
                "reviewers": ["architecture-board"],
                "escalation_group": "architecture-board",
            }
        )
    return {"schema_version": 1, "generated_at": iso_now(), "generated_by": "bootstrap_router", "source_repository": "workspace", "source_commit": None, "owners": owners}


def build_module_map(repo_root: Path, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    modules = discover_modules(repo_root, config)
    infer_module_dependencies(repo_root, modules, config or {})
    # Owner and dependency heuristics.
    for module in modules:
        lower = module.path.lower()
        if "security" in lower:
            module.owner = "scp-security-team" if "saas-control-plane" in lower else "godview-platform-team"
        elif "billing" in lower:
            module.owner = "scp-billing-team"
        elif "tenant" in lower:
            module.owner = "scp-platform-team"
        elif "workflow" in lower:
            module.owner = "godview-workflow-team"
        elif "outline" in lower:
            module.owner = "godview-story-engine-team"
        elif "lore" in lower:
            module.owner = "godview-knowledge-team"
        elif "character" in lower:
            module.owner = "godview-character-team"
        elif "skill" in lower:
            module.owner = "godview-platform-team"
        elif "context" in lower:
            module.owner = "godview-platform-team"
        elif "gateway" in lower:
            module.owner = "scp-security-team"
        elif "developer" in lower:
            module.owner = "scp-platform-team"
        elif "frontend" in lower or "ui" in lower:
            module.owner = "godview-platform-team" if "godview" in lower else "scp-platform-team"
        elif "sdk" in lower:
            module.owner = "scp-security-team"
        elif "app" in lower or "demo" in lower:
            module.owner = "scp-platform-team"
        if not module.allowed_outbound_to:
            module.allowed_outbound_to = sorted(set(module.depends_on))

    module_dicts = [module.to_dict() for module in modules]
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "modules": module_dicts,
    }


def infer_module_dependencies(repo_root: Path, modules: list[ModuleEntry], config: dict[str, Any]) -> None:
    ignore_patterns = default_ignore_patterns(config)
    for module in modules:
        module_root = repo_root / module.path
        if not module_root.exists():
            continue
        deps: set[str] = set(module.depends_on)
        for source_file in iter_source_files(module_root, ignore_patterns):
            kind = file_suffix_kind(source_file)
            if kind == "python":
                imports = parse_python_imports(source_file)
            elif kind in {"typescript", "javascript"}:
                imports = parse_js_imports(source_file)
            elif kind == "java":
                imports = parse_java_imports(source_file)
            else:
                imports = []
            for imp in imports:
                target = resolve_import_to_module(imp, module, modules, repo_root, source_file)
                if target and target.path != module.path:
                    deps.add(target.path)
        module.depends_on = sorted(deps)


def build_capability_catalog(repo_root: Path, module_map: dict[str, Any]) -> dict[str, Any]:
    modules = [ModuleEntry(**module) for module in module_map.get("modules", [])]
    capabilities = infer_capabilities_from_modules(modules, repo_root)
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "capabilities": [cap.to_dict() for cap in capabilities],
    }


def build_evaluation_set(capabilities: list[CapabilityEntry], module_map: dict[str, Any]) -> dict[str, Any]:
    stable_caps = [cap for cap in capabilities if cap.status == "stable"]
    cases: list[dict[str, Any]] = []
    if not stable_caps:
        stable_caps = capabilities[:]
    for cap in stable_caps[:10]:
        reuse_changed_paths = [owner for owner in cap.dependent_modules[:1]] if cap.dependent_modules else []
        cases.append(
            {
                "id": f"{cap.id}-reuse",
                "request": f"Reuse the existing {cap.name.lower()} capability in the integration layer.",
                "expected_action": "reuse",
                "expected_capabilities": [cap.id],
                "expected_modules": cap.owner_modules[:2],
                "expected_reads": cap.public_entries[:2],
                "changed_paths": reuse_changed_paths,
                "risk_level": "medium",
            }
        )
        expected_extend_action = "review" if any(keyword in cap.id for keyword in ["security", "billing", "entitlement", "gateway", "tenant"]) else "extend"
        cases.append(
            {
                "id": f"{cap.id}-extend",
                "request": f"Extend the existing {cap.name.lower()} capability with a compatible new behavior.",
                "expected_action": expected_extend_action,
                "expected_capabilities": [cap.id],
                "expected_modules": cap.owner_modules[:2],
                "expected_reads": cap.public_entries[:2],
                "changed_paths": cap.owner_modules[:1],
                "risk_level": "high",
            }
        )
    for cap in stable_caps[:4]:
        expected_extract_action = "review" if any(keyword in cap.id for keyword in ["security", "billing", "entitlement", "gateway", "tenant"]) else "extract"
        cases.append(
            {
                "id": f"{cap.id}-extract",
                "request": f"Extract repeated {cap.name.lower()} logic into a shared capability.",
                "expected_action": expected_extract_action,
                "expected_capabilities": [cap.id],
                "expected_modules": cap.owner_modules[:2],
                "expected_reads": cap.public_entries[:2],
                "changed_paths": cap.owner_modules[:2],
                "risk_level": "high",
            }
        )
    cases.extend(
        [
            {
                "id": "new-capability-1",
                "request": "Introduce a new capability for a workflow not covered by the current catalog.",
                "expected_action": "new",
                "expected_capabilities": [],
                "expected_modules": [],
                "expected_reads": [],
                "risk_level": "medium",
            },
            {
                "id": "new-capability-2",
                "request": "Build a brand-new feature area with no reusable shared entry point.",
                "expected_action": "new",
                "expected_capabilities": [],
                "expected_modules": [],
                "expected_reads": [],
                "risk_level": "medium",
            },
            {
                "id": "review-high-risk-1",
                "request": "Change two stable shared capabilities in one request.",
                "expected_action": "review",
                "expected_capabilities": [stable_caps[0].id if stable_caps else "unknown"],
                "expected_modules": stable_caps[0].owner_modules[:2] if stable_caps else [],
                "expected_reads": [],
                "changed_paths": stable_caps[0].owner_modules[:2] if stable_caps else [],
                "risk_level": "critical",
            },
            {
                "id": "review-high-risk-2",
                "request": "Modify gateway claims and billing state transitions together.",
                "expected_action": "review",
                "expected_capabilities": ["gateway-access", "billing-subscription"],
                "expected_modules": [],
                "expected_reads": [],
                "changed_paths": ["backend/saas-gateway", "backend/saas-billing"],
                "risk_level": "critical",
            },
        ]
    )
    while len(cases) < 30 and stable_caps:
        cap = stable_caps[len(cases) % len(stable_caps)]
        cases.append(
            {
                "id": f"extra-{len(cases)+1}",
                "request": f"Reuse {cap.name.lower()} without changing its core logic.",
                "expected_action": "reuse",
                "expected_capabilities": [cap.id],
                "expected_modules": cap.owner_modules[:2],
                "expected_reads": cap.public_entries[:2],
                "risk_level": "medium",
            }
        )
    return {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": "workspace",
        "source_commit": None,
        "cases": cases[:30],
    }


def build_router_bundle(repo_root: Path) -> dict[str, Any]:
    config = build_router_config(repo_root)
    module_map = build_module_map(repo_root, config)
    capability_catalog = build_capability_catalog(repo_root, module_map)
    capabilities = [CapabilityEntry(**cap) for cap in capability_catalog["capabilities"]]
    ownership = build_ownership(capabilities, [ModuleEntry(**module) for module in module_map["modules"]])
    change_rules = build_change_rules(capabilities)
    exception_registry = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "generated_by": "bootstrap_router",
        "source_repository": repo_root.name,
        "source_commit": current_git_commit(repo_root),
        "exceptions": [],
    }
    evaluation_set = build_evaluation_set(capabilities, module_map)
    return {
        "config": config,
        "module_map": module_map,
        "capability_catalog": capability_catalog,
        "ownership": ownership,
        "change_rules": change_rules,
        "exception_registry": exception_registry,
        "evaluation_set": evaluation_set,
    }


def route_bundle_from_repo(repo_root: Path) -> dict[str, Any]:
    bundle_root = resolve_bundle_root(repo_root)
    if bundle_root.exists():
        bundle = load_bundle(bundle_root)
        if bundle:
            bundle["root"] = bundle_root
            return bundle
    bundle = build_router_bundle(repo_root)
    bundle["root"] = bundle_root
    return bundle


def route_or_bootstrap(repo_root: Path, request_text: str, changed_paths: list[str]) -> RouteDecision:
    bundle = route_bundle_from_repo(repo_root)
    return resolve_request(request_text, changed_paths, bundle, bundle.get("root", resolve_bundle_root(repo_root)))


def test_bindings_for_action(bundle: dict[str, Any], action: str, changed_paths: list[str]) -> list[dict[str, Any]]:
    caps = capability_entries(bundle)
    bindings: list[dict[str, Any]] = []
    for cap in caps:
        for binding in cap.test_bindings:
            if action in binding.get("when_actions", []) and any(
                glob_match([pattern], path.replace("\\", "/")) for pattern in binding.get("when_changed_paths", []) for path in changed_paths
            ):
                bindings.append(binding)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for binding in bindings:
        if binding["id"] not in seen:
            seen.add(binding["id"])
            unique.append(binding)
    return unique


def run_command(command: list[str], cwd: Path) -> tuple[int, str, str]:
    result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


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
    review_correct = 0
    for case in evaluations:
        decision = resolve_request(case["request"], case.get("changed_paths", []), bundle, bundle.get("root", resolve_bundle_root(repo_root)))
        action_ok = decision.action == case["expected_action"]
        primary_ok = not case.get("expected_capabilities") or decision.primary_capability in case["expected_capabilities"]
        review_expected += 1 if case["expected_action"] == "review" else 0
        review_correct += 1 if case["expected_action"] == "review" and decision.action == "review" else 0
        action_matches += 1 if action_ok else 0
        primary_matches += 1 if primary_ok else 0
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
    summary = {
        "run_id": f"eval-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "case_count": len(evaluations),
        "top1_action_accuracy": round(action_matches / total, 4),
        "top1_capability_accuracy": round(primary_matches / total, 4),
        "review_precision": round(review_correct / review_expected, 4) if review_expected else 1.0,
        "review_recall": round(review_correct / review_expected, 4) if review_expected else 1.0,
        "false_positive_count": sum(1 for result in results if result["expected_action"] == "review" and result["predicted_action"] != "review"),
        "false_negative_count": sum(1 for result in results if result["expected_action"] != "review" and result["predicted_action"] == "review"),
        "per_case_results": results,
        "status": "pass"
        if (action_matches / total) >= bundle.get("config", {}).get("evaluation", {}).get("top1_accuracy_threshold", 0.85)
        else "fail",
    }
    return summary


def write_report(path: Path, report: dict[str, Any]) -> None:
    dump_json_file(path, report)


def update_last_verified(bundle_root: Path, bundle: dict[str, Any]) -> None:
    now = today_date()
    refs = bundle_root / "references"
    for file_name in ["capability-catalog.yaml", "module-map.yaml", "ownership.yaml", "change-rules.yaml", "exception-registry.yaml", "evaluation-set.yaml"]:
        path = refs / file_name
        if path.exists():
            data = load_yaml_file(path)
            data["generated_at"] = iso_now()
            data["generated_by"] = "rebuild_index"
            if isinstance(data, dict) and "capabilities" in data:
                for cap in data["capabilities"]:
                    cap["last_verified_at"] = now
            dump_yaml_file(path, data)


def rebuild_index(repo_root: Path, write_back: bool = False) -> dict[str, Any]:
    bundle = build_router_bundle(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    reports_dir = bundle_root / "reports" / "index-rebuild"
    reports_dir.mkdir(parents=True, exist_ok=True)
    discovered_modules = bundle["module_map"]["modules"]
    curated_capabilities = bundle["capability_catalog"]["capabilities"]
    conflicts = capability_conflicts(bundle)
    missing_paths = []
    for module in discovered_modules:
        if not (repo_root / module["path"]).exists():
            missing_paths.append(module["path"])
    report = {
        "report_id": f"rebuild-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "source_commit": current_git_commit(repo_root),
        "generated_modules_count": len(discovered_modules),
        "curated_entries_count": len(curated_capabilities),
        "conflicts": conflicts,
        "stale_entries": [],
        "missing_paths": missing_paths,
        "status": "pass" if not conflicts and not missing_paths else "fail",
    }
    if write_back:
        write_bundle(bundle_root, bundle)
        update_last_verified(bundle_root, bundle)
        write_report(reports_dir / "latest.json", report)
    else:
        write_report(reports_dir / "latest.json", report)
    return report


def freshness_report(repo_root: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    config = bundle.get("config", {})
    windows = config.get("freshness_windows", {})
    bundle_root = bundle.get("root", resolve_bundle_root(repo_root))
    results = []
    for key, filename in [
        ("capability_catalog_days", "references/capability-catalog.yaml"),
        ("module_map_days", "references/module-map.yaml"),
        ("exception_registry_days", "references/exception-registry.yaml"),
        ("evaluation_set_days", "references/evaluation-set.yaml"),
    ]:
        path = bundle_root / filename
        if not path.exists():
            results.append({"item": filename, "fresh": False, "reason": "missing file"})
            continue
        days = int(windows.get(key, 7))
        age_days = (dt.datetime.now(dt.timezone.utc).date() - dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc).date()).days
        results.append({"item": filename, "fresh": age_days <= days, "age_days": age_days, "threshold_days": days})
    missing_references = []
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        for ref in capability.get("owner_modules", []):
            if not (repo_root / ref).exists():
                missing_references.append(ref)
        for ref in capability.get("public_entries", []):
            if not any((repo_root / path).exists() for path in [ref, ref.split("/")[0]]):
                missing_references.append(ref)
    return {
        "report_id": f"freshness-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "status": "pass" if all(item.get("fresh", True) for item in results) and not missing_references else "fail",
        "checks": results,
        "missing_references": sorted(set(missing_references)),
    }


def generate_feedback(bundle_root: Path) -> dict[str, Any]:
    route_dir = bundle_root / "reports" / "route-decisions"
    guardrail_dir = bundle_root / "reports" / "guardrail-results"
    proposals: list[dict[str, Any]] = []
    for report_file in sorted(route_dir.glob("*.json")):
        try:
            report = load_json_file(report_file)
        except Exception:
            continue
        if report.get("review_required"):
            proposals.append(
                {
                    "kind": "routing-review",
                    "decision_id": report.get("decision_id"),
                    "reason": report.get("reasoning", []),
                    "suggestion": "Add or refine keywords, aliases, or ownership for the reviewed capability.",
                }
            )
    for report_file in sorted(guardrail_dir.glob("*.json")):
        try:
            report = load_json_file(report_file)
        except Exception:
            continue
        for finding in report.get("findings", []):
            proposals.append(
                {
                    "kind": "guardrail-finding",
                    "rule": finding.get("rule"),
                    "severity": finding.get("severity"),
                    "path": finding.get("path") or finding.get("source_file"),
                    "suggestion": "Promote this pattern into the capability catalog or add a blocking rule.",
                }
            )
    return {
        "report_id": f"feedback-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": iso_now(),
        "proposals": proposals,
        "status": "pass",
    }


def create_bundle_directory(repo_root: Path) -> Path:
    bundle_root = resolve_bundle_root(repo_root)
    bundle_root.mkdir(parents=True, exist_ok=True)
    for sub in ["references", "schemas", "reports/route-decisions", "reports/index-rebuild", "reports/guardrail-results", "reports/evaluation"]:
        (bundle_root / sub).mkdir(parents=True, exist_ok=True)
    return bundle_root


def copy_skill_schemas_to_bundle(bundle_root: Path) -> None:
    skill_schemas = schema_dir()
    target = bundle_root / "schemas"
    target.mkdir(parents=True, exist_ok=True)
    for schema_file in skill_schemas.glob("*.json"):
        shutil.copy2(schema_file, target / schema_file.name)


def bootstrap_bundle(repo_root: Path, write: bool = True) -> dict[str, Any]:
    bundle = build_router_bundle(repo_root)
    bundle_root = resolve_bundle_root(repo_root)
    bundle["root"] = bundle_root
    if write:
        create_bundle_directory(repo_root)
        clear_core_reference_files(bundle_root)
        write_bundle(bundle_root, bundle)
        copy_skill_schemas_to_bundle(bundle_root)
        update_last_verified(bundle_root, bundle)
    return bundle


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


def validate_bundle_files(bundle_root: Path) -> list[str]:
    return validate_bundle(bundle_root)


def schema_files() -> list[str]:
    return [
        "router-config.schema.json",
        "capability-catalog.schema.json",
        "module-map.schema.json",
        "ownership.schema.json",
        "change-rules.schema.json",
        "exception-registry.schema.json",
        "evaluation-set.schema.json",
        "route-decision-report.schema.json",
        "guardrail-report.schema.json",
        "index-rebuild-report.schema.json",
        "evaluation-summary.schema.json",
    ]
