from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from reuse_runtime import runtime_root_for_repo
from router_support.authorization_manifest import AuthorizationManifestStore
from router_support.evidence_baseline import (
    EvidenceBaselineStore,
    baseline_binding,
    classify_against_baseline,
)
from router_support.execution_gate import reduce_execution_gate, shadow_gate_comparison
from router_support.finding_adapters import adapt_check_report
from router_support.incremental_evidence import (
    IncrementalEvidenceCache,
    build_evidence_input,
    update_incremental_snapshot,
)
from router_support.runtime_identity import runtime_identity
from router_support.typed_findings import (
    TypedFinding,
    canonical_json,
    digest_value,
    findings_digest,
)


FLOW_API_VERSION = 1
SAFE_ENVELOPE_FIELDS = (
    "execution_gate",
    "veto_reasons",
    "allowed_write_paths",
    "forbidden_write_paths",
    "unknown_evidence",
    "artifact_path",
    "artifact_digest",
    "output_complete",
)
DEFAULT_COMPACT_FIELDS = (
    "action",
    "primary_capability",
    "recommended_next_action",
    "required_commands",
    "delta_summary",
    "cache_summary",
    "incremental_summary",
    "must_read_targets",
    "inventory_targets",
    "unresolved_read_targets",
    "authorization_request",
    "runtime_identity",
)


def persist_flow_artifact(
    runtime_root: Path, report: Mapping[str, Any]
) -> tuple[Path, str]:
    encoded = (canonical_json(report) + "\n").encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path = Path(runtime_root) / "flow-artifacts" / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    return path, digest


def compact_flow_output(
    report: Mapping[str, Any],
    *,
    fields: Iterable[str] | None = None,
    exclude_fields: Iterable[str] = (),
    artifact_reference: bool = False,
) -> dict[str, Any]:
    excluded = {str(field) for field in exclude_fields if str(field)}
    protected = sorted(excluded & set(SAFE_ENVELOPE_FIELDS))
    if protected:
        raise ValueError(
            "safety-envelope fields cannot be excluded: " + ", ".join(protected)
        )
    selected = list(
        (
            "action",
            "primary_capability",
            "recommended_next_action",
            "required_commands",
        )
        if artifact_reference
        else (*DEFAULT_COMPACT_FIELDS, *(fields or ()))
    )
    selected = [field for field in selected if field not in excluded]
    keys = list(dict.fromkeys([*SAFE_ENVELOPE_FIELDS, *selected]))
    return {key: report.get(key) for key in keys}


def _script_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _check_command(
    check_name: str,
    *,
    repo_root: Path,
    changed_paths: list[str],
    comparison_commit: str | None,
    route_action: str,
    lifecycle_intent: bool,
    timeout_seconds: float,
    output_path: Path,
    runtime_root: Path,
) -> list[str]:
    script_by_check = {
        "dependency": "check_deps.py",
        "public_api": "check_public_api.py",
        "structure": "check_structure.py",
        "freshness": "check_index_freshness.py",
        "governance": "check_bundle_governance.py",
        "reuse": "check_reuse.py",
    }
    command = [
        sys.executable,
        str(_script_root() / "scripts" / script_by_check[check_name]),
        "--repo",
        str(repo_root),
        "--format",
        "json",
        "--output",
        str(output_path),
    ]
    if comparison_commit and check_name in {"dependency", "public_api", "structure"}:
        command.extend(["--comparison-commit", comparison_commit])
    if check_name == "freshness":
        if comparison_commit:
            command.extend(["--comparison-commit", comparison_commit])
        for path in changed_paths:
            command.extend(["--changed-path", path])
    if check_name == "reuse":
        for path in changed_paths:
            command.extend(["--changed-path", path])
        command.extend(
            [
                "--action",
                route_action,
                "--strict-completeness",
                "--timeout-seconds",
                str(timeout_seconds),
                "--hard-timeout-seconds",
                str(timeout_seconds),
                "--runtime-dir",
                str(runtime_root),
            ]
        )
        if lifecycle_intent:
            command.append("--lifecycle-intent")
    if check_name == "governance":
        command.append("--strict")
    return command


def _incomplete_check_report(
    check_name: str,
    *,
    completion_status: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "report_id": f"flow-{check_name}-incomplete",
        "status": "warn",
        "result_status": "warn",
        "completion_status": completion_status,
        "blocking": True,
        "evidence_complete": False,
        "findings": [],
        "flow_error": reason,
    }


