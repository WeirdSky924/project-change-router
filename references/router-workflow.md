# Router Workflow

Use this workflow whenever the user asks to:

- add or modify product behavior in a large repository
- refactor repeated capability logic
- standardize change entry points for AI agents
- create a project-local change-router bundle
- validate that reuse and boundary rules are being followed

## Operating Model

1. Identify the repository root.
2. If `project-change-router/router-config.yaml` does not exist, bootstrap the bundle with `scripts/bootstrap_router.py` only when the user wants durable repository-local routing metadata.
3. Use `scripts/resolve_entry.py` with the request text and known changed paths.
4. Read the routed capability entries before editing.
5. Run the required checks:
   - `scripts/check_reuse.py`
   - `scripts/check_deps.py`
   - `scripts/check_public_api.py`
   - `scripts/check_index_freshness.py`
   - `scripts/check_bundle_governance.py`
6. If route confidence is low or multiple stable capabilities overlap, return `review`.
7. After changes, update the bundle if the change created a new capability or changed public boundaries.

For `check_reuse.py`, `result_status` and `completion_status` answer different questions. A non-failing result does not close the duplicate check when `completion_status` is `bounded`, `incomplete`, `timeout`, `cancelled`, or `error`. Read `summary.scan.scope` and continue targeted source analysis; never expand an unresolved changed path into an implicit repository-wide scan.

## Two-Layer Contract

PCR is not an automatic architecture decision engine. It separates mandatory guardrails from advisory routing guidance.

Mandatory guardrails:

- `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`
- canonical roots, owners, public entries, and dependency direction
- duplicate implementation warnings
- `veto_reasons`, lifecycle review requirements, low routing confidence, provisional boundaries, and high-risk overlaps

Advisory guidance:

- `action`
- `recommended_next_action`
- `recommended_next_steps`
- `safe_next_steps`
- `analysis_directions`
- `why_not_actions`
- `profile_repair_hints`

Use advisory fields to decide what to inspect next and how to unblock the route. Final implementation choices still require source-code analysis, tests, and user-confirmed scope.

## Route Outputs

The resolver emits one integrated route report. Governance fields are not an optional side channel; they are part of the route contract and must be interpreted with `action`, `primary_capability`, and confidence. Mandatory guardrails take precedence over advisory actions.

The report includes:

- route action
- confidence
- primary capability
- secondary capabilities
- required reads
- required checks
- whether coordination or review is required
- block reason and missing evidence when review is required
- safe read-only next steps and suggested human questions
- allowed and forbidden write paths
- post-change closeout steps
- lifecycle action requirements for delete, merge, deprecate, or migrate requests
- composite route participants for cross-stack changes
- evaluation regression hints for human-confirmed routing outcomes

The detailed contract for these integrated outputs is in `references/governance-outputs.md`.

## Review Handling

When `action=review`, the agent must not start product-code implementation automatically. It may follow `safe_next_steps`, inspect the referenced bundle files, repair routing metadata after confirmation, and ask the suggested questions that are relevant to the task.

The skill gives direction, not final architecture decisions. Use `analysis_directions` to decide what to inspect next, then make the engineering call from real code, profile data, tests, and user confirmation.

To continue after a stop, the user override should be scoped by current task, phase, or changed paths and should record the reason. Do not reuse a Phase 0 override for later phases.

## Write Constraints

Before editing, read `must_read_before_edit`. Writes are allowed only under `allowed_write_paths` and must avoid `forbidden_write_paths`. For `review`, `allowed_write_paths` is empty and `forbidden_write_paths` includes `**`.

## Closeout

After implementation, follow `post_change_closeout`. If capability boundaries, public entries, ownership, lifecycle metadata, or generated files changed, run rebuild/validate/governance/evaluation and record feedback where needed.

## Governance Checks

Run `scripts/check_bundle_governance.py` when onboarding a repository, after a large structure change, or when route results repeatedly stop with missing capability candidates.

Treat P0 findings as blockers. P1 findings should usually become profile/catalog or evaluation-set work before unattended execution continues. P2 findings are maintenance items.

The resolver should never treat the catalog as infallible. Real code remains the final source of truth.
