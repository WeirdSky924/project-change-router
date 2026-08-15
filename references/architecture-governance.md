# Architecture Governance

PCR 0.4 integrates repository-neutral architecture checks with typed findings and one authoritative execution gate. These checks do not choose an architecture for the user. They verify that declared owners, dependency direction, structure baselines, freshness evidence, and route calibration still match the code being changed.

## Contract and Compatibility

- `skill_version`: `0.4.x`
- `architecture_governance_api_version`: `2`
- `typed_finding_schema_version`: `1`
- `gate_policy_version`: `1`
- `change_flow_api_version`: `1`
- `authorization_api_version`: `1`
- `reuse_engine_api_version`: remains `2`
- Existing bundle schema v1 remains readable.
- Missing 0.4 precision becomes unknown/incomplete evidence; a read-only check does not write defaults into the bundle.
- Installing the skill never bootstraps, rebuilds, or rewrites a repository-local bundle.

Any routing or evaluation semantic change that can alter attested predictions must bump `evaluation_engine_version` and `architecture_governance_api_version` together. The release consistency test rejects drift between the runtime constant and `skill-version.json`.

Architecture checks emit typed findings in PCR's mandatory guardrail layer. The route `action` remains advisory. One deterministic policy table reduces findings to `execution_gate=pass|conditional|blocked`; only that gate and its safety envelope decide current write authority.

## Canonical Check Sequence

For a routed code or boundary change, use this overall sequence. `run-change-flow` orchestrates the middle route/check block; validation and evaluation remain explicit bundle-maintenance steps:

```text
validate-router-bundle
  -> run-evaluation when route truth changed
  -> run-change-flow
       -> resolve-entry
       -> check-bundle-governance
       -> check-index-freshness
       -> check-deps
       -> check-public-api
       -> check-structure
       -> check-reuse
       -> typed findings + baseline delta + relevance closure
       -> execution gate + compact safety envelope
```

The sequence is evidence aggregation, not a substitute for capability tests. Static architecture checks must be combined with the repository's logic, data, integration, and customer-flow verification where those categories apply.

## Import Graph and Dependency Direction

`check_deps.py` builds a repository-local import graph for Python and TypeScript/JavaScript and evaluates Java imports through the declared module map.

The graph distinguishes:

- runtime imports from Python `TYPE_CHECKING` imports;
- runtime imports from TypeScript `import type` and type-only exports;
- runtime cycles from type-only cycles;
- resolved local imports from parser or resolver diagnostics;
- module-to-module edges from imports that stay inside one module.

Runtime dependency violations and runtime cycles are blocking unless they exactly match an approved baseline item. Type-only cycles remain visible but are not misreported as runtime execution cycles. Parser or resolver diagnostics make the evidence incomplete; they are not silently treated as a clean graph.

An `architecture_baseline` item is exact debt inventory, not a wildcard exemption. It must identify the rule and its stable source/target or cycle identity, have a stable owner, and carry lifecycle/exit metadata where required. `UNKNOWN`, unassigned, or provisional baseline owners cannot authorize unattended writes.

`check_deps.py` and `check_public_api.py` require `--comparison-commit` whenever architecture debt is declared. A baseline can suppress a finding only when the same ID, fingerprint, owner, and exit stage existed in that commit's canonical profile or tracked change-rules bundle. A same-change `public-export-count` reduction is accepted only when the ID, module, owner, and exit stage remain fixed and the lower fingerprint is self-consistent; additions, expansion, and owner drift remain blocking.

## Public API Boundaries

`check_public_api.py` verifies declared public surfaces and reports cross-module imports that bypass them. Private/internal segments remain private even when a package prefix otherwise resembles a public import.

Public export counts are evidence for API breadth. A large count is not automatically a design failure, but new bypasses or accidental exports must not be hidden by broadening the baseline or public root.

## Structural Baselines

`check_structure.py` consumes the canonical structure collections in `change-rules.yaml`:

- `central_growth_baseline`
- `forbidden_implementation_roots`
- `exclusive_source_owners`

The profile-only `generated_output_baseline` is a transitional fourth collection. It is deliberately not copied into generated `change-rules.yaml`, so the generated bundle cannot become a second authority for its own snapshot.

