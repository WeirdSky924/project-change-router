from __future__ import annotations

import hashlib
import fnmatch
import json
import os
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

from router_support.typed_findings import digest_value


PROFILE_NAMES = (
    ".project-change-router.yaml",
    ".project-change-router.yml",
    "project-change-router.profile.yaml",
    "project-change-router.profile.yml",
)
SOURCE_SUFFIXES = frozenset(
    {".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".sql"}
)
IGNORED_SOURCE_PARTS = frozenset(
    {".git", "node_modules", "dist", "build", "coverage", "__pycache__", ".pytest_cache"}
)


def _module_for_path(path: str, module_paths: Iterable[str]) -> str | None:
    normalized = path.replace("\\", "/").strip("/")
    matches = [
        module
        for module in module_paths
        if normalized == module or normalized.startswith(f"{module.rstrip('/')}/")
    ]
    return max(matches, key=len) if matches else None


def build_capability_closure(
    bundle: Mapping[str, Any], seeds: set[str]
) -> set[str]:
    modules = list(bundle.get("module_map", {}).get("modules", []))
    capabilities = list(
        bundle.get("capability_catalog", {}).get("capabilities", [])
    )
    capabilities_by_module: dict[str, set[str]] = defaultdict(set)
    for capability in capabilities:
        capability_id = str(capability.get("id", ""))
        for owner in capability.get("owner_modules", []):
            if capability_id:
                capabilities_by_module[str(owner).strip("/")].add(capability_id)
    module_paths = list(capabilities_by_module)
    graph: dict[str, set[str]] = defaultdict(set)
    for module in modules:
        source_path = str(module.get("path", "")).strip("/")
        source_ids = capabilities_by_module.get(source_path, set())
        for dependency in module.get("depends_on", []):
            target_path = _module_for_path(str(dependency), module_paths)
            target_ids = capabilities_by_module.get(target_path or "", set())
            for source in source_ids:
                graph[source].update(target_ids)
            for target in target_ids:
                graph[target].update(source_ids)
    for entry in bundle.get("path_to_capability_map", {}).get("path_index", []):
        related = {
            str(value)
            for key in ("capabilities", "consumer_capabilities")
            for value in entry.get(key, [])
            if value
        }
        for capability_id in related:
            graph[capability_id].update(related - {capability_id})
    closure = set(seeds)
    pending = list(seeds)
    while pending:
        current = pending.pop()
        for neighbor in graph.get(current, set()):
            if neighbor not in closure:
                closure.add(neighbor)
                pending.append(neighbor)
    return closure


def _git_state(repo_root: Path) -> tuple[str | None, list[str]]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        head = None
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return head, []
    paths = [
        line[3:].split(" -> ")[-1].replace("\\", "/")
        for line in status.splitlines()
        if len(line) > 3
    ]
    return head or None, sorted(set(paths))


def _unversioned_source_paths(repo_root: Path) -> list[str]:
    return sorted(
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SOURCE_SUFFIXES
        and not any(part in IGNORED_SOURCE_PARTS for part in path.relative_to(repo_root).parts)
    )


def _path_record(repo_root: Path, path_text: str) -> dict[str, Any]:
    normalized = path_text.replace("\\", "/").strip("/")
    target = repo_root / normalized
    if not target.exists():
        return {"path": normalized, "state": "deleted"}
    if target.is_dir():
        return {"path": normalized, "state": "directory"}
    content = target.read_bytes()
    return {
        "path": normalized,
        "state": "file",
        "size": len(content),
        "content_digest": hashlib.sha256(content).hexdigest(),
    }


def _profile_digest(repo_root: Path) -> str:
    records = []
    for name in PROFILE_NAMES:
        path = repo_root / name
        if path.is_file():
            records.append(
                {"path": name, "digest": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    return digest_value(records)


def _bundle_digest(bundle: Mapping[str, Any]) -> str:
    return digest_value(
        {
            key: bundle.get(key, {})
            for key in (
                "config",
                "module_map",
                "capability_catalog",
                "ownership",
                "path_to_capability_map",
                "change_rules",
            )
        }
    )


def capabilities_for_path(
    bundle: Mapping[str, Any], path_text: str
) -> set[str]:
    path = path_text.replace("\\", "/").strip("/")
    matches: set[str] = set()
    for entry in bundle.get("path_to_capability_map", {}).get("path_index", []):
        pattern = str(entry.get("path_pattern", "")).replace("\\", "/").strip("/")
        if pattern and fnmatch.fnmatchcase(path, pattern):
            matches.update(str(value) for value in entry.get("capabilities", []) if value)
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        capability_id = str(capability.get("id", ""))
        surfaces = [
            *capability.get("owner_modules", []),
            *capability.get("public_entries", []),
            *capability.get("related_tests", []),
        ]
        for surface in surfaces:
            normalized_surface = str(surface).replace("\\", "/").strip("/")
            if not normalized_surface:
                continue
            if path == normalized_surface or path.startswith(
                f"{normalized_surface.rstrip('/')}/"
            ):
                matches.add(capability_id)
                break
    return matches


def build_evidence_input(
    repo_root: Path,
    bundle: Mapping[str, Any],
    changed_paths: Iterable[str],
    *,
    runtime_identity: Mapping[str, Any],
    structure_digest: str,
    route_capabilities: Iterable[str] = (),
) -> dict[str, Any]:
    repo = Path(repo_root).resolve()
    head, worktree_paths = _git_state(repo)
    if head is None and not worktree_paths:
        worktree_paths = _unversioned_source_paths(repo)
    route_paths = sorted(
        {str(path).replace("\\", "/").strip("/") for path in changed_paths if path}
    )
    global_paths = sorted(set(route_paths) | set(worktree_paths))
    global_records = [_path_record(repo, path) for path in global_paths]
    seeds = {str(value) for value in route_capabilities if value}
    for path in route_paths:
        seeds.update(capabilities_for_path(bundle, path))
    closure = build_capability_closure(bundle, seeds)
    closure_paths = sorted(
        set(route_paths)
        | {
            path
            for path in worktree_paths
            if capabilities_for_path(bundle, path) & closure
        }
    )
    closure_records = [_path_record(repo, path) for path in closure_paths]
    route_records = [_path_record(repo, path) for path in route_paths]
    path_patterns = sorted(
        str(item.get("path_pattern", ""))
        for item in bundle.get("path_to_capability_map", {}).get("path_index", [])
        if item.get("path_pattern")
    )
    common = {
        "head": head,
        "route_paths": route_paths,
        "profile_digest": _profile_digest(repo),
        "bundle_digest": _bundle_digest(bundle),
        "structure_digest": structure_digest,
        "indexed_paths_digest": digest_value(path_patterns),
        "runtime_identity_digest": str(runtime_identity.get("identity_digest", "")),
    }
    evidence = {
        **common,
        "worktree_paths": worktree_paths,
        "route_capability_seeds": sorted(seeds),
        "route_capability_closure": sorted(closure),
        "global_source_fingerprints": global_records,
        "global_source_fingerprint_digest": digest_value(global_records),
        "closure_source_fingerprints": closure_records,
        "closure_source_fingerprint_digest": digest_value(closure_records),
        "route_source_fingerprints": route_records,
        "route_source_fingerprint_digest": digest_value(route_records),
        # Compatibility aliases now intentionally represent route closure, not the whole worktree.
        "source_fingerprints": closure_records,
        "source_fingerprint_digest": digest_value(closure_records),
    }
    evidence["governance_input_digest"] = digest_value(
        {
            key: common[key]
            for key in (
                "profile_digest",
                "bundle_digest",
                "indexed_paths_digest",
                "runtime_identity_digest",
            )
        }
    )
    evidence["global_input_digest"] = digest_value(
        {**common, "source_fingerprints": global_records}
    )
    evidence["closure_input_digest"] = digest_value(
        {
            **common,
            "route_capability_closure": sorted(closure),
            "source_fingerprints": closure_records,
        }
    )
    evidence["task_input_digest"] = digest_value(
        {**common, "source_fingerprints": route_records}
    )
    evidence["input_digest"] = evidence["closure_input_digest"]
    return evidence


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class IncrementalEvidenceCache:
    def __init__(self, runtime_root: Path) -> None:
        self.root = Path(runtime_root) / "incremental-cache"

    def _path(self, check_name: str, evidence: Mapping[str, Any]) -> Path:
        safe = "".join(char if char.isalnum() or char in "-_" else "-" for char in check_name)
        return self.root / safe / f"{evidence.get('input_digest', '')}.json"

    def save(
        self,
        check_name: str,
        evidence: Mapping[str, Any],
        report: Mapping[str, Any],
    ) -> Path:
        path = self._path(check_name, evidence)
        _atomic_json(
            path,
            {
                "check": check_name,
                "evidence": dict(evidence),
                "report": dict(report),
            },
        )
        return path

    def load(
        self, check_name: str, evidence: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        path = self._path(check_name, evidence)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("evidence") != dict(evidence):
            return None
        report = dict(value.get("report", {}))
        report["cache"] = {
            "hit": True,
            "input_digest": evidence.get("input_digest"),
            "artifact": str(path),
        }
        return report


def _graph_edges(
    bundle: Mapping[str, Any], evidence: Mapping[str, Any]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    edges: dict[str, dict[str, str]] = {}
    unresolved: list[str] = []
    modules = list(bundle.get("module_map", {}).get("modules", []))
    module_paths = {
        str(module.get("path", "")).strip("/")
        for module in modules
        if module.get("path")
    }

    def add(kind: str, source: str, target: str) -> None:
        edge_id = f"{kind}:{source}->{target}"
        edges[edge_id] = {
            "kind": kind,
            "source": source,
            "target": target,
            "digest": digest_value(
                {"kind": kind, "source": source, "target": target}
            ),
        }

    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        capability_id = str(capability.get("id", ""))
        if not capability_id:
            continue
        for module_path in capability.get("owner_modules", []):
            normalized = str(module_path).strip("/")
            if normalized in module_paths:
                add(
                    "capability_owner",
                    f"capability:{capability_id}",
                    f"module:{normalized}",
                )
            else:
                unresolved.append(
                    f"capability_owner:capability:{capability_id}->module:{normalized}"
                )
    for module in modules:
        source_path = str(module.get("path", "")).strip("/")
        if not source_path:
            continue
        for dependency in module.get("depends_on", []):
            target_path = _module_for_path(str(dependency), module_paths)
            if target_path:
                add(
                    "module_dependency",
                    f"module:{source_path}",
                    f"module:{target_path}",
                )
            else:
                unresolved.append(
                    f"module_dependency:module:{source_path}->{dependency}"
                )
    route_paths = set(evidence.get("route_paths", []))
    for record in evidence.get("global_source_fingerprints", []):
        if not isinstance(record, Mapping) or not record.get("path"):
            continue
        path = str(record["path"])
        capabilities = capabilities_for_path(bundle, path)
        for capability_id in capabilities:
            add(
                "source_capability",
                f"source:{path}",
                f"capability:{capability_id}",
            )
        if path in route_paths and not capabilities:
            unresolved.append(f"source_capability:source:{path}->unindexed")
    return dict(sorted(edges.items())), sorted(set(unresolved))


def _affected_nodes(
    seeds: set[str],
    current_edges: Mapping[str, Mapping[str, str]],
    previous_edges: Mapping[str, Mapping[str, str]],
) -> list[str]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in [*current_edges.values(), *previous_edges.values()]:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source and target:
            adjacency[source].add(target)
            adjacency[target].add(source)
    affected = set(seeds)
    pending = list(seeds)
    while pending:
        node = pending.pop()
        for neighbor in adjacency.get(node, set()):
            if neighbor not in affected:
                affected.add(neighbor)
                pending.append(neighbor)
    return sorted(affected)


def update_incremental_snapshot(
    runtime_root: Path,
    *,
    repo_id: str,
    bundle: Mapping[str, Any],
    evidence: Mapping[str, Any],
    route_capabilities: Iterable[str],
) -> dict[str, Any]:
    nodes: dict[str, str] = {}
    for record in evidence.get("global_source_fingerprints", []):
        if isinstance(record, Mapping) and record.get("path"):
            nodes[f"source:{record['path']}"] = digest_value(record)
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        capability_id = str(capability.get("id", ""))
        if capability_id:
            nodes[f"capability:{capability_id}"] = digest_value(capability)
    for module in bundle.get("module_map", {}).get("modules", []):
        module_path = str(module.get("path", ""))
        if module_path:
            nodes[f"module:{module_path}"] = digest_value(module)
    snapshot_root = Path(runtime_root) / "incremental-snapshots"
    snapshot_path = snapshot_root / f"{repo_id}.json"
    previous: dict[str, Any] = {}
    if snapshot_path.is_file():
        try:
            previous = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            previous = {}
    previous_nodes = dict(previous.get("nodes", {}))
    edges, unresolved_edges = _graph_edges(bundle, evidence)
    previous_edges = dict(previous.get("edges", {}))
    reused = sorted(
        node for node, digest in nodes.items() if previous_nodes.get(node) == digest
    )
    recomputed = sorted(
        node for node, digest in nodes.items() if previous_nodes.get(node) != digest
    )
    invalidated = sorted(set(previous_nodes) - set(nodes))
    changed_edges = {
        edge_id
        for edge_id, edge in edges.items()
        if previous_edges.get(edge_id) != edge
    }
    removed_edges = set(previous_edges) - set(edges)
    affected_seeds = set(recomputed) | set(invalidated)
    for edge_id in changed_edges | removed_edges:
        edge = edges.get(edge_id) or previous_edges.get(edge_id, {})
        affected_seeds.update(
            value
            for value in (edge.get("source"), edge.get("target"))
            if value
        )
    affected = _affected_nodes(affected_seeds, edges, previous_edges)
    closure = sorted(
        build_capability_closure(bundle, set(str(item) for item in route_capabilities))
    )
    snapshot = {
        "schema_version": 1,
        "repo_id": repo_id,
        "input_digest": evidence.get("input_digest"),
        "nodes": dict(sorted(nodes.items())),
        "edges": edges,
        "unresolved_edges": unresolved_edges,
        "route_capability_closure": closure,
    }
    snapshot["snapshot_digest"] = digest_value(snapshot)
    _atomic_json(snapshot_path, snapshot)
    return {
        "snapshot_path": str(snapshot_path),
        "snapshot_digest": snapshot["snapshot_digest"],
        "node_count": len(nodes),
        "reused_node_count": len(reused),
        "recomputed_node_count": len(recomputed),
        "invalidated_node_count": len(invalidated),
        "edge_count": len(edges),
        "reused_edge_count": sum(
            previous_edges.get(edge_id) == edge for edge_id, edge in edges.items()
        ),
        "recomputed_edge_count": len(changed_edges),
        "invalidated_edge_count": len(removed_edges),
        "unresolved_node_count": len(unresolved_edges),
        "reused_nodes": reused,
        "recomputed_nodes": recomputed,
        "invalidated_nodes": invalidated,
        "affected_node_count": len(affected),
        "affected_nodes": affected,
        "unresolved_nodes": unresolved_edges,
        "route_capability_closure": closure,
    }
