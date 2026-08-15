# Typed Findings and Incremental Global Gate TODO

Status: completed (PCR 0.4.0)

Scope: PCR next-stage routing evidence, execution gate, incremental global checks,
reuse coverage, compact output, must-read precision, and authorization lifecycle.

This document is the completed implementation backlog and acceptance contract.
`execution_gate` is authoritative in 0.4.0; `gate_shadow` retains the legacy/new
comparison as diagnostic evidence only.

## 1. Product Position

PCR remains a direction, ownership, boundary, and reuse-governance system. It does
not replace source reading or the coding agent's engineering analysis.

- Mandatory: canonical owner/root, public entry, write envelope, veto evidence,
  lifecycle constraints, unresolved high-risk evidence, and duplicate-owner risk.
- Advisory: `action`, `why_not_actions`, analysis directions, and suggested unblock
  steps.
- `action` and `execution_gate` are independent outputs. `action=review` does not
  imply either `conditional` or `blocked` without typed evidence and gate policy.
- The objective is not to relax governance. It is to distinguish task-local risk,
  relevant historical risk, unrelated historical debt, and unknown evidence.

### 1.1 Problem and Revision Traceability

The roadmap comes from repeated use in a large Godview repository. Some reported
findings, such as stale bundle data, dynamic-import debt, and existing structural
debt, belong to the host repository. PCR correctly exposed them. PCR's defect was
that it could not reliably classify whether those findings were introduced by,
expanded by, relevant to, or unrelated to the current task.

The design evolved through these corrections:

| Observed problem | Unsafe or incomplete first response | Final design constraint |
| --- | --- | --- |
| An exact path with a known owner and no new finding was blocked because the bundle contained stale global debt. | Let `review` become writable or check only changed paths. | Keep action and gate independent. Classify typed findings by delta and relevance, while preserving global invariants. |
| Reuse checks resolved exact scope but repeatedly ended `incomplete` after many serial scans. | Scan each capability independently and treat bounded completion as sufficient. | Use independent intra-capability, cross-capability, and lifecycle/new/extract channels. Every channel reports coverage; bounded evidence never proves absence. |
| The same dependency, public API, structure, and freshness findings appeared on every run. | Cache reports using broad worktree state or accept the first scan as baseline. | Cache actual evidence inputs and affected graph nodes. Only trusted, fully bound snapshots can become baselines. |
| Full candidates, profiles, and diagnostics polluted the agent's main context. | Allow arbitrary field projection. | Add compact and artifact-reference output only through the new flow, with a non-projectable safety envelope. |
| `must_read_before_edit` returned directories or broad entries. | Add more path hints or rely on line numbers. | Bind exact read targets to path, symbol, and content digest. Directories are inventory targets; line numbers are hints. |
| Route, implementation, and closeout authorization depended on manual notes. | Reuse a matching manifest as authorization. | Separate authorization request from user-created grant. A manifest records authority, and consumed authority cannot revive. |
| Identical path sets sometimes produced different overlap, coordination, or secondary capabilities without explanation. | Stabilize output ordering only. | Give findings stable identities, evidence digests, policy rules, and explicit old/new evidence deltas. |
| Agents manually orchestrated route, per-path reuse, dependency, public API, structure, freshness, and closeout commands. | Change every legacy command to compact output. | Preserve legacy command semantics and add `run_change_flow.py` as the compact orchestrator with ordered required commands. |

The external review also corrected four important assumptions:

1. Freshness was not merely a module-map timestamp check. The installed version
   already evaluated source commit, structure digest, indexed paths, changed-path
   coverage, and diagnostics. Implementation must therefore freeze skill commit,
   install digest, schema/API version, and policy version before comparing behavior.
2. Global checks cannot become changed-path-only. The correct unit is a trusted
   global snapshot plus changed-path-driven recomputation of affected graph nodes and
   the route-relevant closure.
3. A baseline is security-sensitive evidence. First scans, dirty worktrees, and
   bounded or incomplete reports remain candidate or unknown and cannot be promoted
   automatically.
