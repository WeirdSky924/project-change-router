# Project Change Router Skill

English version. The default Chinese README is [README.md](./README.md).

`project-change-router` is a standalone Codex skill for large repositories. It helps an agent decide whether a change should reuse, extend, extract, introduce, or stop for review before editing code.

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

Clone or copy this directory to:

```text
%USERPROFILE%\.codex\skills\project-change-router
```

## Validation

Run:

```powershell
python <codex-home>\skills\.system\skill-creator\scripts\quick_validate.py <codex-home>\skills\project-change-router
```

Expected result:

```text
Skill is valid!
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

## Execution Modes

- Read-only mode: `resolve_entry.py`, `check_reuse.py`, `check_deps.py`, `check_public_api.py`, `check_index_freshness.py`, `run_evaluation.py`
- Write mode: `bootstrap_router.py`, `rebuild_index.py`

Default to read-only mode. Only use write mode when the user explicitly wants repository-local routing data to be created or refreshed.

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

## Verification Performed

This skill was validated with:

- Codex skill structure validation
- skill-local unit tests
- bootstrap and bundle validation across Java, Python, TypeScript, and mixed-monorepo fixtures
- profile override tests for capability and owner remapping

## Chinese Version

See [README.md](./README.md).
