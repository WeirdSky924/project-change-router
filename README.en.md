# Project Change Router Skill

English version. The default Chinese README is [README.md](./README.md).

`project-change-router` is a standalone AI coding skill for large repositories, usable from both Codex and Claude Code. It helps an agent decide whether a change should reuse, extend, extract, introduce, or stop for review before editing code.

This skill is global and installable under `~/.codex/skills/project-change-router`.  
It can also bootstrap a repository-local `project-change-router/` bundle containing:

- router configuration
- capability catalog
- module map
- ownership map
- routing rules
- exception registry
- evaluation set
- validation schemas
- optional repository profile overrides

## What It Does

- route code changes to the correct capability entry
- reduce duplicate implementations
- enforce dependency and public API boundaries
- generate repository-local routing bundles
- load repository-level `.project-change-router.yaml` overrides for capability and ownership rules
- validate routing bundles with JSON Schema
- run evaluation cases against routing logic
- generate feedback proposals from routing and guardrail reports

## Skill Layout

```text
project-change-router/
  SKILL.md
  README.md
  README.en.md
  agents/openai.yaml
  assets/
  references/
  schemas/
  scripts/
  tests/
```

## Installation

Codex install path:

```text
%USERPROFILE%\.codex\skills\project-change-router
```

Claude Code install path:

```text
%USERPROFILE%\.claude\skills\project-change-router
```

Python requirement:

- Python `>= 3.10`

Install dependencies:

```powershell
pip install -r requirements.txt
```

Or:

```powershell
pip install -e .[dev]
```

Install script:

```powershell
python scripts/install_skill.py --target both --inject-hints
```

This script will:

- install the skill into Codex at `~/.codex/skills/project-change-router`
- install the skill into Claude Code at `~/.claude/skills/project-change-router`
- append a guidance block to Codex `~/.codex/AGENTS.md` so Codex conversations are more likely to explicitly invoke this skill when relevant
- append a guidance block to Claude Code `~/.claude/CLAUDE.md` so Claude Code conversations are more likely to explicitly invoke this skill when relevant

## Validation

Run:

```powershell
python <codex-home>\skills\.system\skill-creator\scripts\quick_validate.py <codex-home>\skills\project-change-router
```

Expected result:

```text
Skill is valid!
```

Local smoke test:

```powershell
python -m pytest tests/test_router_core.py -q
python scripts/bootstrap_router.py --repo <repo-root> --format json
python scripts/validate_router_bundle.py --repo <repo-root> --format json
python scripts/run_evaluation.py --repo <repo-root> --format json
```

## How To Use

Invoke the skill explicitly in a Codex request:

- `Use $project-change-router to bootstrap a router bundle for this repository.`
- `Use $project-change-router to resolve the correct capability entry for this change.`
- `Use $project-change-router to validate the repository-local router bundle.`

In Claude Code, invoke it explicitly as:

- `/project-change-router bootstrap a router bundle for this repository`
- `/project-change-router resolve the correct capability entry for this change`
- `/project-change-router validate the repository-local router bundle`

Trigger behavior:

- the current default model is still explicit invocation first
- that means the conversation should directly include:
  - Codex: `$project-change-router`
  - Claude Code: `/project-change-router`
- if you use `install_skill.py --inject-hints`, the installer appends hint blocks to:
  - Codex `AGENTS.md`
  - Claude Code `CLAUDE.md`
- this acts as a soft enforcement reminder rather than a hidden auto-trigger

Post-install recognition check:

- In Codex: `Use $project-change-router to resolve the correct capability entry for this change.`
- In Claude Code: `/project-change-router resolve the correct capability entry for this change`

Expected behavior:

- the agent first checks the repository root and any existing `project-change-router/` bundle
- if the bundle already exists, it reads it directly
- if the bundle does not exist, it should only create one when you explicitly ask for bootstrap

## Execution Modes

- Read-only mode: `resolve_entry.py`, `check_reuse.py`, `check_deps.py`, `check_public_api.py`, `check_index_freshness.py`, `run_evaluation.py`
- Write mode: `bootstrap_router.py`, `rebuild_index.py`

Default to read-only mode. Only use write mode when the user explicitly wants repository-local routing data to be created or refreshed.

## Repository Stage Policy

This skill now infers a `repo_stage` and uses it to limit routing strength.

Stages:

- `seed`
- `emerging`
- `structured`
- `governed`

Behavior:

- `seed`: default to `new` / `review`
- `emerging`: limited `reuse`, stricter `extend` / `extract`
- `structured`: full `reuse` / `extend` / `extract`
- `governed`: profile- and guardrail-driven routing

Each capability also carries its own `stage`:

- `provisional`
- `candidate`
- `stable`
- `governed-capability`

Do not treat generated capabilities, owners, or public entries as final architecture facts in an early repository.

Route outputs now also include:

