from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


CODE_SUFFIXES = {
    ".c", ".cc", ".cjs", ".cpp", ".css", ".go", ".html", ".java",
    ".js", ".jsx", ".kt", ".kts", ".mjs", ".scss", ".py", ".rs",
    ".sh", ".sql", ".toml", ".ts", ".tsx", ".vue", ".yaml", ".yml",
}
NON_CODE_JSON_PREFIXES = (
    "audit/reports/",
    "audit/state/",
    "project-change-router/reports/",
)
NON_CODE_JSON_NAMES = {".refactor_progress.json"}
RUNTIME_MARKDOWN_DIRECTORIES = {"prompts", "skills"}
BUILD_FILE_NAMES = {"Dockerfile", "GNUmakefile", "Makefile", "Procfile"}
DEPENDENCY_MANIFEST_NAMES = {"uv.lock"}
FILE_SIZE_THRESHOLDS = (800, 1200)
DIRECTORY_WIDTH_THRESHOLD = 25
SAME_PREFIX_THRESHOLD = 8

OptionalBaselineLoader = Callable[[Path, str, str], str | None]
ChangedPathLoader = Callable[[Path], Iterable[str]]


@dataclass(frozen=True)
class FileSizeChange:
    current_path: str
    baseline_path: str | None


def resolve_git_commit(repo_root: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git revision is unavailable"
        raise RuntimeError(f"{revision}: {detail}")
    return result.stdout.strip()


def git_commit_is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = result.stderr.strip() or result.stdout.strip() or "git ancestry check failed"
    raise RuntimeError(detail)


def blocking_finding(
    rule: str,
    source: str,
    message: str,
    *,
    severity: str = "P1",
    **details: Any,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "rule": rule,
        "source": source,
        "blocking": True,
        "baseline_status": "new",
        "message": message,
        **details,
    }


def diagnostic(source: str, message: str, **details: Any) -> dict[str, Any]:
    return blocking_finding(
        "structure-baseline-diagnostic",
        source,
        message,
        severity="P0",
        **details,
    )


def _debt_finding(
    rule: str,
    source: str,
    message: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "severity": "P2",
        "rule": rule,
        "source": source,
        "blocking": False,
        "baseline_status": "existing_debt",
        "message": message,
        **details,
    }


def load_optional_git_source(
    repo_root: Path,
    commit: str,
    path: str,
) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    commit_check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if commit_check.returncode != 0:
        raise RuntimeError(commit_check.stderr.strip() or "baseline commit is missing")
    path_check = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if path_check.returncode != 0:
        return None
    raise RuntimeError(result.stderr.strip() or "git show failed")


def _normalize_repo_path(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./")


def _is_governed_code_bearing_path(source_path: str, path: Path | None = None) -> bool:
    normalized = _normalize_repo_path(source_path)
    source = Path(normalized)
    suffix = source.suffix.lower()
    if suffix in CODE_SUFFIXES:
        return True
    if suffix == ".json":
        return source.name not in NON_CODE_JSON_NAMES and not any(
            normalized.startswith(prefix) for prefix in NON_CODE_JSON_PREFIXES
        )
    if suffix == ".md":
        return bool(RUNTIME_MARKDOWN_DIRECTORIES.intersection(normalized.split("/")))
    if source.name.startswith(".env") and source.name.endswith(".example"):
        return True
    if source.name.startswith("requirements") and suffix == ".txt":
        return True
    if source.name in DEPENDENCY_MANIFEST_NAMES:
        return True
    if source.name in BUILD_FILE_NAMES or source.name.startswith("Dockerfile."):
        return True
    return bool(path and path.is_file() and path.stat().st_mode & 0o111)


def _git_nul_output(repo_root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(detail)
    return result.stdout.rstrip("\0").split("\0") if result.stdout else []


def collect_file_size_changes(
    repo_root: Path,
    comparison_commit: str,
) -> tuple[FileSizeChange, ...]:
    fields = _git_nul_output(
        repo_root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        "--find-copies",
        comparison_commit,
        "--",
    )
    changes: dict[str, FileSizeChange] = {}
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if not status:
            continue
        kind = status[0]
        if kind in {"R", "C"}:
            if index + 1 >= len(fields):
                raise RuntimeError(f"malformed git diff record for status {status!r}")
            source_path = _normalize_repo_path(fields[index])
            current_path = _normalize_repo_path(fields[index + 1])
            baseline_path = source_path if kind == "R" else None
            index += 2
        else:
            if index >= len(fields):
                raise RuntimeError(f"malformed git diff record for status {status!r}")
            current_path = _normalize_repo_path(fields[index])
            index += 1
            if kind == "D":
                continue
            if kind not in {"A", "M", "T", "U", "X", "B"}:
                raise RuntimeError(f"unsupported git diff status {status!r}")
            baseline_path = None if kind == "A" else current_path
        changes[current_path] = FileSizeChange(current_path, baseline_path)

    for raw_path in _git_nul_output(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    ):
        current_path = _normalize_repo_path(raw_path)
        if current_path:
            changes[current_path] = FileSizeChange(current_path, None)
    return tuple(changes[path] for path in sorted(changes))


def _gather_file_growth_findings(
    repo_root: Path,
    comparison_commit: str,
    changed_path_loader: ChangedPathLoader | None,
    baseline_loader: OptionalBaselineLoader,
) -> list[dict[str, Any]]:
    try:
        changes = (
            collect_file_size_changes(repo_root, comparison_commit)
            if changed_path_loader is None
            else tuple(
                FileSizeChange(
                    _normalize_repo_path(str(path)),
                    _normalize_repo_path(str(path)),
                )
                for path in changed_path_loader(repo_root)
            )
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return [diagnostic(
            "<git-changes>",
            "Changed code paths could not be measured for structure growth.",
            error=str(exc),
        )]

    findings: list[dict[str, Any]] = []
    for change in changes:
        source_path = change.current_path
        current_path = repo_root / source_path
        if not current_path.is_file() or not _is_governed_code_bearing_path(
            source_path, current_path
        ):
            continue
        try:
            current_lines = len(current_path.read_text(encoding="utf-8").splitlines())
            baseline_source = (
                baseline_loader(repo_root, comparison_commit, change.baseline_path)
                if change.baseline_path is not None
                else None
            )
            baseline_lines = len((baseline_source or "").splitlines())
        except (OSError, UnicodeError, RuntimeError) as exc:
            findings.append(diagnostic(
                source_path,
                "A changed code file could not be measured against its size baseline.",
                error=str(exc),
            ))
            continue
        crossed = [
            threshold
            for threshold in FILE_SIZE_THRESHOLDS
            if baseline_lines < threshold <= current_lines
        ]
        details = {
            "source_commit": comparison_commit,
            "baseline_path": change.baseline_path,
            "baseline_lines": baseline_lines,
            "current_lines": current_lines,
        }
        if crossed:
            findings.append(blocking_finding(
                "code-file-size-threshold-crossing",
                source_path,
                "A changed code file crossed a governed size threshold.",
                crossed_thresholds=crossed,
                **details,
            ))
        elif current_lines > baseline_lines >= 1200:
            findings.append(blocking_finding(
                "code-file-size-hard-growth",
                source_path,
                "A 1200+ line code file grew beyond its comparison baseline.",
                severity="P0",
                growth_policy="hard_fail",
                **details,
            ))
        elif current_lines > baseline_lines >= 800:
            findings.append(blocking_finding(
                "code-file-size-review-growth",
                source_path,
                "An 800-1199 line code file grew and requires structural review.",
                growth_policy="review",
                **details,
            ))
    return findings


def _current_code_paths(repo_root: Path) -> set[str]:
    paths = _git_nul_output(
        repo_root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    return {
        normalized
        for raw_path in paths
        if (normalized := _normalize_repo_path(raw_path))
        and (repo_root / normalized).is_file()
        and _is_governed_code_bearing_path(normalized, repo_root / normalized)
    }


def _baseline_code_paths(repo_root: Path, comparison_commit: str) -> set[str]:
    paths: set[str] = set()
    for record in _git_nul_output(
        repo_root,
        "ls-tree",
        "-r",
        "-z",
        comparison_commit,
    ):
        metadata, separator, raw_path = record.partition("\t")
        if not separator:
            raise RuntimeError(f"malformed git tree record {record!r}")
        normalized = _normalize_repo_path(raw_path)
        mode = metadata.split(" ", 1)[0]
        if normalized and (
            _is_governed_code_bearing_path(normalized) or mode == "100755"
        ):
            paths.add(normalized)
    return paths


def _directory_counts(paths: Iterable[str]) -> Counter[str]:
    return Counter(
        Path(path).parent.as_posix()
        for path in paths
    )


def _same_prefix_counts(paths: Iterable[str]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for path in paths:
        stem = Path(path).stem
        parts = [part for part in re.split(r"[_-]+", stem) if part]
        if len(parts) > 1:
            counts[(Path(path).parent.as_posix(), parts[0])] += 1
    return counts


def _growth_or_debt(
    *,
    source: str,
    baseline_count: int,
    current_count: int,
    threshold: int,
    growth_rule: str,
    debt_rule: str,
    comparison_commit: str,
    details: dict[str, Any],
) -> dict[str, Any] | None:
    shared = {
        "source_commit": comparison_commit,
        "baseline_count": baseline_count,
        "current_count": current_count,
        "threshold": threshold,
        **details,
    }
    if current_count >= threshold and current_count > baseline_count:
        return blocking_finding(
            growth_rule,
            source,
            "A wide code-bearing sibling set grew beyond its comparison baseline.",
            growth_kind="crossing" if baseline_count < threshold else "growth",
            **shared,
        )
    if current_count >= threshold:
        return _debt_finding(
            debt_rule,
            source,
            "Existing wide code-bearing sibling debt remains visible.",
            **shared,
        )
    return None


def _gather_tree_growth_findings(
    repo_root: Path,
    comparison_commit: str,
) -> list[dict[str, Any]]:
    try:
        baseline_paths = _baseline_code_paths(repo_root, comparison_commit)
        current_paths = _current_code_paths(repo_root)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return [diagnostic(
            "<tree-width>",
            "Code-bearing directory width could not be compared.",
            error=str(exc),
        )]

    findings: list[dict[str, Any]] = []
    baseline_directories = _directory_counts(baseline_paths)
    current_directories = _directory_counts(current_paths)
    for directory in sorted(set(baseline_directories) | set(current_directories)):
        finding = _growth_or_debt(
            source=directory,
            baseline_count=baseline_directories[directory],
            current_count=current_directories[directory],
            threshold=DIRECTORY_WIDTH_THRESHOLD,
            growth_rule="code-directory-width-growth",
            debt_rule="code-directory-width-debt",
            comparison_commit=comparison_commit,
            details={"directory": directory},
        )
        if finding is not None:
            findings.append(finding)

    baseline_prefixes = _same_prefix_counts(baseline_paths)
    current_prefixes = _same_prefix_counts(current_paths)
    for directory, prefix in sorted(set(baseline_prefixes) | set(current_prefixes)):
        finding = _growth_or_debt(
            source=directory,
            baseline_count=baseline_prefixes[(directory, prefix)],
            current_count=current_prefixes[(directory, prefix)],
            threshold=SAME_PREFIX_THRESHOLD,
            growth_rule="same-prefix-sibling-growth",
            debt_rule="same-prefix-sibling-debt",
            comparison_commit=comparison_commit,
            details={"directory": directory, "prefix": prefix},
        )
        if finding is not None:
            findings.append(finding)
    return findings


def gather_growth_findings(
    repo_root: Path,
    bundle: dict[str, Any],
    *,
    comparison_commit: str | None,
    changed_path_loader: ChangedPathLoader | None,
    baseline_loader: OptionalBaselineLoader,
) -> list[dict[str, Any]]:
    commit = str(
        comparison_commit
        or bundle.get("config", {}).get("source_commit")
        or ""
    ).strip()
    if not commit:
        return [diagnostic(
            "<comparison-commit>",
            "Structure growth comparison requires an explicit or bundle source commit.",
            missing_fields=["comparison_commit", "config.source_commit"],
            completion_status="incomplete",
            evidence_complete=False,
        )]
    findings = _gather_file_growth_findings(
        repo_root,
        commit,
        changed_path_loader,
        baseline_loader,
    )
    if changed_path_loader is None:
        findings.extend(_gather_tree_growth_findings(repo_root, commit))
    return findings
