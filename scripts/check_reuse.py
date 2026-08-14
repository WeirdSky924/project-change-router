#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import multiprocessing
import os
import subprocess
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

from reuse_runtime import (
    ReuseRuntimeStore,
    atomic_write_json,
    iso_now,
    retention_policy_from_bundle,
    runtime_policy_from_bundle,
    runtime_root_for_repo,
    semantic_digest,
    semantic_report_value,
)
from router_support.freshness_checks import build_structure_snapshot
from router_core import (
    changed_path_candidate_files,
    default_ignore_patterns,
    gather_reuse_report,
    normalize_rel_path,
    route_bundle_from_repo,
)


def scan_worker(
    repo_path: str,
    changed_paths: list[str],
    budget_overrides: dict[str, Any],
    runtime_options: dict[str, Any],
    result_path: str,
) -> None:
    try:
        repo_root = Path(repo_path).resolve()
        bundle = route_bundle_from_repo(repo_root)
        result = gather_reuse_report(
            repo_root,
            bundle,
            changed_paths or None,
            budget_overrides,
            runtime_options,
        )
        atomic_write_json(Path(result_path), {"status": "ok", "result": result})
    except BaseException as exc:
        atomic_write_json(
            Path(result_path),
            {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            },
        )


def incomplete_scan_from_checkpoint(
    runtime_root: Path,
    run_id: str,
    completion_status: str,
    termination_reason: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    with ReuseRuntimeStore(runtime_root, "off") as store:
        checkpoint = store.load_checkpoint(run_id)
    scan = dict((checkpoint or {}).get("scan", {}))
    scan.update(
        {
            "status": "warn",
            "completion_status": completion_status,
            "termination_reason": termination_reason,
            "evidence_complete": False,
            "elapsed_ms": elapsed_ms,
        }
    )
    findings = list((checkpoint or {}).get("findings", []))
    if not any(finding.get("rule") == "reuse-scan-incomplete" for finding in findings):
        findings.append(
            {
                "severity": "P2",
                "rule": "reuse-scan-incomplete",
                "message": "Reuse scan was interrupted; existing evidence is partial and cannot prove that no duplicate implementation exists.",
                "details": {
                    "completion_status": completion_status,
                    "termination_reason": termination_reason,
                },
            }
        )
    return {"scan": scan, "findings": findings}


def run_isolated_scan(
    repo_root: Path,
    changed_paths: list[str],
    budget_overrides: dict[str, Any],
    runtime_options: dict[str, Any],
    hard_timeout_seconds: float,
) -> tuple[dict[str, Any], bool]:
    runtime_root = Path(runtime_options["runtime_root"])
    run_id = str(runtime_options["run_id"])
    work_dir = runtime_root / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    result_path = work_dir / f"{run_id}.result.json"
    if result_path.exists():
        result_path.unlink()
    with ReuseRuntimeStore(runtime_root, str(runtime_options.get("cache_mode", "auto"))) as store:
        store.write_checkpoint(
            run_id,
            {
                "report_schema_version": 2,
                "report_class": "checkpoint",
                "run_id": run_id,
                "timestamp": iso_now(),
                "completion_status": "running",
                "scan": {
                    "status": "warn",
                    "completion_status": "running",
                    "evidence_complete": False,
                    "changed_path_count": len(changed_paths),
                },
                "findings": [],
            },
        )

    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=scan_worker,
        args=(str(repo_root), changed_paths, budget_overrides, runtime_options, str(result_path)),
        name=f"pcr-reuse-{run_id}",
    )
    started = time.monotonic()
    process.start()
    interrupted = False
    completion_status: Optional[str] = None
    termination_reason: Optional[str] = None
    try:
        while process.is_alive():
            process.join(timeout=0.1)
            if hard_timeout_seconds > 0 and time.monotonic() - started >= hard_timeout_seconds:
                completion_status = "timeout"
                termination_reason = "hard_timeout"
                break
    except KeyboardInterrupt:
        interrupted = True
        completion_status = "cancelled"
        termination_reason = "user_cancelled"
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=2.0)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    if completion_status:
        result = incomplete_scan_from_checkpoint(
            runtime_root,
            run_id,
            completion_status,
            str(termination_reason),
            elapsed_ms,
        )
    elif result_path.exists():
        envelope = json.loads(result_path.read_text(encoding="utf-8"))
        if envelope.get("status") == "ok":
            result = envelope["result"]
        else:
            result = incomplete_scan_from_checkpoint(
                runtime_root,
                run_id,
                "error",
                str(envelope.get("error", "worker_error")),
                elapsed_ms,
            )
            result["worker_error"] = envelope.get("traceback")
    else:
        result = incomplete_scan_from_checkpoint(
            runtime_root,
            run_id,
            "error",
            f"worker_exit_{process.exitcode}",
            elapsed_ms,
        )
    if result_path.exists():
        result_path.unlink()
    return result, interrupted


