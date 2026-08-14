from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import subprocess
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from router_support.repository_surfaces import is_within_standard_repository_surface
from router_support.structure_growth import (
    _is_governed_code_bearing_path,
    git_commit_is_ancestor,
    resolve_git_commit,
)


STRUCTURE_SUFFIXES = {
    ".cjs",
    ".css",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".scss",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
DISCOVERY_MANIFEST_NAMES = {
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "pom.xml",
    "settings.gradle",
    "settings.gradle.kts",
}
PROGRESS_OR_REPORT_PATTERNS = (
    ".agent-handoff/**",
    ".claude/CLAUDE.md",
    ".git/**",
    "docs/gap/**",
    "docs/superpowers/plans/**",
    "project-change-router/reports/**",
)


@dataclass(frozen=True)
class StructureSnapshot:
    source_commit: str | None
    digest: str
    paths: tuple[str, ...]
    diagnostics: tuple[str, ...]
    ignored_patterns: tuple[str, ...] = ()


def _normalized(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").strip("/")


def _matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = _normalized(path)
    for raw_pattern in patterns:
        pattern = _normalized(str(raw_pattern))
        if not pattern:
            continue
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        if pattern.endswith("/"):
            candidates.append(pattern + "**")
        if any(fnmatch.fnmatchcase(normalized, candidate) for candidate in candidates):
            return True
    return False


def _git(repo_root: Path, *args: str) -> tuple[str, str | None]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return "", str(exc)
    return result.stdout, None


def _source_commit(repo_root: Path) -> tuple[str | None, str | None]:
    output, error = _git(repo_root, "rev-parse", "HEAD")
    commit = output.strip()
    return (commit or None), error


def _repository_paths(repo_root: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    output, error = _git(repo_root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if error is None:
        return tuple(sorted({_normalized(item) for item in output.split("\0") if item})), ()
    paths = tuple(
        sorted(
            path.relative_to(repo_root).as_posix()
            for path in repo_root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(repo_root).parts
        )
    )
    return paths, (f"git-ls-files-error:{error}",)


def _structure_relevant(repo_root: Path, path: str) -> bool:
    normalized = _normalized(path)
    source = repo_root / normalized
    governed_code_bearing = _is_governed_code_bearing_path(normalized, source)
    if source.suffix.lower() == ".json":
        return governed_code_bearing
    return (
        source.suffix.lower() in STRUCTURE_SUFFIXES
        or governed_code_bearing
        or source.name in DISCOVERY_MANIFEST_NAMES
        or is_within_standard_repository_surface(normalized)
    )


def build_structure_snapshot(
    repo_root: Path,
    ignored: Iterable[str],
    *,
    required_patterns: Iterable[str] = (),
) -> StructureSnapshot:
    root = repo_root.resolve()
    source_commit, commit_error = _source_commit(root)
    repository_paths, scan_diagnostics = _repository_paths(root)
    user_ignored = tuple(str(pattern) for pattern in ignored)
    required = tuple(str(pattern) for pattern in required_patterns)
    digest = hashlib.sha256()
    included: list[str] = []
    diagnostics = list(scan_diagnostics)
    if commit_error:
        diagnostics.append(f"git-rev-parse-error:{commit_error}")
    global_ignores = {
        _normalized(pattern)
        for pattern in user_ignored
        if _matches("src/pcr_freshness_probe.py", (pattern,))
        and _matches("nested/pcr_freshness_probe.ts", (pattern,))
    }
    diagnostics.extend(
        f"unsafe-global-ignore-pattern:{pattern}" for pattern in sorted(global_ignores)
    )
    governable_paths = [
        path
        for path in repository_paths
        if _structure_relevant(root, path)
        and not _matches(path, PROGRESS_OR_REPORT_PATTERNS)
    ]
    if governable_paths and all(_matches(path, user_ignored) for path in governable_paths):
        diagnostics.append("unsafe-ignore-coverage:all-structure-relevant-paths")
    for rel_path in repository_paths:
        if not _structure_relevant(root, rel_path):
            continue
        if _matches(rel_path, PROGRESS_OR_REPORT_PATTERNS):
            continue
        if _matches(rel_path, user_ignored) and not _matches(rel_path, required):
            continue
        path = root / rel_path
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError as exc:
            diagnostics.append(f"read-error:{rel_path}:{exc}")
            continue
        included.append(rel_path)
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return StructureSnapshot(
        source_commit=source_commit,
        digest=digest.hexdigest(),
        paths=tuple(included),
        diagnostics=tuple(sorted(diagnostics)),
        ignored_patterns=user_ignored,
    )


def collect_git_changed_paths(
    repo_root: Path, comparison_commit: str | None = None
) -> tuple[str, ...]:
    commands = (
        ("diff", "--name-only", "--diff-filter=ACDMRTUXB"),
        ("diff", "--cached", "--name-only", "--diff-filter=ACDMRTUXB"),
        ("ls-files", "--others", "--exclude-standard"),
    )
    paths: set[str] = set()
    if comparison_commit:
        output, error = _git(
            repo_root.resolve(),
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            f"{comparison_commit}..HEAD",
        )
        if error is not None:
            raise RuntimeError(f"comparison-commit-diff-error:{error}")
        paths.update(_normalized(item) for item in output.splitlines() if item.strip())
    for command in commands:
        output, error = _git(repo_root.resolve(), *command)
        if error is not None:
            continue
        paths.update(_normalized(item) for item in output.splitlines() if item.strip())
    return tuple(sorted(paths))


def _check(name: str, passed: bool, details: Mapping[str, object]) -> dict[str, object]:
    return {"name": name, "passed": passed, "details": dict(details)}


def _normalized_indexed_snapshot(indexed: object) -> dict[str, object]:
    if not isinstance(indexed, Mapping):
        error = "latest report root must be a JSON object"
        return {
            "status": "fail",
            "diagnostics": [f"indexed_snapshot_schema:{error}"],
            "indexed_paths": [],
            "mapped_path_patterns": [],
            "stale_entries": [],
            "_schema_errors": [error],
        }
    normalized = dict(indexed)
    prior_errors = normalized.get("_schema_errors", [])
    errors = (
        [str(item) for item in prior_errors]
        if isinstance(prior_errors, list)
        else []
    )
    for field in ("indexed_paths", "mapped_path_patterns", "diagnostics"):
        value = normalized.get(field, [])
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            errors.append(f"{field} must be an array of strings")
            normalized[field] = []
    stale_entries = normalized.get("stale_entries", [])
    if not isinstance(stale_entries, list) or any(
        not isinstance(item, Mapping) for item in stale_entries
    ):
        errors.append("stale_entries must be an array of objects")
        normalized["stale_entries"] = []
    for field, expected in (
        ("source_commit", (str, type(None))),
        ("structure_digest", (str,)),
        ("status", (str,)),
    ):
        if field in normalized and not isinstance(normalized[field], expected):
            errors.append(f"{field} has an invalid JSON type")
            normalized[field] = None
    if errors:
        diagnostics = list(normalized.get("diagnostics", []))
        diagnostics.extend(f"indexed_snapshot_schema:{item}" for item in errors)
        normalized["diagnostics"] = diagnostics
        normalized["status"] = "fail"
    normalized["_schema_errors"] = errors
    return normalized


def assess_index_freshness(
    current: StructureSnapshot,
    indexed: object,
    changed_paths: Iterable[str] = (),
    *,
    source_commit_is_ancestor: bool = False,
    system_path_patterns: Iterable[str] = (),
    snapshot_exempt_path_patterns: Iterable[str] = (),
) -> dict[str, object]:
    indexed = _normalized_indexed_snapshot(indexed)
    schema_errors = list(indexed.get("_schema_errors", []))
    current_paths = tuple(sorted(current.paths))
    indexed_paths = tuple(sorted(str(path) for path in indexed.get("indexed_paths", []) or []))
    stale_entries = list(indexed.get("stale_entries", []) or [])
    indexed_diagnostics = list(indexed.get("diagnostics", []) or [])
    indexed_status_passes = indexed.get("status") == "pass"
    mapped_patterns = tuple(str(pattern) for pattern in indexed.get("mapped_path_patterns", []) or [])
    normalized_changes = tuple(sorted({_normalized(path) for path in changed_paths if _normalized(path)}))
    system_patterns = tuple(str(pattern) for pattern in system_path_patterns)
    snapshot_exempt_patterns = tuple(
        str(pattern) for pattern in snapshot_exempt_path_patterns
    )
    system_managed = tuple(
        path for path in normalized_changes if _matches(path, system_patterns)
    )
    snapshot_exempt = tuple(
        path
        for path in normalized_changes
        if _matches(path, snapshot_exempt_patterns)
    )
    unverified_system_managed = tuple(
        path
        for path in system_managed
        if path not in current_paths
        and not _matches(path, snapshot_exempt_patterns)
    )
    unmapped = tuple(
        path for path in normalized_changes
        if not _matches(path, (*mapped_patterns, *system_patterns))
    )
    excluded_changes = tuple(
        path for path in normalized_changes
        if _matches(path, current.ignored_patterns)
        and path not in current_paths
        and not _matches(path, snapshot_exempt_patterns)
    )
    structure_digest_matches = (
        bool(indexed.get("structure_digest"))
        and current.digest == indexed.get("structure_digest")
    )
    indexed_paths_match = current_paths == indexed_paths
    snapshot_is_exact = (
        structure_digest_matches
        and indexed_paths_match
        and not stale_entries
        and not current.diagnostics
        and not indexed_diagnostics
        and indexed_status_passes
    )
    source_commit_matches = (
        bool(current.source_commit)
        and current.source_commit == indexed.get("source_commit")
    )
    source_commit_passes = source_commit_matches or (
        source_commit_is_ancestor and snapshot_is_exact
    )
    source_match_mode = (
        "exact"
        if source_commit_matches
        else "ancestor_exact_snapshot"
        if source_commit_passes
        else "mismatch"
    )
    checks = [
        _check(
            "indexed_snapshot_schema",
            not schema_errors,
            {"errors": schema_errors},
        ),
        _check(
            "source_commit",
            source_commit_passes,
            {
                "current": current.source_commit,
                "indexed": indexed.get("source_commit"),
                "match_mode": source_match_mode,
            },
        ),
        _check(
            "structure_digest",
            structure_digest_matches,
            {"current": current.digest, "indexed": indexed.get("structure_digest")},
        ),
        _check(
            "indexed_paths",
            indexed_paths_match,
            {
                "missing_from_index": sorted(set(current_paths) - set(indexed_paths)),
                "stale_in_index": sorted(set(indexed_paths) - set(current_paths)),
            },
        ),
        _check("stale_entries", not stale_entries, {"entries": stale_entries}),
        _check("changed_path_coverage", not unmapped, {"unmapped": list(unmapped)}),
        _check(
            "system_managed_snapshot_coverage",
            not unverified_system_managed,
            {"unverified": list(unverified_system_managed)},
        ),
        _check(
            "changed_path_snapshot_coverage",
            not excluded_changes,
            {"excluded": list(excluded_changes)},
        ),
        _check(
            "indexed_snapshot_status",
            indexed_status_passes,
            {"status": indexed.get("status")},
        ),
        _check(
            "indexed_snapshot_diagnostics",
            not indexed_diagnostics,
            {"diagnostics": indexed_diagnostics},
        ),
        _check("snapshot_diagnostics", not current.diagnostics, {"diagnostics": list(current.diagnostics)}),
    ]
    failure_reasons = [str(check["name"]) for check in checks if not check["passed"]]
    return {
        "status": "pass" if not failure_reasons else "fail",
        "checks": checks,
        "failure_reasons": failure_reasons,
        "changed_paths": list(normalized_changes),
        "system_managed_changed_paths": list(system_managed),
        "snapshot_exempt_changed_paths": list(snapshot_exempt),
        "unverified_system_managed_changed_paths": list(
            unverified_system_managed
        ),
        "unmapped_changed_paths": list(unmapped),
        "excluded_changed_paths": list(excluded_changes),
        "stale_entries": stale_entries,
        "source_commit": current.source_commit,
        "structure_digest": current.digest,
        "indexed_paths": list(current_paths),
        "diagnostics": list(current.diagnostics),
    }


def _relative_bundle_root(repo_root: Path, bundle_root: Path) -> str | None:
    try:
        return bundle_root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def canonical_bundle_snapshot_paths(
    repo_root: Path,
    bundle_root: Path,
) -> tuple[str, ...]:
    relative_root = _relative_bundle_root(repo_root, bundle_root)
    if relative_root is None:
        return ()
    return (
        f"{relative_root}/router-config.yaml",
        f"{relative_root}/references/capability-catalog.yaml",
        f"{relative_root}/references/module-map.yaml",
        f"{relative_root}/references/ownership.yaml",
        f"{relative_root}/references/change-rules.yaml",
        f"{relative_root}/references/path-to-capability-map.yaml",
        f"{relative_root}/references/exception-registry.yaml",
        f"{relative_root}/references/evaluation-set.yaml",
        f"{relative_root}/schemas/**",
    )


def canonical_bundle_report_paths(
    repo_root: Path,
    bundle_root: Path,
) -> tuple[str, ...]:
    relative_root = _relative_bundle_root(repo_root, bundle_root)
    if relative_root is None:
        return ()
    return (
        f"{relative_root}/reports/index-rebuild/latest.json",
    )


def canonical_bundle_system_paths(
    repo_root: Path,
    bundle_root: Path,
) -> tuple[str, ...]:
    return (
        *canonical_bundle_snapshot_paths(repo_root, bundle_root),
        *canonical_bundle_report_paths(repo_root, bundle_root),
    )


def repository_freshness_report(
    repo_root: Path,
    bundle_root: Path,
    ignored_patterns: Iterable[str],
    changed_paths: Iterable[str] | None,
) -> dict[str, object]:
    latest_path = bundle_root / "reports" / "index-rebuild" / "latest.json"
    try:
        indexed = (
            json.loads(latest_path.read_text(encoding="utf-8"))
            if latest_path.exists()
            else {}
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        indexed = {"diagnostics": [f"latest-report-error:{exc}"]}
    indexed = _normalized_indexed_snapshot(indexed)
    snapshot = build_structure_snapshot(
        repo_root,
        ignored_patterns,
        required_patterns=canonical_bundle_snapshot_paths(
            repo_root,
            bundle_root,
        ),
    )
    requested_changes = {
        _normalized(path) for path in (changed_paths or ()) if _normalized(path)
    }
    repository_changes = set(collect_git_changed_paths(repo_root))
    indexed_source = str(indexed.get("source_commit") or "")
    current_source = str(snapshot.source_commit or "")
    source_is_ancestor = False
    comparison_delta_complete = bool(
        indexed_source
        and current_source
        and indexed_source == current_source
    )
    if indexed_source and current_source and indexed_source != current_source:
        try:
            if not re.fullmatch(r"[0-9a-f]{40}(?:[0-9a-f]{24})?", indexed_source):
                raise ValueError("indexed source commit is not a full object id")
            resolved_indexed = resolve_git_commit(repo_root, indexed_source)
            resolved_current = resolve_git_commit(repo_root, current_source)
            if resolved_indexed != indexed_source or resolved_current != current_source:
                raise ValueError("freshness source commits must be immutable object ids")
            source_is_ancestor = git_commit_is_ancestor(
                repo_root, resolved_indexed, resolved_current
            )
            if source_is_ancestor:
                repository_changes.update(
                    collect_git_changed_paths(repo_root, resolved_indexed)
                )
                comparison_delta_complete = True
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError):
            source_is_ancestor = False
    effective_changes = repository_changes | requested_changes
    assessment = assess_index_freshness(
        snapshot,
        indexed,
        effective_changes,
        source_commit_is_ancestor=source_is_ancestor,
        system_path_patterns=canonical_bundle_system_paths(repo_root, bundle_root),
        snapshot_exempt_path_patterns=canonical_bundle_report_paths(
            repo_root,
            bundle_root,
        ),
    )
    timestamp = (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "report_id": f"freshness-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "timestamp": timestamp,
        **assessment,
        "requested_changed_paths": sorted(requested_changes),
        "repository_changed_paths": sorted(repository_changes),
        "comparison_delta_complete": comparison_delta_complete,
        "missing_references": [] if latest_path.exists() else [
            str(latest_path.relative_to(repo_root))
        ],
    }