It also applies the 800/1200-line file-size bands and immediate directory-width checks to changed code-bearing files. `--comparison-commit` is the explicit comparison boundary for CI and overrides the freshly generated bundle `source_commit`; without either boundary, structure evidence is incomplete and blocking. A clean committed `HEAD` cannot prove what changed from the pull-request or push base by itself.

### Central growth

A central baseline records the approved comparison commit, file/symbol owner, measured line or method surface, forbidden domain residue, and permitted direction of change. Existing debt can be baselined, but net growth beyond the baseline fails. A nominal facade does not satisfy the check when domain logic continues to accumulate behind it.

The rule `source_commit` must resolve to the comparison commit or one of its ancestors and cannot be the current feature commit. The rule itself is also a one-way ratchet: numeric maxima cannot rise, allowed tracked members cannot expand, and tracked or forbidden debt sets cannot shrink relative to the comparison commit's canonical profile or tracked change-rules bundle.

Use `python-class-remove-only` for central classes. Use `python-function-remove-only` for a composition function such as `create_app`; it freezes whole-file lines, function span, nested function count, decorated handler count, and exact nested member names. Removing handlers is allowed, while adding or replacing a handler remains blocking even when the total count is unchanged.

Typical central owners include an application composition root, global database gateway, top-level state controller, or public aggregation module. The correct response to a growth stop is usually `extract` or a focused predecessor, not a larger threshold.

### File-size bands

- Below 800 lines: no size finding.
- Crossing 800 or 1200 lines is blocking.
- Net growth from an 800-1199-line comparison baseline is gate-blocking and requires split evidence according to repository policy.
- Any net growth from a 1200+ comparison baseline is a hard failure unless an exact, time-bounded exception applies.

Existing large files are debt baselines, not permanent exemptions. A later governance package should reduce the baseline.

### Pinned generated outputs

Use `generated_output_baseline` only when reviewed core PCR outputs still preserve curated records that a canonical-input-only rebuild cannot yet reproduce. The `pinned-idempotent-v1` mode covers one closed seven-reference artifact group; profile data cannot supply paths, globs, commands, or ignored fields. `router-config.yaml` remains governed by evaluation attestation and freshness and is excluded to prevent a profile-to-attestation digest cycle.

Every artifact records its own `source_commit` (`full SHA` or `null`), a semantic projection digest, a canonical UTF-8 YAML projection digest, and line count. The closed digest projection removes only top-level `generated_at` and `source_commit`; for `capability_catalog`, it also removes `last_verified_at` and the dates of `curated_bundle_lifecycle_calibrated` and `generated_from_repository_structure` events. `path_to_capability_map.path_index[*].code_file_count` remains in the pinned digest but is comparison-only rebuild volatile: for the same `path_pattern`, and only when both values are valid non-negative integers, the no-write rebuild comparison uses the actual pinned count. No other field is volatile. The rule `source_commit` is the initialization authorization boundary. A non-null artifact source may be older, but it must be an ancestor of both the rule source and the current rebuild source. A 40-character prefix in a SHA-256 repository, symbolic revision, or other resolvable abbreviation is not a full immutable SHA.

The pin binds `canonical_source` to the repository's unique active `.project-change-router.yaml` or `.project-change-router.yml` path and reads that same path from committed provenance. `check_structure.py` and the write-enabled rebuild perform a current no-write rebuild. The actual tracked artifact retains its declared pinned source; a current rebuild may carry a descendant source when the projected semantics are identical. A `null` artifact must rebuild as `null`. Byte comparison substitutes top-level `generated_at`, the listed capability clocks, the validated same-pattern `code_file_count`, and only in this verified ancestor mode the pinned artifact source. Raw tracked bytes, including the actual pinned count, still have to be canonical and match their pinned digest and line snapshot. A missing count, invalid count type, missing artifact, source-mode drift, non-ancestor source, duplicate YAML key, comment, formatting or CRLF change, projected digest mismatch, owner/fingerprint drift, or non-idempotent rebuild invalidates the entire group and preserves all ordinary size findings.

