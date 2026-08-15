# Governance Outputs

Route reports are intentionally split into seven governance output groups. These groups are not an external feature bolted onto the router. They are first-class parts of the same `resolve_entry` route contract and must be read together with `action`, `primary_capability`, confidence, and required checks.

The goal is not to make the router behave like a full architecture agent. The goal is to give the agent enough durable, low-token context to avoid writing in the wrong place, duplicating a capability, or treating weak generated evidence as architecture truth.

## Mandatory vs Advisory

Mandatory fields are execution guardrails. The agent must obey them before product-code writes:

- `execution_gate` and its decisive typed findings/policy rules
- `allowed_write_paths`
- `forbidden_write_paths`
- `must_read_targets`, `inventory_targets`, and `unresolved_read_targets`
- `veto_reasons`
- lifecycle review requirements
- confirmed owners, public entries, canonical roots, and dependency direction
- freshness, dependency/runtime-cycle, public API, and structure guardrail failures
- evaluation `review_only` when thresholds or attestation are not satisfied

Advisory fields are structured direction. The agent should use them to decide what to inspect, repair, or ask next, but they are not a substitute for source-code analysis:

- `action`
- `recommended_next_action`
- `recommended_next_steps`
- `safe_next_steps`
- `analysis_directions`
- `why_not_actions`
- `profile_repair_hints`

If these layers appear to conflict, the execution gate and safety envelope win. For example, `action=extend` cannot override `execution_gate=blocked`, while `action=review` can coexist with any gate state and does not itself deny writes.

Gate states are exact: `pass` means relevant evidence is complete without a relevant blocker; `conditional` means only proven unrelated or non-expanding trusted baseline debt remains and a bounded envelope plus pre-change commands exist; `blocked` covers unknown/incomplete evidence, relevant P0/P1 findings, hard invariants, lifecycle/high-risk changes, or unresolved owner/canonical/public API evidence. `gate_shadow` is diagnostic only.

## 1. Review Handling

Fields:

- `block_reason`
- `missing_evidence`
- `analysis_directions`
- `safe_next_steps`
- `suggested_questions`
- `override_requirements`

Trigger this group when `action=review`, evaluation enforcement is `review_only`, lifecycle intent is detected, early-repo evidence is weak, the path map has no candidate, or multiple capabilities overlap. Triggering guidance does not decide the execution gate.

Expected agent behavior:

- Treat `review` as an investigation direction, not a failed route or an independent stop.
- Use `safe_next_steps` for read-only analysis.
- Use `analysis_directions` to decide what code, imports, callers, public entries, tests, and profile entries to inspect.
- Ask only the relevant `suggested_questions`.
- Continue with writes only when `execution_gate` permits them. Where policy supports an override, require a separately persisted, user-confirmed authorization grant matching `override_requirements`.
- Persist and return the original `route_fingerprint`; changed paths, routing truth, action, capability, or write envelope invalidate the authorization.
- Treat `authorization_context` as task-bound evidence. It records authority but never creates, renews, or expands user authority.
- Keep unattended product writes stopped when the authoritative gate is blocked even if top-1 capability selection or `decision_confidence` appears strong.

Do not:

- Turn a `review` into an automatic `new` route just to keep working.
- Treat `review` as a final architecture decision without doing the recommended investigation.
- Reuse an override from a previous phase.
- Treat any action or confidence value as permission to write independently of `execution_gate`.

## 2. Write Constraints

Fields:

- `allowed_write_paths`
- `forbidden_write_paths`
- `must_read_before_edit`
- `must_read_targets`
- `inventory_targets`
- `unresolved_read_targets`

For `execution_gate=blocked`, authoritative `allowed_write_paths` is empty and `forbidden_write_paths` includes `**`; proposed paths remain diagnostic only. `action=review` alone does not force that envelope. For `reuse`, the target capability core should usually be protected from writes. For `extend` and `extract`, writes should stay in routed owner modules or explicitly changed paths. For `new`, writes should stay in a named isolated capability boundary after confirmation.

Expected agent behavior:

- Read every resolved `must_read_target` at its path/symbol/content digest before editing.
- Use directories only as inventory targets. Run each unresolved structured query and keep the target unresolved until one implementation is proven.
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
- Give each stable capability one explicit `capability_ownership` primary owner and a distinct reviewer. Missing, duplicate, generated-placeholder, `UNKNOWN`, unassigned, and provisional identities remain review-only.
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
- Run freshness, dependency/runtime-cycle, public API, and structure checks when their routed boundary changed.
- Run route evaluation before committing router metadata.
- Record feedback after review, override, or human correction.

