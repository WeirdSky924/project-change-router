---
name: project-change-router
description: Project-level change routing and reuse governance for large repositories. Use when Codex or Claude Code needs to decide whether a request should reuse, extend, extract, introduce, or review a capability before editing code, and when the agent should bootstrap, rebuild, validate, or evaluate a repository-local router bundle for Java, Python, TypeScript, or mixed monorepos.
---

# Project Change Router

## Overview

Use this skill to turn a large repository into a governed change-routing system. It helps the agent locate the correct capability entry, avoid duplicate implementations, enforce boundary checks, and create or validate a repository-local router bundle.

## Workflow

1. Detect whether the request is a feature addition, feature modification, refactor, migration, or bug fix.
2. Find the repository root and look for an existing `project-change-router/` bundle.
3. If the bundle is missing and the user explicitly wants durable routing metadata, bootstrap one from the current repository structure.
4. Resolve the route action with the repository-local catalog and module map.
5. Treat the route action, review guidance, write constraints, lifecycle metadata, composite route metadata, and closeout steps as one integrated route contract.
6. Read the required capability entries and public code entry points before editing.
7. Apply the change only in the routed layer.
8. Run the required guardrails and capability-bound tests.
9. If the route is `review`, stop automatic editing and report `block_reason`, `missing_evidence`, `analysis_directions`, `safe_next_steps`, and scoped `override_requirements`.
10. Apply writes only inside `allowed_write_paths`, never inside `forbidden_write_paths`, and read `must_read_before_edit` first.
11. If the change reveals stale indexes, ownership gaps, or missing capability coverage, run the governance audit before deciding whether to rebuild.
12. Rebuild the bundle only when routing references are stale or the user explicitly asks to refresh repository-local routing data.
13. After a routed change, follow `post_change_closeout` and record feedback or evaluation regressions when review, override, delete, merge, or capability correction happened.
14. For concrete route interpretation examples, read `examples/agent-workflows/README.md` before inventing behavior that is not described by the route report.

## Execution Modes

- Read-only mode: use `scripts/resolve_entry.py`, `scripts/check_reuse.py`, `scripts/check_deps.py`, `scripts/check_public_api.py`, `scripts/check_index_freshness.py`, `scripts/check_bundle_governance.py`, and `scripts/run_evaluation.py`
- Write mode: use `scripts/bootstrap_router.py` or `scripts/rebuild_index.py` only when the user explicitly asks to create or refresh repository-local routing data

Do not silently create or rebuild `project-change-router/` during an unrelated code-edit request.

## Route Actions

- `reuse`: use an existing capability without changing its core
- `extend`: add behavior through a shared capability entry or compatible internal change
- `extract`: move repeated logic into a shared capability first
- `new`: introduce a new capability because no acceptable shared fit exists
- `review`: stop automatic routing because the request is ambiguous, high-risk, or multi-capability

`review` is not an implementation decision. It is a request for more evidence. The skill should provide analysis directions and safe read-only next steps, while leaving the deeper engineering decision to the agent and user.

The governance outputs are not a separate add-on. They are first-class fields of the same route decision report and must be interpreted together with `action`, `primary_capability`, and confidence.

## Repository Bundle

The skill can create or validate a repository-local bundle named `project-change-router/` with:

- `router-config.yaml`
- `references/`
- `references/path-to-capability-map.yaml`
- `profiles/` overrides from the repository root when present
- `schemas/`
- `reports/`

Use the bundle when you need a durable, repo-specific routing index. Use the global skill when you need the routing process itself.

Repository-level overrides are loaded from:

- `.project-change-router.yaml`
- `.project-change-router.yml`
- `project-change-router.profile.yaml`
- `project-change-router.profile.yml`

These overrides can define capability mappings, ownership rules, risk rules, and module overrides without patching the global skill code.

## References

- `references/router-workflow.md`
- `references/bootstrap.md`
- `references/repo-discovery.md`
- `references/schema-overview.md`
- `references/evaluation.md`
- `references/governance-outputs.md`
- `examples/agent-workflows/README.md`

## Resources

- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_index_freshness.py`
- `scripts/check_bundle_governance.py`
- `scripts/run_evaluation.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

## Examples

- `examples/agent-workflows/README.md`: scenario-based agent workflow examples for route, review, seed, composite, lifecycle, profile repair, and closeout behavior
- `examples/agent-workflows/unattended-plan-prompt.md`: reusable prompt for long-running or unattended agent plans
- `examples/agent-workflows/update-existing-router-bundle-prompt.md`: reusable prompt for refreshing an existing repository-local bundle after a skill upgrade
- `examples/outputs/`: complete route and guardrail output samples
- `examples/profiles/`: copyable profile templates for early repos, monorepos, mixed stacks, and this skill repository shape

### assets

- `assets/router-icon.svg`

## Notes

- This skill is standalone and installable under `~/.codex/skills`.
- For Claude Code, install the same folder under `~/.claude/skills/project-change-router/` or `.claude/skills/project-change-router/`.
- Codex requests can invoke it as `$project-change-router`; Claude Code requests should invoke it as `/project-change-router`.
- It does not depend on a specific repository.
- The repository-local router bundle is generated on demand and is not the skill itself.