def _run_check(
    check_name: str,
    *,
    repo_root: Path,
    changed_paths: list[str],
    comparison_commit: str | None,
    route_action: str,
    lifecycle_intent: bool,
    timeout_seconds: float,
    runtime_root: Path,
) -> dict[str, Any]:
    work_root = Path(runtime_root) / "flow-work"
    work_root.mkdir(parents=True, exist_ok=True)
    output_path = work_root / f"{check_name}-{uuid.uuid4().hex}.json"
    command = _check_command(
        check_name,
        repo_root=repo_root,
        changed_paths=changed_paths,
        comparison_commit=comparison_commit,
        route_action=route_action,
        lifecycle_intent=lifecycle_intent,
        timeout_seconds=timeout_seconds,
        output_path=output_path,
        runtime_root=runtime_root,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=_script_root(),
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds + 5.0, 10.0),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _incomplete_check_report(
            check_name, completion_status="timeout", reason="flow child timeout"
        )
    except KeyboardInterrupt:
        return _incomplete_check_report(
            check_name, completion_status="cancelled", reason="flow cancelled"
        )
    try:
        if output_path.is_file():
            return json.loads(output_path.read_text(encoding="utf-8"))
        return _incomplete_check_report(
            check_name,
            completion_status="error",
            reason=(completed.stderr.strip() or f"child exited {completed.returncode}"),
        )
    finally:
        output_path.unlink(missing_ok=True)


