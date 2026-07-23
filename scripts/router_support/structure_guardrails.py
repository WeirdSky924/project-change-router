from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from router_support.central_baseline import (
    CENTRAL_MAX_FIELDS,
    baseline_source_commit_diagnostic as _baseline_source_commit_diagnostic,
    central_rule_weakening_diagnostic as _central_rule_weakening_diagnostic,
    find_python_class_forbidden_source_terms,
    find_python_symbol_forbidden_source_terms,
    measure_python_class,
    measure_python_symbol,
)
from router_support.structure_growth import (
    ChangedPathLoader,
    FILE_SIZE_THRESHOLDS,
    FileSizeChange,
    OptionalBaselineLoader,
    _is_governed_code_bearing_path,
    blocking_finding as _blocking_finding,
    collect_file_size_changes,
    diagnostic as _diagnostic,
    gather_growth_findings,
    load_optional_git_source,
)
from router_support.static_string_scan import (
    static_javascript_strings,
    static_python_strings,
)

BaselineLoader = Callable[[Path, str, str], str]
JAVASCRIPT_STRING_SUFFIXES = {".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
STATIC_STRING_SUFFIXES = {*JAVASCRIPT_STRING_SUFFIXES, ".java"}
STRUCTURE_RULE_COLLECTIONS = (
    "central_growth_baseline",
    "forbidden_implementation_roots",
    "exclusive_source_owners",
)
PROFILE_RULE_MAPPINGS = (
    "dependency_priority",
    "reuse_scan_scope",
    "reuse_scan_budget",
    "reuse_scan_runtime",
    "reuse_scan_retention",
)


def refresh_profile_structure_guardrails(
    existing_rules: dict[str, Any],
    generated_rules: dict[str, Any],
) -> dict[str, Any]:
    """Replace stale generated structure collections with canonical profile truth."""

    refreshed = dict(existing_rules)
    for key in STRUCTURE_RULE_COLLECTIONS:
        refreshed[key] = list(generated_rules.get(key, []))
    for key in PROFILE_RULE_MAPPINGS:
        refreshed[key] = dict(generated_rules.get(key, {}))
    return refreshed


def load_git_source(repo_root: Path, commit: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git show failed"
        raise RuntimeError(detail)
    return result.stdout


def _gather_central_growth_findings(
    repo_root: Path,
    baseline: dict[str, Any],
    baseline_loader: BaselineLoader,
    comparison_commit: str,
    enforce_provenance: bool,
) -> list[dict[str, Any]]:
    required = ("id", "path", "symbol", "source_commit", "owner", "exit_stage")
    missing = [field for field in required if not baseline.get(field)]
    source_path = str(baseline.get("path") or "<missing-path>")
    if missing:
        return [_diagnostic(source_path, "Central-growth baseline is incomplete.", missing_fields=missing)]
    kind = baseline.get("kind")
    if kind not in {"python-class-remove-only", "python-function-remove-only"}:
        return [_diagnostic(source_path, "Central-growth baseline kind is unsupported.", kind=baseline.get("kind"))]
    if enforce_provenance and (
        provenance := _baseline_source_commit_diagnostic(
            repo_root,
            baseline,
            comparison_commit,
            source_path,
        )
    ) is not None:
        return [provenance]
    required_max_fields = {"max_file_lines"}
    if kind == "python-function-remove-only":
        required_max_fields.update(
            {"max_symbol_lines", "max_nested_functions", "max_decorated_handlers"}
        )
    invalid_max_fields = sorted(
        field
        for field in CENTRAL_MAX_FIELDS
        if (field in required_max_fields or field in baseline)
        and (type(baseline.get(field)) is not int or baseline[field] < 0)
    )
    if invalid_max_fields:
        return [
            _diagnostic(
                source_path,
                "Central-growth maxima must be non-negative integers.",
                baseline_id=baseline["id"],
                invalid_max_fields=invalid_max_fields,
            )
        ]
    if enforce_provenance and (
        weakening := _central_rule_weakening_diagnostic(
            repo_root,
            baseline,
            comparison_commit,
            source_path,
        )
    ) is not None:
        return [weakening]

    current_path = repo_root / source_path
    if not current_path.is_file():
        return [_diagnostic(source_path, "Central-growth target file is missing.")]
    try:
        current_source = current_path.read_text(encoding="utf-8")
        baseline_source = baseline_loader(repo_root, str(baseline["source_commit"]), source_path)
        current = measure_python_symbol(current_source, str(baseline["symbol"]), str(kind))
        original = measure_python_symbol(baseline_source, str(baseline["symbol"]), str(kind))
        comparison_measurement = original
        if enforce_provenance:
            comparison_source = baseline_loader(
                repo_root,
                comparison_commit,
                source_path,
            )
            comparison_measurement = measure_python_symbol(
                comparison_source,
                str(baseline["symbol"]),
                str(kind),
            )
    except (OSError, UnicodeError, SyntaxError, RuntimeError, ValueError) as exc:
        return [_diagnostic(source_path, "Central-growth baseline could not be measured.", error=str(exc))]

    tracked_members = set(baseline.get("tracked_members", []))
    measured_maxima = {
        "max_file_lines": len(baseline_source.splitlines()),
        "max_tracked_members_present": len(original["member_names"] & tracked_members),
    }
    if kind == "python-class-remove-only":
        measured_maxima.update(
            max_methods=original["method_count"],
            max_public_methods=original["public_method_count"],
        )
    else:
        measured_maxima.update(
            max_symbol_lines=original["symbol_line_count"],
            max_nested_functions=original["nested_function_count"],
            max_decorated_handlers=original["decorated_handler_count"],
        )
    padded_maxima = {
        field: {"declared": baseline[field], "measured": measured}
        for field, measured in measured_maxima.items()
        if field in baseline and baseline[field] > measured
    }
    if padded_maxima:
        return [
            _diagnostic(
                source_path,
                "Central-growth maxima exceed the comparison source measurement.",
                baseline_id=baseline["id"],
                padded_maxima=padded_maxima,
            )
        ]

    findings: list[dict[str, Any]] = []
    new_members = sorted(
        current["member_names"] - comparison_measurement["member_names"]
    )
    if new_members:
        member_rule = (
            "central-class-member-growth"
            if kind == "python-class-remove-only"
            else "central-function-handler-growth"
        )
        findings.append(
            _blocking_finding(
                member_rule,
                source_path,
                "A remove-only central symbol gained members absent from its committed baseline.",
                baseline_id=baseline["id"],
                owner=baseline["owner"],
                exit_stage=baseline["exit_stage"],
                new_members=new_members,
            )
        )

    metrics = {"file_lines": len(current_source.splitlines())}
    limits = {"file_lines": baseline.get("max_file_lines")}
    if kind == "python-class-remove-only":
        metrics.update(
            methods=current["method_count"],
            public_methods=current["public_method_count"],
        )
        limits.update(
            methods=baseline.get("max_methods"),
            public_methods=baseline.get("max_public_methods"),
        )
    else:
        metrics.update(
            symbol_lines=current["symbol_line_count"],
            nested_functions=current["nested_function_count"],
            decorated_handlers=current["decorated_handler_count"],
        )
        limits.update(
            symbol_lines=baseline.get("max_symbol_lines"),
            nested_functions=baseline.get("max_nested_functions"),
            decorated_handlers=baseline.get("max_decorated_handlers"),
        )
    exceeded = {
        name: {"actual": metrics[name], "maximum": maximum}
        for name, maximum in limits.items()
        if isinstance(maximum, int) and metrics[name] > maximum
    }
    if exceeded:
        findings.append(
            _blocking_finding(
                "central-file-growth",
                source_path,
                "A frozen central file exceeded its exact line or member baseline.",
                baseline_id=baseline["id"],
                owner=baseline["owner"],
                exit_stage=baseline["exit_stage"],
                exceeded=exceeded,
            )
        )
    tracked_limit = baseline.get("max_tracked_members_present")
    present_members = sorted(current["member_names"] & tracked_members)
    if isinstance(tracked_limit, int) and len(present_members) > tracked_limit:
        findings.append(
            _blocking_finding(
                "central-tracked-member-debt",
                source_path,
                "A named central debt cluster exceeds its current reduction target.",
                baseline_id=baseline["id"],
                owner=baseline["owner"],
                exit_stage=baseline["exit_stage"],
                present_members=present_members,
                maximum=tracked_limit,
            )
        )
    raw_allowed_present = baseline.get("allowed_tracked_members_present")
    if raw_allowed_present is not None:
        if (
            not isinstance(raw_allowed_present, list)
            or any(
                not isinstance(member, str) or not member.strip()
                for member in raw_allowed_present
            )
            or len(raw_allowed_present) != len(set(raw_allowed_present))
        ):
            findings.append(
                _diagnostic(
                    source_path,
                    "Central-growth allowed tracked members are malformed.",
                    baseline_id=baseline["id"],
                )
            )
        else:
            allowed_present = set(raw_allowed_present)
            untracked_allowed = sorted(allowed_present - tracked_members)
            if untracked_allowed:
                findings.append(
                    _diagnostic(
                        source_path,
                        "Central-growth allowed members must belong to tracked debt.",
                        baseline_id=baseline["id"],
                        untracked_allowed_members=untracked_allowed,
                    )
                )
            unexpected_present = sorted(set(present_members) - allowed_present)
            if unexpected_present:
                findings.append(
                    _blocking_finding(
                        "central-tracked-member-reintroduction",
                        source_path,
                        "A tracked central member outside the current allowed subset is present.",
                        baseline_id=baseline["id"],
                        owner=baseline["owner"],
                        exit_stage=baseline["exit_stage"],
                        unexpected_present_members=unexpected_present,
                        allowed_present_members=sorted(allowed_present),
                    )
                )
    raw_forbidden_terms = baseline.get("forbidden_source_terms", [])
    if not isinstance(raw_forbidden_terms, list) or any(
        not isinstance(term, str) or not term.strip()
        for term in raw_forbidden_terms
    ):
        findings.append(
            _diagnostic(
                source_path,
                "Central-growth forbidden source terms are malformed.",
                baseline_id=baseline["id"],
            )
        )
    else:
        matched_terms = find_python_symbol_forbidden_source_terms(
            current_source,
            str(baseline["symbol"]),
            str(kind),
            raw_forbidden_terms,
        )
        if matched_terms:
            findings.append(
                _blocking_finding(
                    "central-forbidden-source-term",
                    source_path,
                    "A removed domain still has SQL, codec, or identifier residue in the frozen central class.",
                    baseline_id=baseline["id"],
                    owner=baseline["owner"],
                    exit_stage=baseline["exit_stage"],
                    matched_terms=matched_terms,
                )
            )
    return findings


def _gather_forbidden_root_findings(
    repo_root: Path,
    rule: dict[str, Any],
    baseline_loader: OptionalBaselineLoader,
    comparison_commit: str,
    enforce_provenance: bool,
) -> list[dict[str, Any]]:
    root_value = str(rule.get("path") or "").strip().strip("/")
    if not root_value or any(token in root_value for token in ("*", "?", "[")):
        return [_diagnostic(root_value or "<missing-path>", "Forbidden implementation root must be one exact relative path.")]
    root = repo_root / root_value
    if not root.exists():
        return []
    files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
    governed_files = [
        path
        for path in files
        if _is_governed_code_bearing_path(
            path.relative_to(repo_root).as_posix(),
            path,
        )
    ]
    if not governed_files:
        return []
    source_commit = str(rule.get("source_commit") or "").strip()
    if not source_commit:
        return [
            _diagnostic(
                root_value, "Forbidden implementation root comparison is incomplete.",
                missing_fields=["source_commit"],
                completion_status="incomplete",
                evidence_complete=False,
            )
        ]
    if enforce_provenance and (
        provenance := _baseline_source_commit_diagnostic(
            repo_root,
            rule,
            comparison_commit,
            root_value,
        )
    ) is not None:
        return [provenance]
    try:
        changes = collect_file_size_changes(repo_root, source_commit)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return [
            _diagnostic(
                root_value, "Forbidden implementation root comparison could not be measured.",
                source_commit=source_commit,
                error=str(exc),
                completion_status="incomplete",
                evidence_complete=False,
            )
        ]

    root_prefix = root_value + "/"
    changes_by_path = {change.current_path: change for change in changes}
    findings: list[dict[str, Any]] = []
    for path in sorted(governed_files):
        source = path.relative_to(repo_root).as_posix()
        change = changes_by_path.get(source)
        baseline_path = change.baseline_path if change is not None else source
        baseline_inside_root = bool(
            baseline_path
            and (baseline_path == root_value or baseline_path.startswith(root_prefix))
        )
        try:
            current_source = path.read_text(encoding="utf-8")
            baseline_source = (
                baseline_loader(repo_root, source_commit, baseline_path)
                if baseline_inside_root and baseline_path is not None
                else None
            )
        except (OSError, UnicodeError, RuntimeError) as exc:
            findings.append(
                _diagnostic(
                    source,
                    "Forbidden implementation root change could not be compared.",
                    source_commit=source_commit,
                    error=str(exc),
                    completion_status="incomplete",
                    evidence_complete=False,
                )
            )
            continue
        details = {
            "baseline_id": rule.get("id"),
            "owner": rule.get("owner"),
            "exit_stage": rule.get("exit_stage"),
            "forbidden_root": root_value,
            "source_commit": source_commit,
            "baseline_path": baseline_path if baseline_source is not None else None,
        }
        if baseline_source is None:
            findings.append(
                _blocking_finding(
                    "forbidden-implementation-root",
                    source,
                    "A new code file exists under a root closed to implementation growth.",
                    **details,
                )
            )
            continue
        baseline_lines = len(baseline_source.splitlines())
        current_lines = len(current_source.splitlines())
        if current_lines > baseline_lines:
            findings.append(
                _blocking_finding(
                    "forbidden-implementation-root-growth",
                    source,
                    "An existing forbidden-root code file grew beyond its committed baseline.",
                    baseline_lines=baseline_lines,
                    current_lines=current_lines,
                    **details,
                )
            )
    return findings


def _gather_exclusive_source_owner_findings(
    repo_root: Path,
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    required = ("id", "root", "path_pattern", "owner")
    missing = [field for field in required if not rule.get(field)]
    source = str(rule.get("path_pattern") or rule.get("root") or "<missing-path>")
    if missing:
        return [_diagnostic(source, "Exclusive source owner rule is incomplete.", missing_fields=missing)]

    root_value = str(rule["root"]).strip().strip("/")
    path_pattern = str(rule["path_pattern"]).strip().strip("/")
    if (
        not root_value
        or any(token in root_value for token in ("*", "?", "[", ".."))
        or not path_pattern.startswith(f"{root_value}/")
        or ".." in path_pattern
    ):
        return [_diagnostic(source, "Exclusive source owner root or path pattern is invalid.")]

    allowed_paths = rule.get("allowed_paths")
    raw_patterns = rule.get("forbidden_source_patterns")
    if (
        not isinstance(allowed_paths, list)
        or not allowed_paths
        or any(not isinstance(path, str) or not path.strip() for path in allowed_paths)
        or len(allowed_paths) != len(set(allowed_paths))
        or not isinstance(raw_patterns, list)
        or not raw_patterns
        or any(not isinstance(pattern, str) or not pattern.strip() for pattern in raw_patterns)
    ):
        return [_diagnostic(source, "Exclusive source owner paths or patterns are malformed.")]

    allowed = {path.strip().strip("/") for path in allowed_paths}
    if any(not path.startswith(f"{root_value}/") or any(token in path for token in ("*", "?", "[", "..")) for path in allowed):
        return [_diagnostic(source, "Exclusive source owner allowed paths must be exact files under the rule root.")]
    missing_owners = sorted(path for path in allowed if not (repo_root / path).is_file())
    if missing_owners:
        return [_diagnostic(source, "Exclusive source owner file is missing.", missing_owner_paths=missing_owners)]

    try:
        patterns = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in raw_patterns]
    except re.error as exc:
        return [_diagnostic(source, "Exclusive source owner regex is invalid.", error=str(exc))]

    root = repo_root / root_value
    findings: list[dict[str, Any]] = []
    for path in sorted(repo_root.glob(path_pattern)):
        suffix = path.suffix.lower()
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root).as_posix()
        try:
            path.relative_to(root)
            if relative in allowed:
                continue
            if not _is_governed_code_bearing_path(relative, path):
                continue
            source_text = path.read_text(encoding="utf-8")
            if suffix == ".py":
                strings = static_python_strings(source_text)
            elif suffix in STATIC_STRING_SUFFIXES:
                strings = static_javascript_strings(source_text)
            else:
                findings.append(
                    _diagnostic(
                        relative,
                        "Exclusive source owner scan is incomplete for this code language.",
                        baseline_id=rule["id"],
                        owner=rule["owner"],
                        unsupported_suffix=suffix or "<extensionless>",
                        completion_status="incomplete",
                        evidence_complete=False,
                    )
                )
                continue
        except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
            findings.append(
                _diagnostic(
                    relative,
                    "Exclusive source owner scan failed.",
                    error=str(exc),
                )
            )
            continue
        matched = sorted(pattern.pattern for pattern in patterns if any(pattern.search(value) for value in strings))
        if matched:
            findings.append(
                _blocking_finding(
                    "exclusive-source-owner",
                    relative,
                    "A protected implementation token exists outside its canonical source owner.",
                    baseline_id=rule["id"],
                    owner=rule["owner"],
                    matched_patterns=matched,
                    allowed_paths=sorted(allowed),
                )
            )
    return findings


def gather_structure_findings(
    repo_root: Path,
    bundle: dict[str, Any],
    *,
    comparison_commit: str | None = None,
    baseline_loader: BaselineLoader = load_git_source,
    changed_path_loader: ChangedPathLoader | None = None,
    file_baseline_loader: OptionalBaselineLoader = load_optional_git_source,
    enforce_baseline_provenance: bool | None = None,
) -> list[dict[str, Any]]:
    rules = bundle.get("change_rules", {})
    if enforce_baseline_provenance is None:
        enforce_baseline_provenance = (
            baseline_loader is load_git_source
            and file_baseline_loader is load_optional_git_source
        )
    effective_comparison = str(
        comparison_commit or bundle.get("config", {}).get("source_commit") or ""
    ).strip()
    findings = gather_growth_findings(
        repo_root,
        bundle,
        comparison_commit=comparison_commit,
        changed_path_loader=changed_path_loader,
        baseline_loader=file_baseline_loader,
    )
    for baseline in rules.get("central_growth_baseline", []):
        findings.extend(
            _gather_central_growth_findings(
                repo_root,
                baseline,
                baseline_loader,
                effective_comparison,
                enforce_baseline_provenance,
            )
        )
    for rule in rules.get("forbidden_implementation_roots", []):
        findings.extend(
            _gather_forbidden_root_findings(
                repo_root,
                rule,
                file_baseline_loader,
                effective_comparison,
                enforce_baseline_provenance,
            )
        )
    for rule in rules.get("exclusive_source_owners", []):
        findings.extend(_gather_exclusive_source_owner_findings(repo_root, rule))
    return sorted(findings, key=lambda item: (item["rule"], item["source"], item["message"]))
