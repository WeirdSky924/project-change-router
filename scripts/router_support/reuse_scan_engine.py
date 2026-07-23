from __future__ import annotations

import dataclasses
import datetime as dt
import difflib
import fnmatch
import hashlib
import time
from pathlib import Path
from typing import Any, Optional

from reuse_runtime import (
    FINGERPRINT_VERSION,
    ReuseRuntimePolicy,
    ReuseRuntimeStore,
    file_stat_key,
    iso_now as runtime_iso_now,
    token_sketch,
)
from router_support.reuse_scan import (
    ReuseScanEnvironment,
    build_reuse_scope,
    capability_comparison_files,
    changed_path_candidate_files,
    reuse_scan_budget_from_bundle,
)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _path_token_set(
    environment: ReuseScanEnvironment, repo_root: Path, path: Path
) -> set[str]:
    tokens = set(
        environment.derive_path_tokens(environment.normalize_rel_path(repo_root, path))
    )
    return {token for token in tokens if token not in environment.generic_path_tokens}


def _prioritize_owner_files(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    owner_files: list[Path],
    candidate_files: list[Path],
) -> list[Path]:
    candidate_tokens: set[str] = set()
    for candidate in candidate_files:
        candidate_tokens.update(_path_token_set(environment, repo_root, candidate))
    return sorted(
        owner_files,
        key=lambda path: (
            -_jaccard(_path_token_set(environment, repo_root, path), candidate_tokens),
            environment.normalize_rel_path(repo_root, path),
        ),
    )