def _clean_worktree(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return not result.stdout.strip()


def _repo_id(repo_root: Path, bundle: Mapping[str, Any]) -> str:
    identity = (
        f"{repo_root.resolve()}|"
        f"{bundle.get('config', {}).get('repo_id', repo_root.name)}"
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _check_evidence(
    evidence: Mapping[str, Any],
    check_name: str,
    route_action: str,
    lifecycle_intent: bool,
) -> dict[str, Any]:
    if check_name == "governance":
        scope = "governance"
        scoped_digest = evidence.get("governance_input_digest")
    elif check_name == "reuse":
        scope = "closure"
        scoped_digest = evidence.get("closure_input_digest")
    else:
        scope = "global"
        scoped_digest = evidence.get("global_input_digest")
    value = {
        "head": evidence.get("head"),
        "profile_digest": evidence.get("profile_digest"),
        "bundle_digest": evidence.get("bundle_digest"),
        "structure_digest": evidence.get("structure_digest"),
        "indexed_paths_digest": evidence.get("indexed_paths_digest"),
        "runtime_identity_digest": evidence.get("runtime_identity_digest"),
        "evidence_scope": scope,
        "scoped_source_digest": scoped_digest,
        "check_name": check_name,
        "route_action": route_action if check_name == "reuse" else None,
        "lifecycle_intent": lifecycle_intent if check_name == "reuse" else None,
    }
    value["input_digest"] = digest_value(
        {key: item for key, item in value.items() if key != "input_digest"}
    )
    return value


def _delta_summary(findings: Iterable[TypedFinding]) -> dict[str, int]:
    summary = {
        "task_local_new": 0,
        "task_local_expanded": 0,
        "baseline_unchanged": 0,
        "baseline_reduced": 0,
        "resolved": 0,
        "unknown": 0,
    }
    for finding in findings:
        summary[finding.delta_state] = summary.get(finding.delta_state, 0) + 1
    return summary


def run_change_flow(
    *,
    repo_root: Path,
    request_text: str,
    changed_paths: list[str],
    comparison_commit: str | None = None,
    runtime_dir: str | None = None,
    timeout_seconds: float = 60.0,
    accept_baseline: str | None = None,
    ci_baseline: bool = False,
) -> dict[str, Any]:
    from router_core import (
        build_route_report,
        resolve_bundle_root,
        resolve_request,
        route_bundle_from_repo,
    )

    repo = Path(repo_root).resolve()
    bundle = route_bundle_from_repo(repo)
    decision = resolve_request(
        request_text,
        changed_paths,
        bundle,
        resolve_bundle_root(repo),
    )
    route = build_route_report(decision)
    runtime = runtime_identity(_script_root())
    runtime_root = runtime_root_for_repo(repo, bundle, runtime_dir)
    runtime_root.mkdir(parents=True, exist_ok=True)
    structure_digest = str(
        route.get("authorization_context", {}).get("structure_digest") or "unknown"
    )
    route_capabilities = [
        value
        for value in [
            route.get("primary_capability"),
            *route.get("secondary_capabilities", []),
        ]
        if value
    ]
    evidence_input = build_evidence_input(
        repo,
        bundle,
        changed_paths,
        runtime_identity=runtime,
        structure_digest=structure_digest,
        route_capabilities=route_capabilities,
    )
    lifecycle_intent = bool(
        route.get("capability_lifecycle_action", {}).get("intent")
        not in {None, "", "none"}
    )
    cache = IncrementalEvidenceCache(runtime_root)
    check_names = (
        "dependency",
        "public_api",
        "structure",
        "freshness",
        "governance",
        "reuse",
    )
    checks: dict[str, dict[str, Any]] = {}
    cache_summary = {"hits": 0, "misses": 0, "checks": {}}
    for check_name in check_names:
        scoped_evidence = _check_evidence(
            evidence_input,
            check_name,
            str(route.get("action", "review")),
            lifecycle_intent,
        )
        cached = cache.load(check_name, scoped_evidence)
        if cached is not None:
            report = cached
            cache_summary["hits"] += 1
            cache_summary["checks"][check_name] = "hit"
        else:
            report = _run_check(
                check_name,
                repo_root=repo,
                changed_paths=changed_paths,
                comparison_commit=comparison_commit,
                route_action=str(route.get("action", "review")),
                lifecycle_intent=lifecycle_intent,
                timeout_seconds=timeout_seconds,
                runtime_root=runtime_root,
            )
            report["runtime_identity"] = runtime
            report["cache"] = {
                "hit": False,
                "input_digest": scoped_evidence["input_digest"],
            }
            cache.save(check_name, scoped_evidence, report)
            cache_summary["misses"] += 1
            cache_summary["checks"][check_name] = "miss"
        checks[check_name] = report

    route_findings = [
        TypedFinding.from_dict(item) for item in route.get("typed_findings", [])
    ]
    closure_capabilities = set(evidence_input.get("route_capability_closure", []))
    route_scope_paths = list(changed_paths)
    for capability in bundle.get("capability_catalog", {}).get("capabilities", []):
        if str(capability.get("id", "")) not in closure_capabilities:
            continue
        route_scope_paths.extend(
            str(path)
            for field in ("owner_modules", "public_entries", "related_tests")
            for path in capability.get(field, [])
            if path
        )
    check_findings: list[TypedFinding] = []
    for check_name, report in checks.items():
        check_findings.extend(
            adapt_check_report(
                check_name,
                report,
                route_paths=changed_paths,
                route_capabilities=closure_capabilities,
                route_scope_paths=route_scope_paths,
            )
        )
    raw_evidence_digest = findings_digest(check_findings)
    binding = baseline_binding(
        commit=str(evidence_input.get("head") or "uncommitted"),
        profile_digest=str(evidence_input["profile_digest"]),
        bundle_digest=str(evidence_input["bundle_digest"]),
        structure_digest=structure_digest,
        indexed_paths_digest=str(evidence_input["indexed_paths_digest"]),
        scope_digest=digest_value(
            {
                "changed_paths": sorted(changed_paths),
                "capabilities": sorted(route_capabilities),
            }
        ),
        tool_version=str(runtime["skill_version"]),
        policy_version=str(runtime["gate_policy_version"]),
        evidence_digest=raw_evidence_digest,
    )
    baseline_store = EvidenceBaselineStore(runtime_root)
    repo_id = _repo_id(repo, bundle)
    incremental_summary = update_incremental_snapshot(
        runtime_root,
        repo_id=repo_id,
        bundle=bundle,
        evidence=evidence_input,
        route_capabilities=route_capabilities,
    )
    trusted = baseline_store.load_trusted(repo_id, binding)
    classified_checks = classify_against_baseline(
        check_findings,
        trusted,
        evidence_complete=all(
            report.get("completion_status", "complete") == "complete"
            and report.get("evidence_complete", True) is not False
            and not report.get("flow_error")
            for report in checks.values()
        ),
    )
    all_findings = sorted(
        [*route_findings, *classified_checks], key=lambda item: item.finding_id
    )
    output_complete = all(
        report.get("completion_status", "complete") == "complete"
        and report.get("evidence_complete", True) is not False
        and not report.get("flow_error")
        for report in checks.values()
    )
    candidate = baseline_store.record_candidate(
        repo_id=repo_id,
        binding=binding,
        findings=check_findings,
        clean_worktree=_clean_worktree(repo),
        evidence_complete=output_complete,
        source="ci" if os.environ.get("CI") else "local",
    )
    promoted = None
    if accept_baseline:
        if accept_baseline != candidate["snapshot_fingerprint"]:
            raise ValueError("accepted baseline fingerprint does not match current evidence")
        promoted = baseline_store.promote(
            accept_baseline, authority="user:accepted"
        )
    elif ci_baseline:
        if not os.environ.get("CI"):
            raise ValueError("--ci-baseline requires a CI environment")
        promoted = baseline_store.promote(
            candidate["snapshot_fingerprint"], authority="ci:verified"
        )

    required_commands = list(
        dict.fromkeys(
            [
                *route.get("execution_gate", {}).get("required_commands", []),
                *[
                    step.get("command")
                    for step in route.get("post_change_closeout", [])
                    if isinstance(step, Mapping) and step.get("command")
                ],
            ]
        )
    )
    proposed_allowed = route.get("execution_gate", {}).get(
        "proposed_allowed_write_paths", route.get("allowed_write_paths", [])
    )
    proposed_forbidden = route.get("execution_gate", {}).get(
        "proposed_forbidden_write_paths", route.get("forbidden_write_paths", [])
    )
    gate = reduce_execution_gate(
        all_findings,
        allowed_write_paths=proposed_allowed,
        forbidden_write_paths=proposed_forbidden,
        required_commands=required_commands,
        output_complete=output_complete,
        authoritative=True,
    )
    legacy_state = str(
        route.get("gate_shadow", {}).get(
            "legacy_state",
            "blocked" if route.get("review_required") else "pass",
        )
    )
    shadow = shadow_gate_comparison(legacy_state=legacy_state, new_gate=gate)
    unknown_evidence = list(gate.get("unknown_evidence", []))
    authorization_request: dict[str, Any] = {}
    if gate["state"] == "blocked":
        route_request = route.get("authorization_request", {})
        context = {
            "route_fingerprint": route.get("route_fingerprint"),
            "pre_change_snapshot": evidence_input["input_digest"],
            "task_id": route.get("decision_id", ""),
            "paths": changed_paths,
            "owner": route_request.get("owner", ""),
            "canonical_root": route_request.get("canonical_root", ""),
            "route": route.get("action", "review"),
            "mutation_envelope": {
                "allowed_write_paths": list(proposed_allowed),
                "forbidden_write_paths": list(proposed_forbidden),
            },
        }
        authorization_store = AuthorizationManifestStore(runtime_root)
        authorization_request = authorization_store.create_request(context)
        authorization_request["manifest_path"] = str(
            authorization_store.requests_root
            / f"{authorization_request['request_id']}.json"
        )
    flow_report: dict[str, Any] = {
        "change_flow_api_version": FLOW_API_VERSION,
        "action": route.get("action"),
        "primary_capability": route.get("primary_capability"),
        "secondary_capabilities": route.get("secondary_capabilities", []),
        "execution_gate": gate,
        "gate_shadow": shadow,
        "veto_reasons": route.get("veto_reasons", []),
        "allowed_write_paths": gate["allowed_write_paths"],
        "forbidden_write_paths": gate["forbidden_write_paths"],
        "unknown_evidence": unknown_evidence,
        "output_complete": output_complete,
        "required_commands": required_commands,
        "recommended_next_action": (
            "request_authorization_or_repair_evidence"
            if gate["state"] == "blocked"
            else "run_required_commands"
            if gate["state"] == "conditional"
            else "proceed_with_routed_analysis"
        ),
        "must_read_targets": route.get("must_read_targets", []),
        "inventory_targets": route.get("inventory_targets", []),
        "unresolved_read_targets": route.get("unresolved_read_targets", []),
        "authorization_request": authorization_request,
        "delta_summary": _delta_summary(all_findings),
        "cache_summary": cache_summary,
        "incremental_summary": incremental_summary,
        "baseline": {
            "trusted": trusted is not None,
            "candidate_snapshot_fingerprint": candidate["snapshot_fingerprint"],
            "promoted": promoted,
        },
        "runtime_identity": runtime,
        "route_report": route,
        "checks": checks,
        "typed_findings": [finding.to_dict() for finding in all_findings],
        "evidence_input": evidence_input,
    }
    artifact_path, artifact_digest = persist_flow_artifact(runtime_root, flow_report)
    flow_report["artifact_path"] = str(artifact_path)
    flow_report["artifact_digest"] = artifact_digest
    return flow_report