Ordinary `rebuild_index.py` verifies the group before writing. On success it preserves all seven reference files, refreshes `router-config.yaml`, copied schemas, and `latest.json`, and recomputes evaluation attestation against the effective persisted bundle. On failure it writes none of those files and returns structured blocking findings. `bootstrap_router.py` is blocked while the current or committed profile still declares the pin, while the declaration is malformed, or while removal exists only in the worktree. This prevents clear-and-rewrite and deletion bypasses.

The pin requires a stable, non-provisional capability owner with a normalized identity distinct from every reviewer, plus a trusted full source SHA, initialization record, reason, exit stage, and exit condition. When the comparison commit has no prior pin, pass the exact approved fingerprint through `check_structure.py --initialize-generated-output-baseline <fingerprint>` and through `rebuild_index.py --initialize-generated-output-baseline <fingerprint>` for the first write. The profile's initialization record is audit context and cannot authorize itself. A committed prior pin is matched by the closed artifact group, so renaming its ID cannot reset provenance. Remove it only after protected curated records move into canonical profile or governed feedback inputs, `canonical_only` rebuild converges, and the lifecycle removal is committed. It is not an ignore rule or a permanent exemption.

### Directory width

- An immediate directory with 25 or more code-bearing files is wide.
- Eight or more code-bearing siblings sharing a delimited filename prefix form a flat sibling cluster.
- Crossing either threshold or growing existing debt is blocking.
- Unchanged or reduced debt remains visible but non-blocking; a pure rename does not count as net growth.

### Forbidden roots

`forbidden_implementation_roots` prevents new production implementations in compatibility, legacy, generated, test-support, or otherwise non-canonical roots. Each rule must record the comparison `source_commit`: code already present at that commit remains visible debt, while a new code file or per-file net line growth after that commit is blocking. A missing or unreadable comparison is incomplete evidence and stops unattended use; it is not an ignore or a pass. The rule does not prohibit an explicitly governed adapter or migration facade when its lifecycle, callers, and exit condition are recorded.

### Exclusive owners

`exclusive_source_owners` gives one capability a canonical owner for profile-declared protected implementation tokens. It scans supported-language static string evidence and fails closed when a configured path cannot be scanned reliably. It does not infer a semantic duplicate merely because a new transport, cache, store, or DTO uses different identifiers and no protected token. Raw `fetch` calls, framework-specific stores/caches, and duplicate DTO declarations therefore need repository-specific import, identifier, or AST rules in addition to this token gate.

## Reuse Scope

Changed-path reuse scans use exact ownership before broad module ownership:

1. Prefer the most specific path-map entry.
2. Preserve an additional owner only when the same exact path explicitly declares shared ownership.
3. Use module-owner surfaces only when no path-map owner resolves the path.
4. Never turn repository-wide `**` fallback ownership into an implicit full-repository scan.
5. Expand dependency neighbors by one hop only from observed runtime import edges.
6. Do not expand through type-only edges.
7. Return `incomplete` when a changed path is unresolved, unreadable, or affected by parser diagnostics.

An explicit `--full-scan` remains supported. Absence of a changed path is not silently reinterpreted as reliable changed-path evidence.

Read these fields together:

- `result_status`
- `completion_status`
- `evidence_complete`
- `summary.scan.scope`
- `termination_reason`

`bounded`, `incomplete`, `timeout`, `cancelled`, and `error` are never proof that no duplicate exists.

## Freshness

`check_index_freshness.py` compares the current repository with the indexed truth using:

- current Git commit;
- content-derived structure digest;
- indexed path set;
- stale catalog/module/path entries;
- actual changed-path coverage;
- snapshot/parser diagnostics.

File timestamps are not freshness truth. Canonical `router-config.yaml`, the seven core references, and copied schemas remain part of the structural digest even when repository `ignore_paths` cover the bundle; a `system-managed` label identifies ownership but does not prove content. Generated reports, progress logs, and PCR runtime artifacts remain excluded so that checks do not invalidate themselves, with `latest.json` as the explicit self-reference exemption.

Caller-supplied `--changed-path` values are unioned with real staged, unstaged, untracked, and deleted paths; they never replace Git evidence. An indexed source older than current `HEAD` passes only when it is a full immutable ancestor and the structure digest, indexed paths, stale entries, indexed status, current diagnostics, and indexed diagnostics are all exact. A syntactically valid JSON report with a non-object root or wrong collection field types fails with structured `indexed_snapshot_schema` evidence rather than a traceback.

