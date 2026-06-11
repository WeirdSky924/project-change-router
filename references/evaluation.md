# Evaluation

The repository-local bundle includes `references/evaluation-set.yaml`.

## Purpose

The evaluation set prevents routing logic from drifting silently. It evaluates advisory routing behavior and capability coverage; it is not a verdict that the whole guardrail model is usable or unusable.

- expected route actions
- expected primary capabilities
- expected module reads
- review cases for ambiguous or high-risk changes

Action accuracy failures usually mean the advice layer needs calibration. They do not automatically invalidate mandatory guardrails such as owners, canonical roots, read/write constraints, veto signals, or duplicate-implementation checks.

## Minimum Expectations

- at least 30 cases for the first real rollout
- action accuracy threshold of 0.85
- review precision threshold of 0.90 on high-risk cases
- capability coverage ratio of at least 0.80
- new routing failures should become new cases

## Evaluation Categories

- `reuse`
- `extend`
- `extract`
- `new`
- `review`

## Recommended Policy

Do not expand unattended hard enforcement from advisory actions until the evaluation set passes the configured thresholds. Mandatory boundary checks and write constraints can still protect the agent while the advice layer is being calibrated.

Generated evaluation now covers every generated or profile-backed capability that the bundle can identify. For mature repositories, promote real route regressions into curated cases so `generated_only` does not become a false signal of architecture maturity.

## Regression Capture

Route reports include `evaluation_regression_hints` when a route needs review or captures an important correction opportunity. Add a curated case when:

- a human overrides `review`
- the predicted action was wrong
- the predicted capability was wrong
- a missing owner, public entry, or path mapping caused ambiguity
- a delete, merge, deprecate, or migration decision was confirmed

Curated cases should include `id`, `request`, `expected_action`, `expected_capabilities`, `changed_paths`, and `risk_level`.