4. Shadow mode is required before authority cutover. The existing gate remains
   authoritative until positive and adversarial replays prove that false blocking is
   reduced without weakening unknown, high-risk, ownership, lifecycle, public API,
   or cross-capability protections.

This traceability is normative: later implementation must not remove a safety
constraint merely to improve pass rate, runtime, or output size.

## 2. Existing Foundation

The following foundations already exist and must be evolved instead of duplicated:

- [x] Global freshness reporting remains visible.
- [x] Route-local freshness classifies `task_local_new`, `baseline_unchanged`, and
  `unknown` against forward and reverse capability dependencies.
- [x] Route authorization is bound to `authorization_context` and
  `route_fingerprint`.
- [x] Reuse report identity uses actual scanned-source fingerprints instead of the
  entire worktree status.
- [x] Reuse scans expose bounded/incomplete evidence and cannot claim completeness
  after timeout, cancellation, or budget exhaustion.
- [x] Bundle schema v1 remains readable.

The following target capabilities are complete:

- [x] One normalized typed-finding contract across all checks.
- [x] A deterministic three-state `execution_gate` derived from one policy table.
- [x] Trusted baseline and candidate-snapshot lifecycle.
- [x] Changed-path-driven incremental global graph caching.
- [x] Independent intra-capability and cross-capability reuse channels.
- [x] Compact safe-envelope output and `run_change_flow.py`.
- [x] Symbol/digest-bound must-read targets.
- [x] Separate authorization request/grant state machine with non-revival semantics.
- [x] Shadow-mode replay and authority cutover.

## 3. Target Data Flow

```text
route evidence
  -> normalized typed findings
  -> delta and task-relevance classification
  -> deterministic gate policy table
  -> execution_gate(pass | conditional | blocked)

action(reuse | extend | extract | new | review)
  -> advisory direction only
```

No stage after typed-finding normalization may invent new evidence. The gate reducer
may only evaluate normalized fields through versioned policy rules.

## 4. Typed Finding Contract

Every blocking, conditional, or informational result must emit at least:

```json
{
  "finding_id": "stable-content-derived-id",
  "type": "unindexed_path",
  "severity": "P1",
  "invariant_class": "task_local",
  "origin": "freshness",
  "delta_state": "task_local_new",
  "task_relevance": "relevant",
  "evidence_status": "complete",
  "policy_rule_id": "GATE-PATH-001",
  "paths": ["app/example.py"],
  "capabilities": ["example-capability"],
  "evidence_digest": "sha256"
}
```

Required enums:

- `severity`: `P0`, `P1`, `P2`, `P3`, `info`.
- `invariant_class`: `always_global`, `closure_global`, `task_local`.
- `delta_state`: `task_local_new`, `task_local_expanded`,
  `baseline_unchanged`, `baseline_reduced`, `resolved`, `unknown`.
- `task_relevance`: `relevant`, `unrelated`, `unknown`.
- `evidence_status`: `complete`, `bounded`, `incomplete`, `stale`, `invalid`,
  `unavailable`.

TODO:

- [x] Add a versioned finding schema and Python model.
- [x] Define stable finding identity and canonical serialization.
- [x] Add adapters for freshness, ownership, dependency, public API, structure,
  generated-output, reuse, and lifecycle results.
- [x] Reject missing required fields before gate reduction.
- [x] Preserve original check evidence by digest and artifact reference.
- [x] Document which origins may emit each finding type.

Acceptance:

- Every gate-affecting result can be traced to one `finding_id`, one artifact digest,
  and one `policy_rule_id`.
- The reducer contains no repository scanning, name matching, or heuristic routing.

## 5. Deterministic Execution Gate

Define exactly three states:

- `pass`: all relevant evidence is complete and no relevant blocking finding exists.
- `conditional`: only known unrelated or non-expanding baseline debt remains, and
  the report supplies a bounded write envelope plus required pre-change commands.
- `blocked`: any unindexed path, unknown owner/canonical root, relevant freshness
  unknown, high-risk/lifecycle finding, relevant P0/P1 finding, or incomplete
  relevant dependency closure exists.

TODO:

- [x] Implement one versioned gate policy table over typed-finding fields.
- [x] Keep action calculation outside the gate reducer.
- [x] Emit `gate_policy_version`, matched rule IDs, decisive finding IDs, and a
  deterministic explanation order.
- [x] Require `allowed_write_paths` and pre-change commands for `conditional`.
- [x] Forbid `conditional` when task relevance or evidence completeness is unknown.
- [x] Preserve the legacy gate as authoritative during shadow mode; after cutover,
  retain it as diagnostic `gate_shadow` evidence.

Required regression cases:

- [x] Known unrelated baseline debt plus exact owner and complete closure ->
  `conditional`.
- [x] Second owner -> `blocked`.
- [x] Unindexed changed path -> `blocked`.
- [x] New public export conflict -> `blocked`.
- [x] Relevant unresolved/dynamic import -> `blocked`.
- [x] Cross-capability canonical duplication -> `blocked`.

## 6. Incremental Global Invariants

Use changed paths to drive incremental recomputation without dropping global truth.

`always_global`:

- canonical owner uniqueness;
- dependency cycles;
- canonical-root uniqueness;
- public-export conflicts;
- generated-output pin and provenance integrity.

`closure_global`:

- callers and callees;
- public entries;
- shared substrate;
- dynamic/unresolved imports;
- forward and reverse capability dependencies.

`task_local`:

- changed-path capability and write boundary;
- local duplicate implementation;
- changed symbols and local tests.

TODO:

- [x] Define graph node and edge identities independent of report ordering.
- [x] Cache a trusted global snapshot and recompute affected nodes plus transitive
  closure.
- [x] Keep always-global checks active through cached proof, not by skipping them.
- [x] Invalidate affected cache entries when source, profile, path, owner, public
  entry, parser, tool, or policy identity changes.
- [x] Emit reused-node, recomputed-node, invalidated-node, and unresolved-node counts.

## 7. Trusted Baseline

Allowed baseline sources:

- a confirmed complete global check on a clean commit;
- a CI-produced and verified snapshot;
- a user-accepted historical-debt snapshot bound to a complete input fingerprint.

Disallowed automatic baseline sources:

- first scan;
- dirty-worktree scan;
- bounded, incomplete, stale, or invalid evidence;
- a snapshot whose source commit, profile, bundle, or structure cannot be verified.

Every baseline must bind:

```text
commit + profile digest + bundle digest + structure digest + indexed paths digest
+ tool version + policy version + evidence digest
```

TODO:

- [x] Add `candidate_snapshot`, `trusted_baseline`, `superseded`, and `invalid`
  lifecycle states.
- [x] Require explicit provenance and promotion authority.
- [x] Prevent dirty or incomplete snapshots from promotion.
- [x] Record baseline delta as new, expanded, unchanged, reduced, or resolved.
- [x] Fail closed when baseline ancestry or any identity component is unknown.

## 8. Task-Relevance Closure

The relevance graph must include:

- changed paths;
- capability owners and public entries;
- callers and callees;
- shared substrate;
- test bindings;
- forward and reverse capability dependencies.

TODO:

- [x] Normalize all closure nodes to stable path/symbol/capability identities.
- [x] Mark relevance `unknown` when a closure edge is unresolved or dynamic.
- [x] Allow known historical dynamic-import debt outside the closure to become
  `baseline_unchanged + unrelated` only with trusted baseline proof.
- [x] Emit the exact path from each changed node to each decisive finding.

## 9. Reuse Coverage Channels

Run and report these channels independently:

1. Intra-capability duplication among the routed owner, public entries, and bound
   tests.
2. Cross-capability checks for shared paths, canonical-owner collisions, and shared
   substrate.
3. Extended scans for `new`, `extract`, lifecycle, migration, and public-contract
   requests.

TODO:

- [x] Give every channel its own scope digest, coverage, budget, completion status,
  skipped reasons, and evidence digest.
- [x] Cache normalized source fingerprints by actual scanned files.
- [x] Preserve cancellation and configured timeout through every nested scanner.
- [x] Prevent bounded results from emitting a global no-duplicate conclusion.
- [x] Require cross-capability coverage before `new` or `extract` can avoid review.
- [x] Add regression fixtures for shared-path and canonical duplication.