An unmapped changed path fails freshness. Do not remove the path, enlarge ignore patterns, or rewrite evidence to make the check pass. Add or repair the correct owner/path mapping after source review.

Route resolution does not erase a failing global freshness report. It derives typed findings from the complete delta between the indexed source, `HEAD`, the index, the worktree, and untracked files. Paths are compared with the routed capability's forward and reverse dependency closure:

- `task_local_new`: a changed path intersects that closure and remains blocking;
- `task_local_expanded`: a known relevant finding increased and remains blocking;
- `baseline_unchanged`: all failing delta paths are mapped and proven outside that closure, so the global debt stays visible without blocking this route;
- `baseline_reduced` or `resolved`: trusted historical debt decreased or disappeared;
- `unknown`: an unmapped path, incomplete snapshot, stale entry, parser diagnostic, or other unlocalizable evidence remains blocking.

The route report binds compatibility feedback to `authorization_context` and `route_fingerprint`. The flow separately creates an `authorization_request`; only explicit external confirmation can create a bounded grant. Grants bind source/structure/runtime/policy identity, paths, owner, canonical root, route, pre-change snapshot, and mutation envelope. Changed context invalidates them, and consumed authority never revives.

Global evidence is cached, not skipped. Always-global owner/cycle/canonical/public-export/generated-pin invariants reuse a trusted snapshot only when every identity input matches. Changed paths drive recomputation of affected graph nodes and the forward/reverse closure. First scans, dirty worktrees, bounded/incomplete output, and unknown ancestry cannot become trusted baselines.

## Stable Capability Governance

Every stable capability must have:

- one canonical owner;
- a reviewer distinct from an unknown/provisional placeholder;
- lifecycle state and canonical-root metadata;
- public entries or a documented internal-only boundary;
- contracts and related test bindings;
- positive and boundary evaluation coverage.

Generated discovery is allowed to propose candidates, but rebuild preserves curated records and must not replace their owner, lifecycle, public entry, or evaluation truth with heuristics.

## Evaluation and Review-only Mode

Evaluation measures both routing direction and the integrated route contract:

- top-1 action accuracy;
- top-1 capability accuracy;
- review precision and recall;
- capability coverage;
- secondary capability/contract accuracy;
- false-positive and false-negative regressions.

The attestation records `evaluation_engine_version`, and its digest binds the metrics to that engine version plus route-affecting bundle truth. Operational reuse budgets, runtime timeouts, and retention values do not invalidate the attestation; engine or route-semantic scope changes do.

When the configured thresholds, minimum case count, coverage, engine-version match, or attestation are not satisfied, PCR stays `review_only`. Legacy attestations without an engine version require a fresh evaluation and explicit write-back before unattended product writes can resume.

Evaluation cases must come from real routing shapes and include:

- normal `reuse` and `extend` cases;
- an `extract` boundary;
- high-risk `review`/veto cases;
- known false-positive and false-negative regressions;
- changed paths and expected secondary capabilities where relevant.

Do not fabricate cases or weaken thresholds to obtain a passing score.

## Lifecycle and Migration

A shadow or compatibility core is acceptable only when it records:

- lifecycle state (`planned`, `active`, `migrating`, `deprecated`, or `verified` as defined by the host repository);
- canonical replacement owner;
- current caller inventory;
- migration note and compatibility contract;
- test impact;
- measurable exit condition.

Delete, merge, rename, move, or deprecate requests remain lifecycle findings that block until required evidence and authorization are complete. `action=review` describes the investigation direction; historical overrides are not reusable authorization for a new lifecycle transition.

## CI Minimum

CI should fetch sufficient Git history and pass the pull-request base commit or push `before` commit to `run_change_flow.py --comparison-commit`. It should retain the digest-verified full artifact, require complete global and reuse evidence, and verify the authoritative gate plus bundle/evaluation status. It should also run repository capability tests and validate a temporary atomic installation of the skill.

The checks prevent recurrence; they do not close an architecture gap by themselves. A gap closes only after the faulty path is removed or compatibly isolated, callers and imports are verified, the canonical owner is unambiguous, and a regression gate fails when the problem is reintroduced.