- `confidence_level`
- `confidence_reasons`
- `veto_reasons`
- `positive_signals`
- `negative_signals`
- `risk_signals`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`

Interpretation:

- `high`: strong profile, boundary, and structure evidence
- `medium`: partial structure evidence, still needs care
- `low`: insufficient evidence, usually should be treated as `review`

Usage:

- start with `recommended_next_action`
- then follow `recommended_next_steps`
- use `why_not_actions` to understand why stronger actions were rejected

## Lifecycle

Recommended decision table:

- first repository onboarding: `python scripts/bootstrap_router.py --repo <repo-root>`
- major repository structure change: `python scripts/rebuild_index.py --repo <repo-root>`
- pre-merge validation: `python scripts/validate_router_bundle.py --repo <repo-root>`
- routine guardrail checks: `python scripts/check_reuse.py --repo <repo-root>`, `python scripts/check_deps.py --repo <repo-root>`, `python scripts/check_public_api.py --repo <repo-root>`
- routing quality review: `python scripts/run_evaluation.py --repo <repo-root>`
- rule improvement suggestions: `python scripts/sync_feedback.py --repo <repo-root>`

Manual feedback write-back:

```powershell
python scripts/sync_feedback.py --repo <repo-root> --feedback-file <feedback.json> --format json
```

Example `feedback.json`:

```json
{
  "decision_id": "route-...",
  "final_action": "review",
  "final_capability": "billing",
  "confirmed_public_entry": "services/billing/__init__.py",
  "confirmed_owner": "billing-team",
  "profile_update_recommended": true,
  "notes": "Human-confirmed correction"
}
```

## Repository-Local Bundle

The skill itself is global.  
The generated bundle is local to a target repository.

Bootstrap example:

```powershell
python <codex-home>\skills\project-change-router\scripts\bootstrap_router.py --repo <repo-root> --format json
```

This creates:

```text
<repo>/project-change-router/
```

with repository-local references, schemas, and reports.

The bootstrap step will also automatically append this entry to the target repository `.gitignore`:

```text
project-change-router/
```

Optionally, the target repository root can include one of:

```text
.project-change-router.yaml
.project-change-router.yml
project-change-router.profile.yaml
project-change-router.profile.yml
```

These files can define:

- capability-to-path mappings
- ownership rules
- risk rules
- module overrides

Ready-to-copy templates:

- [examples/profiles/README.md](./examples/profiles/README.md)
- [examples/profiles/early-repo.project-change-router.yaml](./examples/profiles/early-repo.project-change-router.yaml)
- [examples/profiles/python-monorepo.project-change-router.yaml](./examples/profiles/python-monorepo.project-change-router.yaml)
- [examples/profiles/ts-workspace.project-change-router.yaml](./examples/profiles/ts-workspace.project-change-router.yaml)
- [examples/profiles/mixed-repo.project-change-router.yaml](./examples/profiles/mixed-repo.project-change-router.yaml)

An anonymized real-structure calibration reference is also available:

- [examples/calibration/README.md](./examples/calibration/README.md)
- [examples/calibration/anonymized-structure.md](./examples/calibration/anonymized-structure.md)
- [examples/calibration/anonymized-profile.yaml](./examples/calibration/anonymized-profile.yaml)
- [examples/calibration/anonymized-module-map.yaml](./examples/calibration/anonymized-module-map.yaml)
- [examples/calibration/anonymized-route-cases.yaml](./examples/calibration/anonymized-route-cases.yaml)
- [examples/calibration/anonymized-feedback.json](./examples/calibration/anonymized-feedback.json)

## Bundle Sample

Minimal bundle samples:

- [examples/bundle/router-config.yaml](./examples/bundle/router-config.yaml)
- [examples/bundle/references/capability-catalog.yaml](./examples/bundle/references/capability-catalog.yaml)
- [examples/bundle/references/module-map.yaml](./examples/bundle/references/module-map.yaml)
- [examples/bundle/references/ownership.yaml](./examples/bundle/references/ownership.yaml)
- [examples/bundle/references/change-rules.yaml](./examples/bundle/references/change-rules.yaml)
- [examples/bundle/references/exception-registry.yaml](./examples/bundle/references/exception-registry.yaml)
- [examples/bundle/references/evaluation-set.yaml](./examples/bundle/references/evaluation-set.yaml)

## Output Samples

Real sample outputs:

- route report: [examples/outputs/resolve-entry.pass.json](./examples/outputs/resolve-entry.pass.json)
- `check_deps.py`: [examples/outputs/check-deps.pass.json](./examples/outputs/check-deps.pass.json)
- `check_public_api.py`: [examples/outputs/check-public-api.pass.json](./examples/outputs/check-public-api.pass.json)
- `check_reuse.py`: [examples/outputs/check-reuse.pass.json](./examples/outputs/check-reuse.pass.json)
- `run_evaluation.py`: [examples/outputs/run-evaluation.pass.json](./examples/outputs/run-evaluation.pass.json)

Typical success signals:

- `status: pass`
- or a route report `action` of `reuse`, `extend`, `new`, or `review`

Typical failure signals:

- `status: fail`
- guardrail report `blocking: true`
- route report `review_required: true`
- validation report with non-empty `errors`

Important fields:

- `confidence_level`
- `confidence_reasons`
- `veto_reasons`
- `primary_capability_stage`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`

## Main Scripts

- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_index_freshness.py`
- `scripts/run_evaluation.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

## Design Notes

- the skill is independent from any single project
- the repository-local bundle is generated on demand
- repository-specific behavior belongs in profile overrides, not hardcoded Python logic
- high-risk shared capabilities intentionally route conservatively
- generated bundles should still be curated by repository owners

## Limits and Misclassification Boundaries

This skill is a heuristic and profile-driven router, not a perfect architecture facts database.

Be explicit about these limits:

- the first bootstrap is only a first pass
- capability ownership and public API surfaces still need human calibration
- `route=review` is a safety mechanism, not a failure state
- without a profile, the router intentionally behaves more conservatively
- a passing evaluation does not eliminate the need for architecture review
- early repositories are deliberately downgraded to more conservative `repo_stage`s
- `provisional` capabilities should not be treated as long-term architecture boundaries
- `generated_only` evaluation indicates self-consistency, not architectural maturity

## Verification Performed

This skill was validated with:

- skill structure validation
- skill-local unit tests
- bootstrap and bundle validation across Java, Python, TypeScript, and mixed-monorepo fixtures
- profile override tests for capability and owner remapping
- CI smoke validation for dependency install, tests, bootstrap, validate, and evaluation

## Chinese Version

See [README.md](./README.md).