## 10. Compact Output and Unified Flow

Existing commands retain their current output semantics. Add a new
`run_change_flow.py` entry that orchestrates route, checks, and closeout and defaults
to compact output.

The following safety envelope is mandatory and cannot be removed by `--fields`:

- `execution_gate`;
- `veto_reasons`;
- `allowed_write_paths`;
- `forbidden_write_paths`;
- `unknown_evidence`;
- `artifact_path`;
- `artifact_digest`;
- `output_complete`.

TODO:

- [x] Define `compact-json`, `artifact-reference`, and full diagnostic modes.
- [x] Return only decision, safety envelope, decisive delta, and next command by
  default from the new flow.
- [x] Store full findings in a content-addressed artifact.
- [x] Add projection validation that rejects attempts to hide safety-envelope fields.
- [x] Emit executable `required_commands` in dependency order.
- [x] Make artifact completeness explicit when any child check is bounded or fails.

## 11. Precise Must-Read Targets

Replace ambiguous path-only reads with:

```json
{
  "path": "app/service.py",
  "symbol": "WorkflowService.execute",
  "content_digest": "sha256",
  "line_hint": 120,
  "reason": "canonical implementation",
  "resolution_status": "resolved"
}
```

TODO:

- [x] Add `must_read_targets` for exact files and symbols.
- [x] Move directories to `inventory_targets`; never require blind full-directory
  reading.
- [x] Treat line numbers as hints, not stable identity.
- [x] Emit a structured query command and keep the target unresolved when a unique
  implementation cannot be proven.
- [x] Invalidate the target when its content digest changes.

## 12. Authorization State Machine

Separate authorization into:

- `authorization_request`: the requested task/path/mutation envelope and required
  user decision;
- `authorization_grant`: an immutable record of the user's actual confirmation.

The manifest records authority but cannot create, broaden, renew, or restore it.

Required grant bindings:

- pre-change snapshot and route fingerprint;
- task identity and authorized paths;
- owner, canonical root, and route;
- mutation envelope;
- authorization source and exact user confirmation;
- issue time, state, and consumption record.

Required states:

```text
requested -> granted -> consumed
                    -> invalidated
requested -> rejected | expired
```

TODO:

- [x] Define request and grant schemas separately.
- [x] Make grants single-use unless the user explicitly authorizes a bounded
  multi-step envelope.
- [x] Invalidate on relevant source, profile, path, owner, route, policy, or mutation
  change.
- [x] Prevent a consumed grant from returning to `granted`, even when all inputs are
  byte-identical.
- [x] Audit every state transition with a chained digest.
- [x] Preserve legacy route-fingerprint feedback as compatibility input, never as an
  automatically renewable grant.

## 13. Version Identity and Compatibility

Every report and artifact must include:

- skill semantic version;
- skill Git commit;
- installed payload digest;
- schema version;
- public API version;
- gate policy version;
- parser/scanner version where relevant.

TODO:

- [x] Add one canonical runtime identity provider.
- [x] Bind cache, baseline, findings, authorization, and artifact identity to it.
- [x] Keep bundle schema v1 readable.
- [x] When legacy input cannot provide required precision, emit `unknown` and keep
  the gate blocked instead of fabricating defaults.
- [x] Document upgrade behavior without rewriting existing repository-local bundles.

## 14. Shadow Mode and Cutover

Shadow mode was mandatory before the 0.4.0 cutover. The legacy gate remained
authoritative during replay; the new gate is now authoritative and the same
comparison remains available as `gate_shadow` diagnostic evidence.

Each shadow report must include:

- old and new gate states;
- decisive finding and policy-rule differences;
- old/new allowed and forbidden paths;
- cache-hit and invalidation evidence;
- whether the disagreement is safer, equivalent, or less safe;
- artifact references for replay.

Required replay suites:

- [x] Godview INT-04: exact owner, no new finding, unrelated stale debt may become
  `conditional`.