def build_input_fingerprint(
    repo_root: Path,
    bundle: dict[str, Any],
    changed_paths: list[str],
    budget_overrides: dict[str, Any],
    source_fingerprint_digest: str | None = None,
) -> str:
    identity_files = changed_path_candidate_files(
        repo_root,
        changed_paths,
        default_ignore_patterns(bundle.get("config", {})),
    )
    changed_identities = {
        normalize_rel_path(repo_root, path): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in identity_files
    }
    for changed_path in changed_paths:
        normalized = changed_path.replace("\\", "/")
        if not any(path == normalized or path.startswith(normalized.rstrip("/") + "/") for path in changed_identities):
            changed_identities[normalized] = "missing-or-ignored"
    head_state = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    full_scan_snapshot = None
    if not changed_paths:
        snapshot = build_structure_snapshot(
            repo_root, default_ignore_patterns(bundle.get("config", {}))
        )
        full_scan_snapshot = {
            "source_commit": snapshot.source_commit,
            "structure_digest": snapshot.digest,
            "indexed_paths": list(snapshot.paths),
            "diagnostics": list(snapshot.diagnostics),
        }
    routing_truth = {
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
    return semantic_digest(
        {
            "repo": str(repo_root.resolve()),
            "changed_paths": sorted(path.replace("\\", "/") for path in changed_paths),
            "changed_identities": changed_identities,
            "budget_overrides": budget_overrides,
            "routing_truth_digest": semantic_digest(routing_truth),
            "head_commit": (
                head_state.stdout.strip() if head_state.returncode == 0 else None
            ),
            "full_scan_snapshot": full_scan_snapshot,
            "source_fingerprint_digest": source_fingerprint_digest,
        }
    )


def build_canonical_report(
    run_id: str,
    input_fingerprint: str,
    reuse_report: dict[str, Any],
) -> dict[str, Any]:
    findings = reuse_report["findings"]
    scan = reuse_report["scan"]
    blocking = any(finding.get("severity") in {"P0", "P1"} for finding in findings)
    completion_status = str(scan.get("completion_status", "complete"))
    result_status = "fail" if blocking else "pass" if completion_status == "complete" else "warn"
    return {
        "report_schema_version": 2,
        "report_class": "canonical",
        "report_id": "check-reuse",
        "run_id": run_id,
        "timestamp": iso_now(),
        "script": "check_reuse.py",
        "status": result_status,
        "result_status": result_status,
        "completion_status": completion_status,
        "blocking": blocking,
        "evidence_complete": bool(scan.get("evidence_complete", completion_status == "complete")),
        "input_fingerprint": input_fingerprint,
        "summary": {"finding_count": len(findings), "scan": scan},
        "artifacts": {},
        "findings": findings,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect duplicate implementations and forbidden reuse bypasses.")
    parser.add_argument("--repo", required=True, help="Repository root path.")
    parser.add_argument("--changed-path", action="append", default=[], help="Optional changed path filters.")
    parser.add_argument("--full-scan", action="store_true", help="Explicitly scan all indexed modules when no changed path is provided.")
    parser.add_argument("--max-candidate-files", type=int, help="Maximum changed or full-scan candidate files.")
    parser.add_argument("--max-owner-files", type=int, help="Maximum owner files scanned per capability.")
    parser.add_argument("--max-comparisons", type=int, help="Maximum full-text similarity comparisons.")
    parser.add_argument("--max-file-bytes", type=int, help="Maximum file size eligible for full similarity.")
    parser.add_argument("--top-k-owner-files", type=int, help="Maximum prefiltered owner files per candidate and capability.")
    parser.add_argument("--timeout-seconds", type=float, help="Soft timeout; stops scheduling new comparisons and emits a report.")
    parser.add_argument("--hard-timeout-seconds", type=float, help="Hard timeout; terminates the isolated scan worker.")
    parser.add_argument("--checkpoint-interval-seconds", type=float, help="Checkpoint write interval.")
    parser.add_argument("--cache-mode", choices=["auto", "read-only", "off", "rebuild"], help="Persistent fingerprint cache mode.")
    parser.add_argument("--runtime-dir", help="Override the external runtime directory for cache and managed reports.")
    parser.add_argument("--diagnostics", choices=["auto", "always", "never"], help="Diagnostic report persistence mode.")
    parser.add_argument("--persist-reports", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--strict-completeness", action="store_true", help="Return exit code 2 for bounded or unresolved scans.")
    parser.add_argument("--cleanup-only", action="store_true", help="Apply configured cache/report retention and exit.")
    parser.add_argument("--format", choices=["json", "text"], default="text")
    parser.add_argument("--output", help="Optional canonical report output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo).resolve()
    bundle = route_bundle_from_repo(repo_root)
    policy = runtime_policy_from_bundle(
        bundle,
        {
            "soft_timeout_seconds": args.timeout_seconds,
            "hard_timeout_seconds": args.hard_timeout_seconds,
            "checkpoint_interval_seconds": args.checkpoint_interval_seconds,
            "cache_mode": args.cache_mode,
            "diagnostics_mode": args.diagnostics,
            "persist_reports": args.persist_reports,
        },
    )
    retention = retention_policy_from_bundle(bundle)
    runtime_root = runtime_root_for_repo(repo_root, bundle, args.runtime_dir)

    if args.cleanup_only:
        with ReuseRuntimeStore(runtime_root, policy.cache_mode) as store:
            removed = store.cleanup(repo_root, retention)
        report = {
            "report_schema_version": 2,
            "report_class": "canonical",
            "report_id": "check-reuse-cleanup",
            "run_id": f"cleanup-{uuid.uuid4().hex[:12]}",
            "timestamp": iso_now(),
            "status": "pass",
            "result_status": "pass",
            "completion_status": "complete",
            "blocking": False,
            "evidence_complete": True,
            "summary": {"removed": removed, "runtime_root": str(runtime_root)},
            "findings": [],
        }
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.format == "json" else f"status=pass removed={removed}")
        return 0

    if not args.changed_path and not args.full_scan:
        # Preserve the historical no-filter behavior while making the scope visible.
        legacy_full_scan = True
    else:
        legacy_full_scan = False

    budget_overrides = {
        "max_candidate_files": args.max_candidate_files,
        "max_owner_files_per_capability": args.max_owner_files,
        "max_comparisons": args.max_comparisons,
        "max_file_bytes_for_full_similarity": args.max_file_bytes,
        "top_k_owner_files_per_candidate": args.top_k_owner_files,
    }
    budget_overrides = {key: value for key, value in budget_overrides.items() if value is not None}
    run_id = f"reuse-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    runtime_options = {
        **dataclasses.asdict(policy),
        "runtime_root": str(runtime_root),
        "run_id": run_id,
    }
    reuse_report, interrupted = run_isolated_scan(
        repo_root,
        args.changed_path,
        budget_overrides,
        runtime_options,
        policy.hard_timeout_seconds,
    )
    if legacy_full_scan:
        reuse_report["scan"]["legacy_implicit_full_scan"] = True
        reuse_report["scan"]["migration_note"] = "Pass --full-scan explicitly in new automation; implicit full scan remains supported for compatibility."

    report = build_canonical_report(
        run_id,
        build_input_fingerprint(
            repo_root,
            bundle,
            args.changed_path,
            budget_overrides,
            reuse_report["scan"].get("source_fingerprint_digest"),
        ),
        reuse_report,
    )
    with ReuseRuntimeStore(runtime_root, policy.cache_mode) as store:
        diagnostic_needed = policy.diagnostics_mode == "always" or (
            policy.diagnostics_mode == "auto"
            and (
                report["completion_status"] != "complete"
                or report["summary"]["scan"].get("elapsed_ms", 0) >= policy.slow_scan_diagnostic_seconds * 1000
            )
        )
        if diagnostic_needed:
            diagnostic = {
                "report_schema_version": 2,
                "report_class": "diagnostic",
                "run_id": run_id,
                "timestamp": iso_now(),
                "result_status": report["result_status"],
                "completion_status": report["completion_status"],
                "scan": report["summary"]["scan"],
            }
            artifact = store.persist_report("diagnostic", diagnostic)
            report["artifacts"]["diagnostic"] = str(artifact.path)
        cleanup_result = store.cleanup(repo_root, retention)
        report["summary"]["retention_cleanup"] = cleanup_result
        if policy.persist_reports:
            artifact = store.persist_report(
                "canonical",
                report,
                semantic_report_value(report),
                pinned=report["blocking"],
            )
            report["artifacts"]["canonical"] = str(artifact.path)
            report["artifacts"]["deduplicated"] = artifact.deduplicated
            report["artifacts"]["occurrence_count"] = artifact.occurrence_count
            if not artifact.deduplicated:
                atomic_write_json(artifact.path, report)
        checkpoint_path = runtime_root / "reports" / "checkpoint" / f"{run_id}.json"
        if checkpoint_path.exists():
            report["artifacts"]["checkpoint"] = str(checkpoint_path)

    if args.output:
        atomic_write_json(Path(args.output), report)
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"status={report['status']} completion={report['completion_status']} "
            f"findings={len(report['findings'])}"
        )
    if interrupted:
        return 130
    if report["blocking"]:
        return 1
    if report["completion_status"] in {"timeout", "cancelled", "error"}:
        return 2
    if args.strict_completeness and report["completion_status"] != "complete":
        return 2
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
