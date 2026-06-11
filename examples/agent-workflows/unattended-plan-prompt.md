# Unattended Agent Prompt Example

Use this prompt inside long-running plans when the agent may create, modify, delete, merge, deprecate, or migrate feature-level code.

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router for the target repository.

Treat the route report as one integrated contract. Read action, routing_confidence, decision_confidence, primary_capability, secondary_capabilities, required_reads, must_read_before_edit, allowed_write_paths, forbidden_write_paths, composite_route, capability_lifecycle_action, evaluation_regression_hints, and post_change_closeout together.

If action=review, do not implement product code. Only perform safe_next_steps and read-only analysis unless the user provides a scoped override for the current task, phase, or changed paths. Do not reuse an override from an earlier phase.

If routing_confidence_level=low, treat automatic capability selection as unsafe even when decision_confidence_level=high. High decision confidence may mean the router is highly confident that the agent should stop.

Do not create a second implementation center when an existing capability, public entry, owner rule, or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

For cross-stack changes, use composite_route to identify primary and secondary capabilities. Keep business logic in the confirmed core capability. Facade, API, UI, and transport layers should delegate to the core instead of becoming parallel implementations.

For delete, merge, deprecate, replace, and migration work, stop for lifecycle review first. Identify superseded_by, deprecation_date, migration_note, affected_callers, regression_tests, and rollback_plan before writing.

After routed changes, run the required closeout checks. Record feedback and add or update evaluation cases when a review, override, lifecycle change, false positive, false negative, or routing correction occurred.

Every new generated file or report directory must be checked for .gitignore inclusion.
```