Do not:

- Finish a routed change without reporting whether routing metadata changed.
- Assume code tests passing means the router bundle remains current.

## 5. Capability Lifecycle

Field:

- `capability_lifecycle_action`

Delete, merge, deprecate, replace, retire, and migration requests are lifecycle changes. They emit mandatory lifecycle evidence and block until required metadata/authorization is complete because they can invalidate reuse paths and public entries across the repository. `action=review` remains advisory investigation direction.

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

## 8. Unified Flow and Compact Safety Envelope

`run_change_flow.py` is the preferred agent-facing pre-change entry point. It runs route, dependency, public API, structure, freshness, governance, and reuse checks; normalizes typed findings; classifies trusted-baseline deltas and task relevance; reduces the authoritative gate; and emits ordered pre-change/closeout commands.

The default `compact-json` output includes the decision, precise reads, decisive delta, next commands, runtime identity, and this fixed safety envelope: `execution_gate`, `veto_reasons`, `allowed_write_paths`, `forbidden_write_paths`, `unknown_evidence`, `artifact_path`, `artifact_digest`, and `output_complete`. Projection cannot remove those fields. The full evidence report is content-addressed, and consumers must verify the artifact bytes against `artifact_digest` before relying on it.

## 9. Trusted Baseline and Incremental Global Evidence

The flow remains globally governed. It caches proof for always-global invariants and recomputes changed graph nodes plus the forward/reverse route closure; it does not replace global checks with changed-path-only scans. A baseline can become trusted only from a clean, complete commit scan, trusted CI output, or explicit acceptance of the exact candidate fingerprint. Dirty, first-run, bounded, incomplete, or ancestry-unknown snapshots remain candidates or unknown.

Baseline and cache identity includes commit, profile, bundle, structure, indexed paths, scope, runtime/tool/parser/policy versions, and evidence digest. Reports expose reused, recomputed, invalidated, and unresolved nodes/edges plus `task_local_new`, `task_local_expanded`, `baseline_unchanged`, `baseline_reduced`, `resolved`, and `unknown` deltas.

## 10. Authorization Request and Grant

A route or flow `authorization_request` is a bound request context, not authority. `manage_authorization.py grant` may record authority only after an external user confirmation, including its source and exact confirmation text. Grants default to one use and 24-hour expiry, may be explicitly bounded to at most 100 uses and 30 days, and bind the pre-change snapshot, route, owner, canonical root, paths, mutation envelope, context digest, and immutable grant binding digest.

Every state transition is recorded in a chained audit event. A relevant context change invalidates the grant. A consumed, expired, rejected, or invalidated grant can never return to `granted`, even if later input is byte-identical. Legacy route-fingerprint feedback remains compatibility evidence and never renews a grant.

## Architecture Guardrail Context

The seven output groups are interpreted alongside the read-only architecture reports; those reports are not an eighth advisory action group.

- `check_deps.py` distinguishes Python and TypeScript/JavaScript runtime edges from Python `TYPE_CHECKING` and TypeScript type-only edges. Runtime cycles and reversed dependencies block unless an exact approved baseline identity matches.
- `check_public_api.py` reports cross-module private-surface bypasses and public export breadth against the same exact-baseline contract.
- `check_structure.py` enforces changed-file 800/1200-line bands plus `central_growth_baseline`, `forbidden_implementation_roots`, `exclusive_source_owners`, and atomic profile-only verification for an explicitly pinned core generated bundle. Verified rebuilds preserve all seven tracked refs; failed verification performs no bundle/report write.
- `check_index_freshness.py` binds evidence to the current commit, a content-derived structure digest, indexed/stale paths, report field shapes, and actual changed-path coverage. Explicit paths cannot hide Git changes, and ancestor commits require an otherwise exact snapshot.
- `run_evaluation.py` reports `normal` or `review_only`; attestation binds accepted metrics to route-affecting bundle truth.

An exact baseline is owned debt with a stable identity and exit condition, not permission to add another violation. Parser/resolver diagnostics or unmapped changed paths make evidence incomplete. Static evidence supplements rather than replaces capability, logic, data, integration, and customer-flow tests.
