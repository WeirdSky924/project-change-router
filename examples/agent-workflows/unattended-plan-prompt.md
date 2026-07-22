# Unattended Agent Prompt Example

Use this prompt inside long-running plans when the agent may create, modify, delete, merge, deprecate, or migrate feature-level code.

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router for the target repository.

Use project-change-router as a direction index and guardrail system, not as an automatic architecture decision engine.

Treat the route report as one integrated contract. Read action, routing_confidence, decision_confidence, primary_capability, secondary_capabilities, required_reads, must_read_before_edit, allowed_write_paths, forbidden_write_paths, composite_route, capability_lifecycle_action, evaluation_regression_hints, and post_change_closeout together.

Mandatory layer: obey must_read_before_edit, allowed_write_paths, forbidden_write_paths, veto_reasons, canonical root, owner, public entry, lifecycle review, and duplicate-implementation warnings before writing product code.

Advisory layer: treat action, recommended_next_steps, safe_next_steps, analysis_directions, profile_repair_hints, and why_not_actions as directions for source-code analysis and user-confirmed decisions, not as final architecture commands.

If action=review, do not implement product code. Only perform safe_next_steps and read-only analysis unless the user provides a scoped override for the current task, phase, or changed paths. Do not reuse an override from an earlier phase.

If routing_confidence_level=low, treat automatic capability selection as unsafe even when decision_confidence_level=high. High decision confidence may mean the router is highly confident that the agent should stop.

Do not create a second implementation center when an existing capability, public entry, owner rule, or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

When running check_reuse, inspect result_status, completion_status, evidence_complete, and summary.scan.scope together. Only completion_status=complete with evidence_complete=true closes the duplicate check for the reported capability scope. For bounded, incomplete, timeout, cancelled, or error results, use the scoped candidates and diagnostics for targeted source analysis; do not claim that duplicate implementations are absent and do not expand to an unindexed full-repository scan.

For cross-stack changes, use composite_route to identify primary and secondary capabilities. Keep business logic in the confirmed core capability. Facade, API, UI, and transport layers should delegate to the core instead of becoming parallel implementations.

For delete, merge, deprecate, replace, and migration work, stop for lifecycle review first. Identify superseded_by, deprecation_date, migration_note, affected_callers, regression_tests, and rollback_plan before writing.

After routed changes, run the required closeout checks. Record feedback and add or update evaluation cases when a review, override, lifecycle change, false positive, false negative, or routing correction occurred.

Every new generated file or report directory must be checked for .gitignore inclusion.
```
