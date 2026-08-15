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
3. Prefer `scripts/run_change_flow.py` with the request text and known changed paths. It preserves legacy command behavior while providing the compact agent-facing orchestration path.
4. Read `execution_gate` and the non-projectable safety envelope before interpreting advisory `action`.
5. The flow resolves the route and aggregates `check_bundle_governance`, `check_index_freshness`, `check_deps`, `check_public_api`, `check_structure`, and `check_reuse`. It consumes the bundle's current evaluation policy/attestation as route evidence; run `validate_router_bundle.py` and `run_evaluation.py` separately when route metadata or evaluation truth changes.
6. Normalize all gate-affecting evidence into schema-valid typed findings and deterministically reduce `execution_gate=pass|conditional|blocked` through one policy table.
7. Read exact `must_read_targets`; inventory directory targets without blind full reads; execute unresolved structured queries before editing.
8. If blocked, do not write product code. If conditional, run all required commands and stay inside the bounded envelope. If pass, still preserve the envelope.
9. Use `action` only to guide reuse/extend/extract/new/review engineering analysis. It cannot override the gate.
10. After changes, execute `post_change_closeout` and update the bundle only if the change created a capability or changed an owner, public boundary, lifecycle, or indexed structure.

For `check_reuse.py`, `result_status` and `completion_status` answer different questions. A non-failing result does not close the duplicate check when `completion_status` is `bounded`, `incomplete`, `timeout`, `cancelled`, or `error`. Read `summary.scan.scope` and continue targeted source analysis; never expand an unresolved changed path into an implicit repository-wide scan.

## Two-Layer Contract

PCR is not an automatic architecture decision engine. It separates mandatory guardrails from advisory routing guidance.

Mandatory guardrails:

- `execution_gate`, typed findings, and policy traces
- `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`
- canonical roots, owners, public entries, and dependency direction
- duplicate implementation warnings
- `veto_reasons`, unknown evidence, lifecycle findings, provisional boundaries, and high-risk overlaps

Advisory guidance:

- `action`
- `recommended_next_action`
- `recommended_next_steps`
- `safe_next_steps`
- `analysis_directions`
- `why_not_actions`
- `profile_repair_hints`

Use advisory fields to decide what to inspect next and how to unblock the route. `action=review` may coexist with any gate state and is never a second decision engine. Final implementation choices still require source-code analysis, tests, and user-confirmed scope.

## Route Outputs

The resolver emits one integrated route report. Governance fields are not an optional side channel; they are part of the route contract and must be interpreted with `action`, `primary_capability`, and confidence. Mandatory guardrails take precedence over advisory actions.

The report includes:

- authoritative execution gate, matched policy rules, decisive finding IDs, and unknown evidence
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
- symbol/digest-bound must-read targets, directory inventory targets, and unresolved query commands
- runtime identity, baseline delta, incremental cache summary, authorization request, and content-addressed artifact reference

The detailed contract for these integrated outputs is in `references/governance-outputs.md`.

## Review Handling

When `action=review`, use `safe_next_steps`, inspect the referenced bundle/code evidence, repair routing metadata after confirmation, and ask only relevant questions. Do not infer write authority from review or any other action.

The skill gives direction, not final architecture decisions. Use `analysis_directions` to decide what to inspect next, then make the engineering call from real code, profile data, tests, and user confirmation.

To continue after an authoritative block where policy permits an override, persist an authorization request scoped to the current task, phase, changed paths, owner, route, pre-change snapshot, and mutation envelope. Record explicit user confirmation as a grant; do not reuse a Phase 0 grant for later phases or revive consumed authority.

Evaluation `review_only` is calibration evidence, not an action rewrite. Missing, stale, or below-threshold attestation becomes a typed finding that the authoritative gate evaluates; a plausible top-1 capability selection cannot override a blocked gate.

## Write Constraints

Before editing, read the exact path/symbol/content digest in `must_read_targets`. Directories are inventory-only; unresolved targets require the supplied structured query. Writes are allowed only under the authoritative `allowed_write_paths` and must avoid `forbidden_write_paths`. A blocked gate forces an empty allowed set and `**` forbidden; `action=review` alone does not.

## Closeout

After implementation, follow `post_change_closeout`. If capability boundaries, public entries, ownership, lifecycle metadata, or generated files changed, run rebuild/validate/governance/evaluation and record feedback where needed.

## Governance Checks

Run `scripts/check_bundle_governance.py` when onboarding a repository, after a large structure change, or when route results repeatedly stop with missing capability candidates.

Treat P0 findings as blockers. P1 findings should usually become profile/catalog or evaluation-set work before unattended execution continues. P2 findings are maintenance items. Stable capabilities require one canonical owner, a distinct reviewer, lifecycle metadata, public or internal-only boundary documentation, contracts/test bindings, and positive plus boundary evaluation cases.

## Architecture Evidence

`check_deps.py` resolves Python and TypeScript/JavaScript import graphs. It separates runtime edges from Python `TYPE_CHECKING` and TypeScript `import type`/type-only export edges. Runtime cycles and reversed dependencies block unless an exact approved `architecture_baseline` item matches. Type-only cycles remain visible but do not masquerade as runtime cycles. Parser or resolver diagnostics make evidence incomplete. `check_public_api.py` uses the same exact-baseline contract for public-API debt.

`check_structure.py` enforces changed-file 800/1200-line bands and the profile-backed `central_growth_baseline`, `forbidden_implementation_roots`, and `exclusive_source_owners` collections. A profile-only `generated_output_baseline` may atomically verify a closed, reviewed core PCR bundle during canonical-profile migration. Each artifact retains its own full-SHA-or-null pinned provenance; a non-null source may predate the rule and current rebuild only when it is an ancestor of both and projected semantics remain exact. Ordinary rebuild preserves the seven tracked refs after verification, refreshes only the observation/config surfaces, and writes nothing on verification failure. Any byte, digest, line, source-mode, owner, provenance, or idempotence mismatch restores the normal size stop. Existing debt is an exact, owned, exit-bound baseline, never a wildcard exemption.

`check_index_freshness.py` compares the current commit, content-derived structure digest, indexed and stale paths, report field shapes, and changed-path coverage. Explicit paths are unioned with real Git changes. An ancestor source passes only with an otherwise exact snapshot. Canonical config, seven core references, and schemas remain digest inputs even when bundle paths are ignored; only the self-referential latest report is exempt. File timestamps, ignored real paths, malformed report collections, and generated PCR runtime reports are not substitutes for source truth.

Static evidence supplements the repository's logic, data, integration, and customer-flow tests. It does not replace them.

The resolver should never treat the catalog as infallible. Real code remains the final source of truth.
