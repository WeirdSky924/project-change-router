# Governance Outputs

Route reports are intentionally split into seven governance output groups. These groups are not an external feature bolted onto the router. They are first-class parts of the same `resolve_entry` route contract and must be read together with `action`, `primary_capability`, confidence, and required checks.

The goal is not to make the router behave like a full architecture agent. The goal is to give the agent enough durable, low-token context to avoid writing in the wrong place, duplicating a capability, or treating weak generated evidence as architecture truth.

## Mandatory vs Advisory

Mandatory fields are execution guardrails. The agent must obey them before product-code writes:

- `allowed_write_paths`
- `forbidden_write_paths`
- `must_read_before_edit`
- `veto_reasons`
- lifecycle review requirements
- confirmed owners, public entries, canonical roots, and dependency direction

Advisory fields are structured direction. The agent should use them to decide what to inspect, repair, or ask next, but they are not a substitute for source-code analysis:

- `action`
- `recommended_next_action`
- `recommended_next_steps`
- `safe_next_steps`
- `analysis_directions`
- `why_not_actions`
- `profile_repair_hints`

If these layers appear to conflict, guardrails win. For example, `action=extend` does not permit writes outside `allowed_write_paths`, and `action=review` does not mean the task is impossible; it means automatic product-code writes need more evidence, profile repair, or a scoped user confirmation.

## 1. Review Handling

Fields:

- `block_reason`
- `missing_evidence`
- `analysis_directions`
- `safe_next_steps`
- `suggested_questions`
- `override_requirements`

Trigger this group when `action=review`, when a lifecycle intent is detected, when early-repo policy blocks automatic routing, when the path map has no candidate, or when multiple capabilities overlap.

Expected agent behavior:

- Treat `review` as a stop for implementation, not as a failed route.
- Use `safe_next_steps` for read-only analysis.
- Use `analysis_directions` to decide what code, imports, callers, public entries, tests, and profile entries to inspect.
- Ask only the relevant `suggested_questions`.
- Continue with writes only when the user gives an override matching `override_requirements`.

Do not:

- Turn a `review` into an automatic `new` route just to keep working.
- Treat `review` as a final architecture decision without doing the recommended investigation.
- Reuse an override from a previous phase.
- Treat `decision_confidence=high` as permission to write when `action=review`.

## 2. Write Constraints

Fields:

- `allowed_write_paths`
- `forbidden_write_paths`
- `must_read_before_edit`

For `review`, `allowed_write_paths` must be empty and `forbidden_write_paths` must include `**`. For `reuse`, the target capability core should usually be protected from writes. For `extend` and `extract`, writes should stay in routed owner modules or explicitly changed paths. For `new`, writes should stay in a named isolated capability boundary after confirmation.

Expected agent behavior:

- Read every relevant item in `must_read_before_edit` before editing.
- Restrict writes to `allowed_write_paths`.
- Stop if the requested implementation requires writing outside the route constraints.
- Run a `.gitignore` inclusion check for generated or report directories.

Do not:

- Use route output as permission to write anywhere in the repository.
- Create a parallel implementation center under a convenient but unrelated directory.

## 3. Governance Repair Hints

Fields:

- `profile_repair_hints`
- `repair_suggestions` in governance reports

These hints translate weak routing evidence into concrete metadata repair work. They are emitted when capability mappings are generated-only, public entries are heuristic, ownership is missing, path coverage is incomplete, contracts are thin, or lifecycle metadata is incomplete.

Expected agent behavior:

- Treat repair hints as profile/catalog/governance work, not product implementation.
- Convert repeated manual confirmations into `.project-change-router.yaml` profile entries.
- Add contracts, public entries, ownership rules, lifecycle metadata, and evaluation cases after human confirmation.
- Run `check_bundle_governance.py` after profile or catalog changes.

Do not:

- Promote generated-only capability guesses to stable boundaries without human calibration.
- Hide P1 governance warnings when planning unattended execution.

## 4. Post-Change Closeout

Field:

- `post_change_closeout`

Closeout steps define what must happen after an implementation changes capability boundaries, public entries, ownership, lifecycle state, generated files, or routing metadata.

Expected agent behavior:

- Rebuild the index when boundaries, public entries, or lifecycle metadata changed.
- Validate the bundle after route-affecting edits.
- Run governance audit after capability/profile/path-map changes.
- Run route evaluation before committing router metadata.
- Record feedback after review, override, or human correction.

Do not:

- Finish a routed change without reporting whether routing metadata changed.
- Assume code tests passing means the router bundle remains current.

## 5. Capability Lifecycle

Field:

- `capability_lifecycle_action`

Delete, merge, deprecate, replace, retire, and migration requests are lifecycle changes. They are review-first because they can invalidate reuse paths and public entries across the repository.

Expected agent behavior:

- Identify `superseded_by`, `deprecation_date`, `migration_note`, affected callers, regression tests, and rollback plan before writing.
- Inspect public entries, dependent modules, related tests, path-to-capability map, and evaluation cases before removal.
- Update profile/catalog lifecycle metadata after the human decision.
- Add or update evaluation cases for the lifecycle decision.

Do not:

- Delete a capability because current changed paths look unused.
- Merge two capabilities without confirming canonical root and caller impact.

## 6. Composite Routing

Field:

- `composite_route`

Composite routes appear when a request spans multiple capability surfaces, for example backend core plus API facade plus frontend transport. The router should identify participants and a primary candidate, but it should not replace deeper engineering analysis.

Expected agent behavior:

- Use `participants` to identify core, facade, adapter, UI, test, migration, or governance surfaces.
- Prefer the core or dependency-priority capability as primary when scores are close.
- Treat multi-capability core changes as review-before-write.
- Let facade, API, and UI layers delegate to the confirmed core capability instead of becoming parallel implementation centers.

Do not:

- Implement business logic in a facade or UI surface because it was the most visible changed path.
- Treat a secondary capability as safe to modify without reading its public entries and contracts.

## 7. Evaluation Regression Capture

Field:

- `evaluation_regression_hints`

Regression hints turn real routing ambiguity into future tests. They should be used after human confirmation, overrides, false positives, false negatives, capability corrections, and lifecycle decisions.

Expected agent behavior:

- Add curated cases to `references/evaluation-set.yaml` when a route was corrected or overridden.
- Include `id`, `request`, `expected_action`, `expected_capabilities`, `changed_paths`, and `risk_level`.
- Prefer real anonymized cases over synthetic cases for mature repositories.
- Keep generated-only evaluation clearly labeled as system self-consistency, not architecture maturity.

Do not:

- Treat evaluation pass as proof that profile boundaries are correct.
- Fix a false negative without adding a regression case.
