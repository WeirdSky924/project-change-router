from __future__ import annotations

import fnmatch
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from router_support.repository_surfaces import is_within_standard_repository_surface
from router_support.structure_growth import _is_governed_code_bearing_path


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


def build_structure_snapshot(repo_root: Path, ignored: Iterable[str]) -> StructureSnapshot:
    root = repo_root.resolve()
    source_commit, commit_error = _source_commit(root)
    repository_paths, scan_diagnostics = _repository_paths(root)
    user_ignored = tuple(str(pattern) for pattern in ignored)
    exclusions = user_ignored + PROGRESS_OR_REPORT_PATTERNS
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
        if not _structure_relevant(root, rel_path) or _matches(rel_path, exclusions):
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


def assess_index_freshness(
    current: StructureSnapshot,
    indexed: Mapping[str, object],
    changed_paths: Iterable[str] = (),
) -> dict[str, object]:
    current_paths = tuple(sorted(current.paths))
    indexed_paths = tuple(sorted(str(path) for path in indexed.get("indexed_paths", []) or []))
    stale_entries = list(indexed.get("stale_entries", []) or [])
    mapped_patterns = tuple(str(pattern) for pattern in indexed.get("mapped_path_patterns", []) or [])
    normalized_changes = tuple(sorted({_normalized(path) for path in changed_paths if _normalized(path)}))
    unmapped = tuple(path for path in normalized_changes if not _matches(path, mapped_patterns))
    excluded_changes = tuple(
        path for path in normalized_changes if _matches(path, current.ignored_patterns)
    )
    checks = [
        _check(
            "source_commit",
            bool(current.source_commit) and current.source_commit == indexed.get("source_commit"),
            {"current": current.source_commit, "indexed": indexed.get("source_commit")},
        ),
        _check(
            "structure_digest",
            bool(indexed.get("structure_digest")) and current.digest == indexed.get("structure_digest"),
            {"current": current.digest, "indexed": indexed.get("structure_digest")},
        ),
        _check(
            "indexed_paths",
            current_paths == indexed_paths,
            {
                "missing_from_index": sorted(set(current_paths) - set(indexed_paths)),
                "stale_in_index": sorted(set(indexed_paths) - set(current_paths)),
            },
        ),
        _check("stale_entries", not stale_entries, {"entries": stale_entries}),
        _check("changed_path_coverage", not unmapped, {"unmapped": list(unmapped)}),
        _check(
            "changed_path_snapshot_coverage",
            not excluded_changes,
            {"excluded": list(excluded_changes)},
        ),
        _check("snapshot_diagnostics", not current.diagnostics, {"diagnostics": list(current.diagnostics)}),
    ]
    failure_reasons = [str(check["name"]) for check in checks if not check["passed"]]
    return {
        "status": "pass" if not failure_reasons else "fail",
        "checks": checks,
        "failure_reasons": failure_reasons,
        "changed_paths": list(normalized_changes),
        "unmapped_changed_paths": list(unmapped),
        "excluded_changed_paths": list(excluded_changes),
        "stale_entries": stale_entries,
        "source_commit": current.source_commit,
        "structure_digest": current.digest,
        "indexed_paths": list(current_paths),
        "diagnostics": list(current.diagnostics),
    }