- [x] Second owner remains `blocked`.
- [x] Unindexed path remains `blocked`.
- [x] New public export remains `blocked` until confirmed.
- [x] Relevant unresolved/dynamic import remains `blocked`.
- [x] Cross-capability duplication remains `blocked`.
- [x] Any relevant source/profile/path/owner change invalidates cache and grant.
- [x] Bundle schema v1 without sufficient evidence becomes `unknown/blocked`.

Cutover criteria:

- No known case where the new gate is less strict for unknown or relevant P0/P1
  evidence.
- Every conditional result has complete evidence, trusted baseline proof, exact
  write envelope, and required commands.
- Replays are deterministic across repeated cold and warm runs.
- Differences are explainable by stable finding IDs and policy rules.
- The user explicitly approves making the new gate authoritative.

## 15. Implementation Order

### Phase 0: Freeze identity and fixtures

- [x] Record current skill/API/schema versions and install digest behavior.
- [x] Freeze representative Godview and synthetic replay inputs.
- [x] Capture old-gate outputs as immutable comparison artifacts.

Exit: replay inputs and old outputs are reproducible from clean commits.

### Phase 1: Evidence model

- [x] Implement typed findings and adapters.
- [x] Implement invariant classes, trusted-baseline schema, and relevance closure.
- [x] Add schema and deterministic serialization tests.

Exit: all current checks can emit valid typed findings without changing authority.

### Phase 2: Shadow gate

- [x] Implement the deterministic policy table and three gate states.
- [x] Run old and new gates together; old gate remained authoritative during shadow.
- [x] Persist disagreement artifacts and policy traces.

Exit: required positive and blocking replays pass in shadow mode.

### Phase 3: Incremental global engine

- [x] Add trusted global snapshots, graph invalidation, and delta summaries.
- [x] Add capability and cross-capability reuse channels.
- [x] Verify cold/warm equivalence and invalidation behavior.

Exit: warm runs reuse proof without hiding global invariants or stale evidence.

### Phase 4: Agent-facing workflow

- [x] Add compact safe-envelope output.
- [x] Add exact must-read targets and structured unresolved queries.
- [x] Add `run_change_flow.py` and ordered required commands.

Exit: a normal agent route can proceed without loading full diagnostic artifacts into
the main conversation.

### Phase 5: Authorization lifecycle

- [x] Implement authorization request/grant schemas and state transitions.
- [x] Add single-use consumption, invalidation, expiry, and audit chaining.
- [x] Prove consumed grants cannot revive.

Exit: authorization can be independently verified and never self-created.

### Phase 6: Authority cutover

- [x] Complete Godview and synthetic replay review.
- [x] Compare false block, false pass, and unknown classifications.
- [x] Obtain explicit cutover approval through the requested TODO implementation.
- [x] Make the new gate authoritative while retaining rollback diagnostics.

Exit: the old gate is no longer authoritative, but compatibility reports remain
available for one documented transition window.

## 16. Completion Definition

This roadmap is complete only when:

- [x] All gate decisions reduce from schema-valid typed findings and a versioned
  policy table.
- [x] Global invariants remain proven through complete recomputation or trusted cache.
- [x] Baselines cannot be laundered from dirty or incomplete evidence.
- [x] Relevant unresolved closure evidence blocks.
- [x] Bounded reuse never claims absence of duplication.
- [x] Compact output cannot hide the safety envelope.
- [x] Must-read targets are symbol/digest-bound or explicitly unresolved.
- [x] Authorization grants are externally created, narrowly bound, and irreversible
  after consumption.
- [x] Shadow replays demonstrate reduced false blocking without weaker unknown-risk
  handling.
- [x] Documentation, schemas, fixtures, CI, migration notes, and anonymous real-repo
  examples are synchronized.

## 17. Non-Goals

- Do not turn PCR into a general-purpose coding or architecture agent.
- Do not make route action a write authorization.
- Do not hide global debt to improve pass rates.
- Do not treat bounded scanning as complete evidence.
- Do not auto-promote snapshots or auto-grant overrides.
- Do not rewrite existing repository-local bundles during skill installation.