def gather_reuse_report(
    environment: ReuseScanEnvironment,
    repo_root: Path,
    bundle: dict[str, Any],
    modules: list[Any],
    capabilities: list[Any],
    ignore_patterns: list[str],
    changed_paths: Optional[list[str]] = None,
    budget_overrides: Optional[dict[str, Any]] = None,
    runtime_options: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    started = time.monotonic()
    capability_by_id = {capability.id: capability for capability in capabilities}
    budget, budget_configuration_errors = reuse_scan_budget_from_bundle(
        bundle, budget_overrides
    )
    runtime_options = dict(runtime_options or {})
    runtime_policy = ReuseRuntimePolicy(
        soft_timeout_seconds=max(
            0.0, float(runtime_options.get("soft_timeout_seconds", 0.0))
        ),
        hard_timeout_seconds=max(
            0.0, float(runtime_options.get("hard_timeout_seconds", 0.0))
        ),
        checkpoint_interval_seconds=max(
            0.1, float(runtime_options.get("checkpoint_interval_seconds", 5.0))
        ),
        cache_mode=str(runtime_options.get("cache_mode", "off")),
        diagnostics_mode=str(runtime_options.get("diagnostics_mode", "never")),
        persist_reports=bool(runtime_options.get("persist_reports", False)),
    )
    run_id = str(
        runtime_options.get(
            "run_id",
            f"reuse-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        )
    )
    deadline = (
        started + runtime_policy.soft_timeout_seconds
        if runtime_policy.soft_timeout_seconds > 0
        else None
    )
    runtime_root = (
        Path(runtime_options["runtime_root"]).resolve()
        if runtime_options.get("runtime_root")
        else None
    )
    store = (
        ReuseRuntimeStore(runtime_root, runtime_policy.cache_mode)
        if runtime_root
        else None
    )

    phase_started = time.monotonic()
    if changed_paths:
        candidate_files = changed_path_candidate_files(
            environment, repo_root, changed_paths, ignore_patterns
        )
    else:
        candidate_files = environment.source_files_for_modules(
            repo_root, modules, ignore_patterns
        )
    scope = build_reuse_scope(
        environment,
        repo_root,
        bundle,
        capabilities,
        modules,
        candidate_files,
        changed_paths,
        ignore_patterns,
    )
    scoped_capabilities = [
        capability_by_id[item]
        for item in scope["capability_ids"]
        if item in capability_by_id
    ]
    scope_elapsed = int((time.monotonic() - phase_started) * 1000)

    findings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {
        "status": "complete",
        "completion_status": "complete",
        "termination_reason": None,
        "evidence_complete": True,
        "budget_exceeded": False,
        "changed_path_count": len(changed_paths or []),
        "candidate_file_count": len(candidate_files),
        "candidate_files_scanned": min(len(candidate_files), budget.max_candidate_files),
        "candidate_files_limited": len(candidate_files) > budget.max_candidate_files,
        "owner_file_count": 0,
        "owner_files_scanned": 0,
        "owner_files_limited_capabilities": [],
        "capabilities_without_owner_files": [],
        "capabilities_total": len(capabilities),
        "capabilities_scanned": len(scoped_capabilities),
        "capabilities_skipped_by_scope": max(
            0, len(capabilities) - len(scoped_capabilities)
        ),
        "raw_pair_count": 0,
        "unique_pair_count": 0,
        "comparisons_planned": 0,
        "comparisons_run": 0,
        "comparisons_skipped_by_prefilter": 0,
        "comparisons_skipped_by_size": 0,
        "comparisons_skipped_by_budget": 0,
        "comparisons_skipped_by_top_k": 0,
        "comparisons_skipped_by_pair_dedup": 0,
        "source_files_read": 0,
        "fingerprint_cache_hits": 0,
        "fingerprint_cache_misses": 0,
        "fingerprints_written": 0,
        "fingerprint_advisories_reported": 0,
        "size_limited_examples": [],
        "candidate_examples": [
            environment.normalize_rel_path(repo_root, path)
            for path in candidate_files[:20]
        ],
        "scope": scope,
        "elapsed_ms_by_phase": {"candidate_and_scope": scope_elapsed},
        "budget": dataclasses.asdict(budget),
        "runtime": dataclasses.asdict(runtime_policy),
        "runtime_recovery": store.recovery_event if store else None,
        "fingerprint_version": FINGERPRINT_VERSION,
    }
    if budget_configuration_errors:
        metrics.update(
            status="warn",
            completion_status="incomplete",
            termination_reason="invalid_configuration",
            evidence_complete=False,
        )
        findings.append(
            {
                "severity": "P1",
                "rule": "reuse-scan-configuration-invalid",
                "message": "Reuse scan budget configuration cannot prove complete evidence.",
                "details": {"errors": list(budget_configuration_errors)},
            }
        )
        if store:
            store.close()
        return {"findings": findings, "scan": metrics}
    if metrics["candidate_files_limited"]:
        candidate_files = candidate_files[: budget.max_candidate_files]

    normalized_cache: dict[Path, str] = {}
    fingerprint_cache: dict[Path, dict[str, Any]] = {}
    owner_file_cache: dict[str, list[Path]] = {}
    pair_prefilter_cache: dict[tuple[str, str], Optional[float]] = {}
    exact_score_cache: dict[tuple[str, str], float] = {}
    duplicate_findings: dict[tuple[str, str], dict[str, Any]] = {}
    fingerprint_advisories: dict[tuple[str, str], dict[str, Any]] = {}
    last_checkpoint = started
    stop_reason: Optional[str] = None

    def rel(path: Path) -> str:
        return environment.normalize_rel_path(repo_root, path)

    def should_stop() -> bool:
        nonlocal stop_reason
        if stop_reason:
            return True
        if deadline is not None and time.monotonic() >= deadline:
            stop_reason = "soft_timeout"
            return True
        return False

    def write_checkpoint(force: bool = False) -> None:
        nonlocal last_checkpoint
        if store is None:
            return
        now = time.monotonic()
        if (
            not force
            and now - last_checkpoint < runtime_policy.checkpoint_interval_seconds
        ):
            return
        payload = {
            "report_schema_version": 2,
            "report_class": "checkpoint",
            "run_id": run_id,
            "timestamp": runtime_iso_now(),
            "completion_status": "running" if not stop_reason else stop_reason,
            "scan": metrics,
            "findings": [*findings, *duplicate_findings.values()],
        }
        store.write_checkpoint(run_id, payload)
        last_checkpoint = now

    def normalized_text(path: Path) -> str:
        if path not in normalized_cache:
            metrics["source_files_read"] += 1
            normalized_cache[path] = environment.normalized_code(
                path.read_text(encoding="utf-8", errors="ignore")
            )
        return normalized_cache[path]

    def fingerprint(path: Path) -> dict[str, Any]:
        if path in fingerprint_cache:
            return fingerprint_cache[path]
        path_rel = rel(path)
        stat_key = file_stat_key(path)
        cached = store.get_fingerprint(path_rel, stat_key) if store else None
        if cached is not None:
            metrics["fingerprint_cache_hits"] += 1
            fingerprint_cache[path] = cached
            return cached
        metrics["fingerprint_cache_misses"] += 1
        text = normalized_text(path)
        tokens = environment.text_tokens(text)
        value = {
            "suffix": path.suffix.lower(),
            "file_size": path.stat().st_size,
            "normalized_length": len(text),
            "token_count": len(tokens),
            "token_sketch": token_sketch(tokens),
            "content_digest": hashlib.blake2b(
                text.encode("utf-8"), digest_size=16
            ).hexdigest(),
        }
        if store:
            store.put_fingerprint(path_rel, stat_key, value)
            if runtime_policy.cache_mode not in {"off", "read-only"}:
                metrics["fingerprints_written"] += 1
        fingerprint_cache[path] = value
        return value

    def pair_key(left: Path, right: Path) -> tuple[str, str]:
        return tuple(sorted((rel(left), rel(right))))

    def remember_size_limited(
        owner_file: Path,
        candidate: Path,
        owner_fp: dict[str, Any],
        candidate_fp: dict[str, Any],
    ) -> None:
        if len(metrics["size_limited_examples"]) < 20:
            metrics["size_limited_examples"].append(
                {
                    "owner_file": rel(owner_file),
                    "candidate_file": rel(candidate),
                    "owner_bytes": owner_fp["file_size"],
                    "candidate_bytes": candidate_fp["file_size"],
                }
            )

    def prefilter_pair(
        owner_file: Path, candidate: Path, capability_id: str
    ) -> Optional[float]:
        key = pair_key(owner_file, candidate)
        if key in pair_prefilter_cache:
            metrics["comparisons_skipped_by_pair_dedup"] += 1
            if (
                key in fingerprint_advisories
                and capability_id not in fingerprint_advisories[key]["capabilities"]
            ):
                fingerprint_advisories[key]["capabilities"].append(capability_id)
                fingerprint_advisories[key]["capabilities"].sort()
            return pair_prefilter_cache[key]
        if candidate == owner_file or candidate.suffix.lower() != owner_file.suffix.lower():
            metrics["comparisons_skipped_by_prefilter"] += 1
            pair_prefilter_cache[key] = None
            return None
        owner_fp = fingerprint(owner_file)
        candidate_fp = fingerprint(candidate)
        shorter = max(
            1, min(owner_fp["normalized_length"], candidate_fp["normalized_length"])
        )
        length_ratio = (
            max(owner_fp["normalized_length"], candidate_fp["normalized_length"])
            / shorter
        )
        if length_ratio > budget.max_length_ratio:
            metrics["comparisons_skipped_by_prefilter"] += 1
            pair_prefilter_cache[key] = None
            return None
        token_score = _jaccard(
            set(owner_fp["token_sketch"]), set(candidate_fp["token_sketch"])
        )
        path_score = _jaccard(
            _path_token_set(environment, repo_root, owner_file),
            _path_token_set(environment, repo_root, candidate),
        )
        if (
            token_score < budget.min_token_jaccard
            and path_score < budget.min_path_token_overlap
        ):
            metrics["comparisons_skipped_by_prefilter"] += 1
            pair_prefilter_cache[key] = None
            return None
        score = (token_score * 0.8) + (path_score * 0.2)
        size_limited = bool(
            owner_fp["file_size"] > budget.max_file_bytes_for_full_similarity
            or candidate_fp["file_size"] > budget.max_file_bytes_for_full_similarity
            or owner_fp["normalized_length"]
            > budget.max_normalized_chars_for_full_similarity
            or candidate_fp["normalized_length"]
            > budget.max_normalized_chars_for_full_similarity
            or owner_fp["normalized_length"] * candidate_fp["normalized_length"]
            > budget.max_similarity_char_product
        )
        if size_limited:
            metrics["comparisons_skipped_by_size"] += 1
            remember_size_limited(owner_file, candidate, owner_fp, candidate_fp)
            if score >= budget.min_fingerprint_advisory_score:
                fingerprint_advisories[key] = {
                    "severity": "P2",
                    "rule": "duplicate-fingerprint-candidate",
                    "path": rel(candidate),
                    "owner_path": rel(owner_file),
                    "capability": capability_id,
                    "capabilities": [capability_id],
                    "fingerprint_score": round(score, 4),
                    "message": (
                        "fingerprint similarity requires targeted source analysis; "
                        "this is not exact duplicate proof"
                    ),
                }
            pair_prefilter_cache[key] = None
            return None
        pair_prefilter_cache[key] = score
        return score

    scan_phase_started = time.monotonic()
    for capability in capabilities:
        for pattern in capability.forbidden_patterns:
            for candidate in candidate_files:
                candidate_rel = rel(candidate)
                if fnmatch.fnmatchcase(candidate_rel, pattern.replace("\\", "/")):
                    findings.append(
                        {
                            "severity": "P0",
                            "rule": "forbidden-pattern",
                            "path": candidate_rel,
                            "capability": capability.id,
                            "message": (
                                f"{candidate_rel} matches a forbidden path pattern "
                                f"for {capability.id}"
                            ),
                        }
                    )

    if scope.get("completion_status") != "complete":
        findings.append(
            {
                "severity": "P2",
                "rule": "reuse-scan-scope-unresolved",
                "message": (
                    "Changed paths were not fully resolved to reliable capability "
                    "ownership; the scan did not expand to unrelated capabilities."
                ),
                "details": {
                    "scope_status": scope["status"],
                    "unresolved_paths": scope["unresolved_paths"],
                    "scoped_capabilities": scope["capability_ids"],
                    "diagnostics": scope.get("diagnostics", []),
                },
            }
        )

    budget_exhausted = False
    for capability in scoped_capabilities:
        if should_stop() or not candidate_files:
            break
        if capability.id not in owner_file_cache:
            owner_files = capability_comparison_files(
                environment,
                repo_root,
                capability,
                modules,
                ignore_patterns,
                candidate_files,
            )
            metrics["owner_file_count"] += len(owner_files)
            if len(owner_files) > budget.max_owner_files_per_capability:
                metrics["owner_files_limited_capabilities"].append(
                    {
                        "capability": capability.id,
                        "owner_file_count": len(owner_files),
                        "scanned": budget.max_owner_files_per_capability,
                    }
                )
                owner_files = _prioritize_owner_files(
                    environment, repo_root, owner_files, candidate_files
                )[: budget.max_owner_files_per_capability]
            owner_file_cache[capability.id] = owner_files
        owner_files = owner_file_cache[capability.id]
        if not owner_files:
            metrics["capabilities_without_owner_files"].append(capability.id)
            findings.append(
                {
                    "severity": "P1",
                    "rule": "reuse-owner-surface-missing",
                    "capability": capability.id,
                    "message": "Scoped capability has no readable canonical owner files.",
                }
            )
        metrics["owner_files_scanned"] += len(owner_files)
        metrics["raw_pair_count"] += sum(
            1
            for owner_file in owner_files
            for candidate in candidate_files
            if owner_file != candidate
        )

        for candidate in candidate_files:
            if should_stop():
                break
            preliminary: list[tuple[float, Path]] = []
            for owner_file in owner_files:
                if should_stop():
                    break
                rough_score = prefilter_pair(owner_file, candidate, capability.id)
                if rough_score is not None:
                    preliminary.append((rough_score, owner_file))
                write_checkpoint()
            metrics["comparisons_planned"] += len(preliminary)
            selected = sorted(
                preliminary, key=lambda item: item[0], reverse=True
            )[: budget.top_k_owner_files_per_candidate]
            metrics["comparisons_skipped_by_top_k"] += max(
                0, len(preliminary) - len(selected)
            )
            for _, owner_file in selected:
                if should_stop():
                    break
                key = pair_key(owner_file, candidate)
                if key in exact_score_cache:
                    metrics["comparisons_skipped_by_pair_dedup"] += 1
                    score = exact_score_cache[key]
                else:
                    if metrics["comparisons_run"] >= budget.max_comparisons:
                        metrics["budget_exceeded"] = True
                        metrics["comparisons_skipped_by_budget"] += len(selected)
                        budget_exhausted = True
                        break
                    owner_text = normalized_text(owner_file)
                    candidate_text = normalized_text(candidate)
                    matcher = difflib.SequenceMatcher(None, owner_text, candidate_text)
                    if matcher.quick_ratio() < 0.85:
                        metrics["comparisons_skipped_by_prefilter"] += 1
                        exact_score_cache[key] = 0.0
                        continue
                    metrics["comparisons_run"] += 1
                    score = matcher.ratio()
                    exact_score_cache[key] = score
                if score < 0.85:
                    continue
                existing = duplicate_findings.get(key)
                if existing is None:
                    duplicate_findings[key] = {
                        "severity": "P1" if score >= 0.92 else "P2",
                        "rule": "duplicate-implementation",
                        "path": rel(candidate),
                        "owner_path": rel(owner_file),
                        "capability": capability.id,
                        "capabilities": [capability.id],
                        "score": round(score, 4),
                        "message": f"duplicate implementation signal for {capability.id}",
                    }
                elif capability.id not in existing["capabilities"]:
                    existing["capabilities"].append(capability.id)
                    existing["capabilities"].sort()
                    if score >= 0.92:
                        existing["severity"] = "P1"
                    existing["score"] = max(existing["score"], round(score, 4))
                write_checkpoint()
            if budget_exhausted or should_stop():
                break
        if budget_exhausted or should_stop():
            break

    findings.extend(duplicate_findings.values())
    advisory_findings = [
        finding
        for key, finding in sorted(
            fingerprint_advisories.items(),
            key=lambda item: (-item[1]["fingerprint_score"], item[0]),
        )
        if key not in duplicate_findings
    ][:20]
    findings.extend(advisory_findings)
    metrics["fingerprint_advisories_reported"] = len(advisory_findings)
    metrics["unique_pair_count"] = sum(
        1 for left, right in pair_prefilter_cache if left != right
    )
    metrics["elapsed_ms_by_phase"]["fingerprint_and_compare"] = int(
        (time.monotonic() - scan_phase_started) * 1000
    )
    metrics["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    size_limit_prevented_scan = bool(
        metrics["raw_pair_count"] > 0
        and metrics["comparisons_skipped_by_size"] > 0
        and metrics["comparisons_planned"] == 0
        and metrics["comparisons_run"] == 0
    )
    metrics["size_limit_prevented_scan"] = size_limit_prevented_scan

    if stop_reason:
        completion_status = "timeout"
        termination_reason = stop_reason
    elif scope.get("completion_status") != "complete":
        completion_status = "incomplete"
        termination_reason = "scope_unresolved"
    elif not scoped_capabilities:
        completion_status = "incomplete"
        termination_reason = "capability_surface_missing"
        findings.append(
            {
                "severity": "P1",
                "rule": "reuse-capability-surface-missing",
                "message": "Reuse scan has no governed capability comparison surface.",
            }
        )
    elif metrics["capabilities_without_owner_files"]:
        completion_status = "incomplete"
        termination_reason = "owner_surface_missing"
    elif (
        metrics["budget_exceeded"]
        or metrics["candidate_files_limited"]
        or metrics["owner_files_limited_capabilities"]
        or metrics["comparisons_skipped_by_top_k"] > 0
        or metrics["comparisons_skipped_by_size"] > 0
    ):
        completion_status = "bounded"
        termination_reason = "configured_budget"
    else:
        completion_status = "complete"
        termination_reason = None
    metrics["completion_status"] = completion_status
    metrics["termination_reason"] = termination_reason
    metrics["evidence_complete"] = completion_status == "complete"
    metrics["status"] = "complete" if completion_status == "complete" else "warn"

    if completion_status != "complete" and not any(
        finding["rule"] == "reuse-scan-scope-unresolved" for finding in findings
    ):
        findings.append(
            {
                "severity": "P2",
                "rule": "reuse-scan-incomplete",
                "message": (
                    "Reuse scan produced bounded or interrupted evidence; do not "
                    "treat it as proof that no duplicate implementation exists."
                ),
                "details": {
                    "completion_status": completion_status,
                    "termination_reason": termination_reason,
                    "scope": scope,
                },
            }
        )

    write_checkpoint(force=True)
    if store:
        if completion_status == "complete":
            store.delete_checkpoint(run_id)
        store.close()
    return {"findings": findings, "scan": metrics}
