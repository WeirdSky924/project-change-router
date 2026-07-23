from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from router_support.generated_output_baseline.write_guard import (
    assess_generated_output_write,
)
from router_support.generated_output_baseline.write_policy import (
    generated_output_write_policy,
)
from router_support.freshness_checks import canonical_bundle_snapshot_paths


@dataclass(frozen=True)
class IndexRebuildOperations:
    resolve_bundle_root: Callable[[Path], Path]
    load_bundle: Callable[[Path], dict[str, Any]]
    load_profile: Callable[[Path], dict[str, Any]]
    build_bundle: Callable[[Path, bool], dict[str, Any]]
    create_bundle_directory: Callable[[Path], Path]
    write_bundle: Callable[..., None]
    prepare_preserved_bundle: Callable[..., dict[str, Any]]
    copy_schemas: Callable[[Path], None]
    build_snapshot: Callable[..., Any]
    ignore_patterns: Callable[[dict[str, Any]], list[str]]
    capability_conflicts: Callable[[dict[str, Any]], list[str]]
    write_report: Callable[[Path, dict[str, Any]], None]
    report_id: Callable[[], str]
    timestamp: Callable[[], str]


def rebuild_router_index(
    repo_root: Path,
    *,
    write_back: bool,
    operations: IndexRebuildOperations,
    generated_output_initialization_fingerprint: str | None = None,
) -> dict[str, Any]:
    bundle_root = operations.resolve_bundle_root(repo_root)
    existing = operations.load_bundle(bundle_root) if bundle_root.exists() else {}
    profile = operations.load_profile(repo_root)
    preflight = generated_output_write_policy(repo_root, profile)
    rebuild_error: str | None = None
    try:
        rebuilt = operations.build_bundle(repo_root, write_back)
    except Exception as exc:
        if not preflight.protected:
            raise
        rebuilt = existing
        rebuild_error = f"{type(exc).__name__}: {exc}"
    rebuilt["root"] = bundle_root
    decision = assess_generated_output_write(
        repo_root,
        profile,
        None if rebuild_error else rebuilt,
        initialization_fingerprint=(
            generated_output_initialization_fingerprint
        ),
        rebuild_error=rebuild_error,
    )

    existing_modules = {
        item["path"]
        for item in existing.get("module_map", {}).get("modules", [])
        if isinstance(item, dict) and item.get("path")
    }
    new_modules = {
        item["path"]
        for item in rebuilt.get("module_map", {}).get("modules", [])
        if isinstance(item, dict) and item.get("path")
    }
    stale_entries = [
        {"path": path, "kind": "module"}
        for path in sorted(existing_modules - new_modules)
    ]
    missing_paths = [
        item["path"]
        for item in rebuilt.get("module_map", {}).get("modules", [])
        if isinstance(item, dict)
        and item.get("path")
        and item.get("status", "active") != "planned"
        and not (repo_root / item["path"]).exists()
        and item["path"] != "."
    ]

    write_performed = bool(write_back and decision.write_allowed)
    if write_performed:
        rebuilt = operations.prepare_preserved_bundle(
            rebuilt,
            existing,
            decision.preserve_bundle_keys,
        )
        operations.create_bundle_directory(repo_root)
        operations.write_bundle(
            bundle_root,
            rebuilt,
            preserve_bundle_keys=decision.preserve_bundle_keys,
        )
        operations.copy_schemas(bundle_root)
    snapshot = operations.build_snapshot(
        repo_root,
        operations.ignore_patterns(rebuilt.get("config", {})),
        required_patterns=canonical_bundle_snapshot_paths(
            repo_root,
            bundle_root,
        ),
    )
    mapped_path_patterns = sorted(
        str(item.get("path_pattern"))
        for item in rebuilt.get("path_to_capability_map", {}).get(
            "path_index", []
        )
        if isinstance(item, dict) and item.get("path_pattern")
    )
    conflicts = operations.capability_conflicts(rebuilt)
    generated_findings = list(decision.findings)
    failed = bool(
        missing_paths
        or conflicts
        or stale_entries
        or snapshot.diagnostics
        or generated_findings
    )
    report = {
        "report_id": operations.report_id(),
        "timestamp": operations.timestamp(),
        "source_commit": snapshot.source_commit,
        "structure_digest": snapshot.digest,
        "indexed_paths": list(snapshot.paths),
        "mapped_path_patterns": mapped_path_patterns,
        "diagnostics": list(snapshot.diagnostics),
        "generated_modules_count": len(new_modules),
        "curated_entries_count": len(
            rebuilt.get("capability_catalog", {}).get("capabilities", [])
        ),
        "conflicts": conflicts,
        "stale_entries": stale_entries,
        "missing_paths": missing_paths,
        "preserved_generated_output_keys": sorted(
            decision.preserve_bundle_keys
        ),
        "generated_output_evidence": list(decision.evidence),
        "generated_output_findings": generated_findings,
        "generated_output_write_state": (
            "blocked"
            if decision.policy.protected and not decision.write_allowed
            else "preserved_verified"
            if decision.policy.protected
            else "not_configured"
        ),
        "write_performed": write_performed,
        "status": "fail" if failed else "pass",
    }
    if write_performed:
        operations.write_report(
            bundle_root / "reports" / "index-rebuild" / "latest.json",
            report,
        )
    return report
