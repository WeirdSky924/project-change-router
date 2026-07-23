from __future__ import annotations

import ast
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from router_support.architecture_baseline import comparison_guardrail_items
from router_support.structure_growth import (
    diagnostic,
    git_commit_is_ancestor,
    resolve_git_commit,
)

PYTHON_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
CENTRAL_MAX_FIELDS = (
    "max_file_lines",
    "max_methods",
    "max_public_methods",
    "max_symbol_lines",
    "max_nested_functions",
    "max_decorated_handlers",
    "max_tracked_members_present",
)


def baseline_source_commit_diagnostic(
    repo_root: Path,
    baseline: dict[str, Any],
    comparison_commit: str,
    source: str,
) -> dict[str, Any] | None:
    source_commit = str(baseline.get("source_commit") or "").strip()
    if not comparison_commit:
        return diagnostic(
            source,
            "Baseline provenance requires an effective comparison commit.",
            diagnostic_code="baseline_source_commit_incomplete",
            baseline_id=baseline.get("id"),
            completion_status="incomplete",
            evidence_complete=False,
        )
    try:
        source_resolved = resolve_git_commit(repo_root, source_commit)
        comparison_resolved = resolve_git_commit(repo_root, comparison_commit)
        head_resolved = resolve_git_commit(repo_root, "HEAD")
        is_ancestor = git_commit_is_ancestor(
            repo_root,
            source_resolved,
            comparison_resolved,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return diagnostic(
            source,
            "Baseline source commit provenance could not be verified.",
            diagnostic_code="baseline_source_commit_incomplete",
            baseline_id=baseline.get("id"),
            source_commit=source_commit,
            comparison_commit=comparison_commit,
            error=str(exc),
            completion_status="incomplete",
            evidence_complete=False,
        )
    source_is_feature_head = (
        source_resolved == head_resolved
        and head_resolved != comparison_resolved
    )
    if source_is_feature_head or not is_ancestor:
        reason = "feature_head" if source_is_feature_head else "not_comparison_ancestor"
        return diagnostic(
            source,
            "Baseline source commit is not trusted by the comparison boundary.",
            diagnostic_code="baseline_source_commit_untrusted",
            baseline_id=baseline.get("id"),
            source_commit=source_resolved,
            comparison_commit=comparison_resolved,
            current_head=head_resolved,
            provenance_reason=reason,
            completion_status="incomplete",
            evidence_complete=False,
        )
    return None


def central_rule_weakening_diagnostic(
    repo_root: Path,
    baseline: dict[str, Any],
    comparison_commit: str,
    source: str,
) -> dict[str, Any] | None:
    try:
        comparison_resolved = resolve_git_commit(repo_root, comparison_commit)
        comparison_items = comparison_guardrail_items(
            repo_root,
            comparison_resolved,
            "central_growth_baseline",
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return diagnostic(
            source,
            "Previous central baseline could not be verified.",
            diagnostic_code="central_baseline_provenance_incomplete",
            baseline_id=baseline.get("id"),
            comparison_commit=comparison_commit,
            error=str(exc),
            completion_status="incomplete",
            evidence_complete=False,
        )

    target_fields = ("kind", "path", "symbol")
    target = tuple(baseline.get(field) for field in target_fields)
    target_matches = [
        item
        for item in comparison_items.values()
        if tuple(item.get(field) for field in target_fields) == target
    ]
    if len(target_matches) > 1:
        return diagnostic(
            source,
            "Comparison commit has conflicting central baselines for one canonical target.",
            diagnostic_code="central_baseline_comparison_target_conflict",
            baseline_id=baseline.get("id"),
            comparison_commit=comparison_resolved,
            comparison_baseline_ids=sorted(
                str(item.get("id")) for item in target_matches
            ),
            canonical_target={field: baseline.get(field) for field in target_fields},
            completion_status="incomplete",
            evidence_complete=False,
        )

    previous_by_id = comparison_items.get(str(baseline.get("id")))
    previous_by_target = target_matches[0] if target_matches else None
    if (
        previous_by_id is not None
        and previous_by_target is not None
        and previous_by_id is not previous_by_target
    ):
        return diagnostic(
            source,
            "Central baseline ID and canonical target resolve to different comparison records.",
            diagnostic_code="central_baseline_comparison_identity_conflict",
            baseline_id=baseline.get("id"),
            comparison_commit=comparison_resolved,
            comparison_baseline_ids=sorted(
                {
                    str(previous_by_id.get("id")),
                    str(previous_by_target.get("id")),
                }
            ),
            completion_status="incomplete",
            evidence_complete=False,
        )
    previous = previous_by_target or previous_by_id
    if previous is None:
        return None

    weakened: dict[str, Any] = {}

    def string_set(value: object) -> set[str] | None:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return None
        return set(value)

    for field in ("kind", "path", "symbol", "source_commit", "owner", "exit_stage"):
        if baseline.get(field) != previous.get(field):
            weakened[field] = {
                "comparison": previous.get(field),
                "current": baseline.get(field),
            }
    for field in CENTRAL_MAX_FIELDS:
        old_value = previous.get(field)
        if old_value is None:
            continue
        current_value = baseline.get(field)
        if type(old_value) is not int or type(current_value) is not int or current_value > old_value:
            weakened[field] = {"comparison": old_value, "current": current_value}

    previous_allowed = previous.get("allowed_tracked_members_present")
    current_allowed = baseline.get("allowed_tracked_members_present")
    previous_allowed_set = string_set(previous_allowed)
    current_allowed_set = string_set(current_allowed)
    if previous_allowed is not None and (
        previous_allowed_set is None
        or current_allowed_set is None
        or not current_allowed_set.issubset(previous_allowed_set)
    ):
        weakened["allowed_tracked_members_present"] = {
            "comparison": previous_allowed,
            "current": current_allowed,
        }
    for field in ("tracked_members", "forbidden_source_terms"):
        old_values = previous.get(field, [])
        current_values = baseline.get(field, [])
        old_set = string_set(old_values)
        current_set = string_set(current_values)
        if old_set is None or current_set is None or not old_set.issubset(current_set):
            weakened[field] = {
                "comparison": old_values,
                "current": current_values,
            }
    if not weakened:
        return None
    return diagnostic(
        source,
        "Central baseline constraints were weakened after the comparison commit.",
        diagnostic_code="central_baseline_weakening",
        baseline_id=baseline.get("id"),
        comparison_commit=comparison_resolved,
        weakened_fields=weakened,
        completion_status="complete",
        evidence_complete=True,
    )


def _python_symbol_node(source: str, symbol: str, kind: str) -> ast.AST:
    tree = ast.parse(source)
    expected: tuple[type[ast.AST], ...]
    label: str
    if kind == "python-class-remove-only":
        expected = (ast.ClassDef,)
        label = "class"
    elif kind == "python-function-remove-only":
        expected = PYTHON_FUNCTION_NODES
        label = "function"
    else:
        raise ValueError(f"unsupported central baseline kind {kind!r}")
    node = next(
        (item for item in tree.body if isinstance(item, expected) and item.name == symbol),
        None,
    )
    if node is None:
        raise ValueError(f"{label} {symbol!r} was not found")
    return node


def measure_python_class(source: str, symbol: str) -> dict[str, Any]:
    class_node = _python_symbol_node(source, symbol, "python-class-remove-only")
    method_names = {
        node.name
        for node in class_node.body
        if isinstance(node, PYTHON_FUNCTION_NODES)
    }
    return {
        "member_names": method_names,
        "method_names": method_names,
        "method_count": len(method_names),
        "public_method_count": sum(not name.startswith("_") for name in method_names),
    }


def measure_python_function(source: str, symbol: str) -> dict[str, Any]:
    function_node = _python_symbol_node(source, symbol, "python-function-remove-only")
    nested = [
        node
        for node in ast.walk(function_node)
        if node is not function_node and isinstance(node, PYTHON_FUNCTION_NODES)
    ]
    names = {node.name for node in nested}
    return {
        "member_names": names,
        "nested_function_names": names,
        "nested_function_count": len(nested),
        "decorated_handler_count": sum(bool(node.decorator_list) for node in nested),
        "symbol_line_count": function_node.end_lineno - function_node.lineno + 1,
    }


def measure_python_symbol(source: str, symbol: str, kind: str) -> dict[str, Any]:
    if kind == "python-class-remove-only":
        return measure_python_class(source, symbol)
    if kind == "python-function-remove-only":
        return measure_python_function(source, symbol)
    raise ValueError(f"unsupported central baseline kind {kind!r}")


def find_python_symbol_forbidden_source_terms(
    source: str,
    symbol: str,
    kind: str,
    terms: Iterable[str],
) -> list[str]:
    symbol_node = _python_symbol_node(source, symbol, kind)

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9_]+", "", value.casefold())

    def static_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_string(node.left)
            right = static_string(node.right)
            if left is not None and right is not None:
                return left + right
        return None

    search_units: set[str] = set()
    for node in ast.walk(symbol_node):
        identifiers: list[str] = []
        if isinstance(node, (*PYTHON_FUNCTION_NODES, ast.ClassDef)):
            identifiers.append(node.name)
        elif isinstance(node, ast.Name):
            identifiers.append(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.append(node.attr)
        elif isinstance(node, ast.arg):
            identifiers.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            identifiers.append(node.arg)
        search_units.update(
            normalized
            for identifier in identifiers
            if (normalized := normalize(identifier))
        )
        value = static_string(node)
        if value is not None and (normalized := normalize(value)):
            search_units.add(normalized)
    return sorted(
        term
        for term in terms
        if any(normalize(term) in unit for unit in search_units)
    )


def find_python_class_forbidden_source_terms(
    source: str,
    symbol: str,
    terms: list[str],
) -> list[str]:
    return find_python_symbol_forbidden_source_terms(
        source,
        symbol,
        "python-class-remove-only",
        terms,
    )
