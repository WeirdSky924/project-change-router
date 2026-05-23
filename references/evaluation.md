# Evaluation

The repository-local bundle includes `references/evaluation-set.yaml`.

## Purpose

The evaluation set prevents routing logic from drifting silently. It provides:

- expected route actions
- expected primary capabilities
- expected module reads
- review cases for ambiguous or high-risk changes

## Minimum Expectations

- at least 30 cases for the first real rollout
- action accuracy threshold of 0.85
- review precision threshold of 0.90 on high-risk cases
- new routing failures should become new cases

## Evaluation Categories

- `reuse`
- `extend`
- `extract`
- `new`
- `review`

## Recommended Policy

Do not expand hard enforcement until the evaluation set passes the configured thresholds.
