# Unattended Agent Prompt Example

Use this prompt inside long-running plans when the agent may create, modify, delete, merge, deprecate, or migrate feature-level code.

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router for the target repository and run run_change_flow.py with the request and complete changed-path set.

Use project-change-router as a direction index and guardrail system, not as an automatic architecture decision engine.

Treat the flow report as one integrated contract. Read execution_gate before action. Also read runtime_identity, typed findings, decisive finding IDs, policy rules, unknown_evidence, output_complete, primary/secondary capabilities, exact read targets, allowed/forbidden paths, composite/lifecycle metadata, required_commands, authorization_request, artifact digest, and post_change_closeout.

Mandatory layer: execution_gate.state is the authoritative write decision. For blocked, do not write product code. For conditional, execute every required_command and keep writes inside the bounded envelope. For pass, still obey exact reads and the envelope. Never ignore vetoes, unknown evidence, owner/canonical/public-entry rules, lifecycle findings, or duplicate risk.

Advisory layer: treat action, including action=review, recommended_next_steps, safe_next_steps, analysis_directions, profile_repair_hints, and why_not_actions as directions for source-code analysis and user-confirmed decisions. Never turn action into a second gate.

If a blocked gate is eligible for override, persist an authorization request and obtain explicit user confirmation before creating a grant. Bind it to task, phase, paths, owner, route, pre-change snapshot, mutation envelope, runtime/policy identity, expiry, and use count. Never reuse a grant from another phase or revive consumed/invalidated authority.

If routing_confidence_level=low, treat automatic capability selection as weak even when decision_confidence_level=high. Confidence explains route/action evidence; it does not replace execution_gate.

Do not create a second implementation center when an existing capability, public entry, owner rule, or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

For reuse, inspect intra_capability, cross_capability, and extended channel coverage. Only complete evidence for every required channel can support none_found. For bounded, incomplete, timeout, cancelled, or error results, use scoped candidates and diagnostics for targeted source analysis; report not_proven and never expand an unresolved path to an unindexed full-repository scan.

Use must_read_targets by exact path, symbol, and content_digest. Treat directories only as inventory_targets. Run every unresolved_read_targets query and keep the target unresolved until one implementation is proven. If a content digest changes before editing, rerun the flow.

Use only a trusted baseline bound to a clean complete commit/CI/user-accepted snapshot and the current profile, bundle, structure, index, scope, runtime, parser, and policy identity. Never promote a first scan, dirty worktree, or bounded/incomplete result. Treat unresolved closure edges as unknown.

Keep the main context compact. Preserve execution_gate, veto_reasons, allowed/forbidden paths, unknown_evidence, output_complete, artifact_path, and artifact_digest. Read the full content-addressed artifact only for the evidence needed by the current decision, and verify its digest.

For cross-stack changes, use composite_route to identify primary and secondary capabilities. Keep business logic in the confirmed core capability. Facade, API, UI, and transport layers should delegate to the core instead of becoming parallel implementations.

For delete, merge, deprecate, replace, and migration work, stop for lifecycle review first. Identify superseded_by, deprecation_date, migration_note, affected_callers, regression_tests, and rollback_plan before writing.

After routed changes, execute post_change_closeout and rerun affected flow/checks. Record feedback and add or update evaluation cases when a review, override, lifecycle change, false positive, false negative, or routing correction occurred.

Every new generated file or report directory must be checked for .gitignore inclusion.
```
