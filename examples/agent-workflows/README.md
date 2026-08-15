# Agent Workflow Examples

These examples show how an agent should use the route report as an integrated contract before editing code. They are intentionally written as execution patterns, not theory.

PCR is a direction index and guardrail system, not an automatic architecture decision engine.

Mandatory guardrails:

- Read `execution_gate` first. It is the authoritative `pass`, `conditional`, or `blocked` write decision.
- Respect `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`.
- Protect confirmed owners, public entries, canonical roots, dependency direction, and lifecycle review requirements.
- Trace vetoes, unknown evidence, provisional boundaries, and high-risk overlaps to typed findings and matched policy rules.

Advisory guidance:

- Treat `action`, `recommended_next_steps`, `safe_next_steps`, `analysis_directions`, `why_not_actions`, and `profile_repair_hints` as investigation and unblock guidance.
- Do not treat `action` as a final engineering command.
- Do not treat `action=review` as permanent refusal or an independent stop. It is investigation guidance and can coexist with any gate state.

## 1. Route Before Editing

User request:

```text
Add refund support to the billing service.
```

Command:

```powershell
python scripts/run_change_flow.py --repo <repo-root> --request "Add refund support to the billing service." --changed-path services/billing/refund.py --format compact-json
```

Agent reads first:

- `execution_gate`
- `action`
- `primary_capability`
- `routing_confidence_level`
- `decision_confidence_level`
- `must_read_targets`
- `inventory_targets`
- `unresolved_read_targets`
- `allowed_write_paths`
- `forbidden_write_paths`
- `post_change_closeout`

Correct behavior:

- Follow `execution_gate`: no writes for blocked; run all prerequisites for conditional; preserve the envelope for pass.
- Read exact path/symbol/digest targets and execute unresolved query commands before editing.
- Write only under `allowed_write_paths`.
- Treat `action` as a route tendency while using source analysis to confirm the implementation plan.
- Run the checks listed in `required_checks`.
- Follow `post_change_closeout` before reporting completion.

Wrong behavior:

- Searching the repository from scratch and ignoring the route report.
- Editing a convenient nearby file outside `allowed_write_paths`.
- Treating a passing unit test as proof that routing metadata is still fresh.

## 2. Blocked Gate With Review Guidance

Full output sample:

- `../outputs/resolve-entry.review-guidance.json`

Typical signal:

```json
{
  "action": "review",
  "execution_gate": {
    "state": "blocked",
    "authoritative": true
  },
  "block_reason": {
    "code": "missing_capability_candidate"
  },
  "allowed_write_paths": [],
  "forbidden_write_paths": ["**"]
}
```

Correct behavior:

- Do not write product code.
- Execute only `safe_next_steps`.
- Read `project-change-router/references/path-to-capability-map.yaml`.
- Read `project-change-router/references/capability-catalog.yaml`.
- Ask the user only the relevant `suggested_questions`.
- Treat review as evidence-gathering direction and the blocked execution gate as the write stop.

Acceptable scoped authorization starts with an explicit user confirmation and a persisted request/grant:

```text
I authorize overriding this blocked gate only for the current task, current pre-change snapshot, and listed changed paths. Record a single-use grant with this exact confirmation and do not reuse it in later phases.
```

Wrong behavior:

- Converting `review` into `new` just to keep working.
- Treating `review` as proof that the task cannot be implemented.
- Reusing an override from a previous phase.
- Treating `decision_confidence=high` or any action as write permission.

## 3. Seed Repository New Capability

Full output sample:

- `../outputs/resolve-entry.seed-new-capability.json`

Typical signal:

```json
{
  "repo_stage": "seed",
  "action": "new",
  "routing_confidence_level": "low",
  "decision_confidence_level": "high"
}
```

Correct behavior:

- Create a named isolated capability boundary.
- Do not attach the new code to a weak generated capability just because names are similar.
- After the boundary is confirmed, add ownership and profile data.

Wrong behavior:

- Treating low routing confidence as a reason to ignore the route report.
- Creating a new file inside an existing module without naming the new boundary.

## 4. Cross-Stack Composite Change

Full output sample:

- `../outputs/resolve-entry.composite-review.json`

Typical signal:

```json
{
  "action": "review",
  "composite_route_required": true,
  "composite_route": {
    "primary": "billing-core",
    "secondary": ["billing-ui"],
    "coordination_policy": "review_before_write"
  }
}
```

Correct behavior:

- Identify which participant is core, facade, adapter, UI, test, migration, or governance.
- Read the primary capability public entries before touching secondary layers.
- Keep business logic in the confirmed core capability.
- Let API and UI surfaces delegate to the confirmed core rather than becoming new implementation centers.

Wrong behavior:

- Implementing business behavior in the API or UI layer because that path is most visible.
- Editing all participants after seeing `composite_route` without human confirmation.

## 5. Lifecycle Change

User request:

```text
Deprecate payment-core and replace it with billing-runtime.
```

Expected route behavior:

```json
{
  "action": "review",
  "block_reason": {
    "code": "capability_lifecycle_change"
  },
  "capability_lifecycle_action": {
    "intent": "deprecate",
    "review_required": true,
    "required_metadata": [
      "superseded_by",
      "deprecation_date",
      "migration_note",
      "affected_callers",
      "regression_tests",
      "rollback_plan"
    ]
  }
}
```

Correct behavior:

- Do not delete or merge code immediately.
- Identify public entries, dependent modules, callers, tests, and rollback path.
- Update lifecycle metadata after human confirmation.
- Add an evaluation case for the lifecycle decision.

Wrong behavior:

- Deleting a capability because it looks unused from changed paths only.
- Merging two capabilities without confirming the canonical root.

## 6. Profile Repair After Review

If the report includes:

```json
{
  "profile_repair_hints": [
    {
      "kind": "ownership_rule"
    },
    {
      "kind": "capability"
    },
    {
      "kind": "evaluation_case"
    }
  ]
}
```

Correct behavior:

- Treat this as governance metadata work, not product implementation.
- Add or refine `.project-change-router.yaml` only after human confirmation.
- Run `check_bundle_governance.py` after profile changes.
- Add a curated evaluation case when a route was corrected.

Wrong behavior:

- Promoting a generated-only capability to stable without confirmation.
- Hiding P1 governance warnings during unattended execution.

## 7. Closeout After Routed Changes

Always inspect `post_change_closeout`.

If capability boundaries, public entries, ownership, lifecycle metadata, generated files, or route-affecting behavior changed, run:

```powershell
python scripts/rebuild_index.py --repo <repo-root> --format json
python scripts/validate_router_bundle.py --repo <repo-root> --format json
python scripts/check_bundle_governance.py --repo <repo-root> --format json
python scripts/run_evaluation.py --repo <repo-root> --format json
```

If a human review or override happened, record feedback:

```powershell
python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json
```

Wrong behavior:

- Finishing with only product tests.
- Updating code while leaving stale path-to-capability or evaluation data.

## 8. Updating an Existing Bundle After a Skill Upgrade

Full copyable prompt:

- `update-existing-router-bundle-prompt.md`

Use it only when a repository already has an older bundle and read-only compatibility checks prove that current routing metadata actually needs refresh. A skill installation upgrade alone does not require a bundle rebuild.

Correct behavior:

- Run the latest skill scripts against the target repo.
- Validate compatibility first and stop without writes when the existing bundle remains current.
- Preserve `.project-change-router.yaml`, curated evaluation cases, manual feedback, ownership rules, and lifecycle metadata.
- Replace only generated or marked project-change-router guidance blocks.
- Rebuild only after a concrete stale reference or confirmed boundary change is identified, then validate, audit governance, check freshness, and run evaluation.
- Report P0/P1/P2 findings and recommended calibration actions.

Wrong behavior:

- Re-running bootstrap over an existing calibrated bundle without confirmation.
- Rebuilding only because `reuse_scan_runtime` defaults are absent from a schema-v1 bundle.
- Overwriting user-authored profile data because a generated file changed shape.
- Manually adding new route report fields to old outputs instead of regenerating with the latest scripts.

## 9. Interpreting Reuse Scan Completion

If `check_reuse.py` returns:

```json
{
  "result_status": "warn",
  "completion_status": "bounded",
  "evidence_complete": false
}
```

Correct behavior:

- Read `summary.scan.scope`, fingerprint candidates, size/budget limits, and diagnostics.
- Continue with targeted source analysis inside the resolved capability scope.
- Repair a missing path/test binding when the scope is incomplete.
- Treat `duplicate-fingerprint-candidate` as a P2 investigation lead, not exact duplicate proof.
- Claim the scoped duplicate check complete only when `completion_status=complete` and `evidence_complete=true`.

Wrong behavior:

- Reporting “no duplicate implementation” because `result_status` is not `fail`.
- Re-running for 600 seconds without inspecting the built-in timeout and scope report.
- Expanding an unresolved test path into a full-repository similarity scan.
- Treating checkpoint or diagnostic artifacts as canonical decisions.

## 10. Conditional Gate for Unrelated Historical Debt

Typical compact signal:

```json
{
  "action": "review",
  "execution_gate": {
    "state": "conditional",
    "required_commands": ["read owner entry before editing"]
  },
  "delta_summary": {
    "baseline_unchanged": 2,
    "unknown": 0
  }
}
```

Correct behavior:

- Verify the baseline is trusted and bound to the current runtime/profile/bundle/structure/index identity.
- Confirm every remaining finding is proven unrelated or non-expanding historical debt.
- Run every required command and keep writes inside the bounded envelope.
- Treat `action=review` as investigation direction; do not turn it into a second block.

Wrong behavior:

- Promoting the current dirty or incomplete scan to a baseline.
- Treating any stale debt as unrelated without a relevance trace and trusted baseline.
- Widening allowed paths because the gate is conditional.

## 11. Compact Output and Precise Reads

Use:

```powershell
python scripts/run_change_flow.py --repo <repo-root> --request "<request>" --changed-path <path> --format compact-json
```

Correct behavior:

- Keep the fixed safety envelope in the main context.
- Verify the full artifact bytes against `artifact_digest` before loading evidence from it.
- Read each `must_read_target` by exact path, symbol, and `content_digest`.
- Treat directories as `inventory_targets`; run `unresolved_read_targets[].command` when no unique symbol is proven.
- Rerun the flow if a target digest changes before editing.

Wrong behavior:

- Excluding `execution_gate`, vetoes, write paths, unknown evidence, artifact identity, or completeness through field projection.
- Reading an entire routed directory as if it were one must-read file.
- Treating a line hint as stable identity.

## 12. Bounded Authorization

Correct behavior:

- Persist the flow's request context with `manage_authorization.py request`.
- Obtain explicit user confirmation, then record a grant with its authority source and exact text.
- Default to one use and 24-hour expiry; use bounded multi-use only when the user explicitly authorizes it.
- Consume the grant for the matching task/snapshot/envelope and preserve the digest-chained audit events.

Wrong behavior:

- Treating an authorization request, old route fingerprint, or matching manifest as authority.
- Reusing a Phase 0 grant for Phase 1.
- Returning consumed, expired, rejected, or invalidated authority to `granted`.

## 13. Three Reuse Channels

For a normal extension, inspect intra- and cross-capability coverage. For `new`, `extract`, or lifecycle work, also require extended coverage. Each required channel must report complete evidence before the aggregate can say `none_found`; bounded channels only support `not_proven` and targeted follow-up.

An exact duplicate between the routed owner and a related capability belongs to `cross_capability`. A duplicate found only in the expanded new/extract/lifecycle search belongs to `extended`. Do not relabel either as intra-capability merely because both files appeared in one route report.
