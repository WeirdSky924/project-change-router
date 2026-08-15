# Evaluation

The repository-local bundle includes `references/evaluation-set.yaml`.

## Purpose

The evaluation set prevents routing logic from drifting silently. It evaluates advisory routing behavior and capability coverage; it is not a verdict that the whole guardrail model is usable or unusable.

- expected route actions
- expected primary capabilities
- expected secondary capabilities and route contracts
- expected module reads
- review cases for ambiguous or high-risk changes
- false-positive and false-negative regression cases

Action accuracy failures usually mean the advice layer needs calibration. They do not automatically invalidate mandatory guardrails such as owners, canonical roots, read/write constraints, veto signals, or duplicate-implementation checks.

## Minimum Expectations

- at least 30 cases for the first real rollout
- action accuracy threshold of 0.85
- primary capability accuracy threshold of 0.85
- review precision threshold of 0.90 on high-risk cases
- review recall threshold of 1.00 so high-risk review/veto cases have no false negatives
- capability coverage ratio of at least 0.80
- secondary capability/contract accuracy threshold of 1.00 when strict enforcement is enabled
- new routing failures should become new cases

These values are enforcement floors, not suggested defaults that a profile may lower. A repository may tighten them, but a lower value keeps PCR in `review_only`.

## Evaluation Categories

- `reuse`
- `extend`
- `extract`
- `new`
- `review`

## Recommended Policy

Do not expand unattended hard enforcement from advisory actions until the evaluation set passes every configured threshold, reaches the minimum case count, and has a current attestation. Mandatory boundary checks and write constraints can still protect the agent while the advice layer is being calibrated.

The runtime reports `enforcement_mode=review_only` if enforcement is missing or disabled, metrics are missing or outside `[0,1]`, any threshold is below its floor, curated provenance is incomplete, the attestation is absent, its evaluation-engine version is missing or stale, or its digest no longer matches route-affecting bundle truth. The flow adapts this evidence into typed findings and the authoritative execution gate; `review_only` is not an action rewrite. A plausible top-1 capability match does not override a blocked gate. Read-only analysis, profile repair, and evaluation maintenance may continue.

Generated evaluation covers every generated or profile-backed capability that the bundle can identify, but generated cases are diagnostic only and never authorize `normal`. Rebuild records trusted human cases in `curated_case_ids`; hybrid accuracy and case-count metrics use only those IDs. A legacy curated/hybrid file without that provenance remains readable but review-only until its real cases are moved into the canonical profile and rebuilt.

The curated set must cover all six calibration categories: `positive_reuse`, `positive_extend`, `extract_boundary`, `review_veto`, `false_positive_regression`, and `false_negative_regression`. Every curated case must declare an exact, catalog-valid `expected_primary_capability`; a legacy `expected_capabilities` membership list is not strong enough for `normal`. Repositories with more than one stable capability must also include exact, catalog-valid secondary-capability evidence; no-evidence secondary accuracy is not treated as production proof.

## Attestation

The evaluation attestation records `evaluation_engine_version` and binds selected metrics to a digest of that version, the capability catalog, module map, route-semantic change rules, and evaluation set. A change to routing/evaluation semantics, capability ownership, path mapping, dependency policy, architecture baseline, or reuse scope invalidates the attestation until evaluation is rerun.

Operational scan settings such as reuse budgets, runtime timeouts, cache mode, diagnostics, and retention do not change route semantics and therefore do not invalidate the evaluation digest. This distinction prevents routine operations tuning from granting or revoking route authority.

Read-only compatibility checks never write an attestation or new default fields into an old schema-v1 bundle. A legacy attestation without `evaluation_engine_version` remains readable but cannot authorize `normal`. After an evaluation-engine upgrade, rerun evaluation and use the explicit index write-back workflow to persist a passing current-version attestation.

## Regression Capture

Route reports include `evaluation_regression_hints` when a route needs review or captures an important correction opportunity. Add a curated case when:

- a human overrides `review`
- the predicted action was wrong
- the predicted capability was wrong
- a missing owner, public entry, or path mapping caused ambiguity
- a delete, merge, deprecate, or migration decision was confirmed

Curated cases should include `id`, `request`, `expected_action`, `expected_primary_capability`, `expected_capabilities`, `changed_paths`, `risk_level`, and `calibration_category`. Strict composite cases also declare `expected_secondary_capabilities` and `secondary_match: exact`.

Use real routing shapes. A mature set should include normal `reuse` and `extend` positives, an `extract` boundary, high-risk `review`/veto cases, and known false-positive/false-negative regressions. Do not fabricate cases, remove difficult paths, or weaken thresholds to obtain `normal` enforcement.
