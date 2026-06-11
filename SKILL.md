---
name: project-change-router
description: >-
  Project-level direction, boundary, and reuse governance for large repositories.
  Use when Codex or Claude Code needs mandatory routing guardrails before code
  edits: identify capability candidates, canonical roots, owners,
  allowed/forbidden write paths, reuse risks, and advisory actions such as reuse,
  extend, extract, new, or review. Also use when the agent should bootstrap,
  rebuild, validate, or evaluate a repository-local router bundle for Java,
  Python, TypeScript, or mixed monorepos.
---

# Project Change Router

## Overview

Use this skill to turn a large repository into a governed change-routing system. It helps the agent locate likely capability entries, avoid duplicate implementations, enforce boundary checks, and create or validate a repository-local router bundle.

PCR is a direction index and guardrail system, not an automatic architecture decision engine. Its boundary, risk, and read/write constraints are mandatory for the agent to respect. Its `action`, `recommended_next_steps`, `analysis_directions`, and `why_not_actions` are structured guidance for the agent's own source-code analysis and user-confirmed engineering decision.

## Two-Layer Contract

Mandatory guardrail layer:

- Respect `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`.
- Do not bypass confirmed owners, public entries, canonical roots, or dependency direction.
- Do not create a second implementation center when a reusable capability may already exist.
- Treat `veto_reasons`, lifecycle review, low routing confidence, provisional boundaries, and high-risk overlaps as stop-or-confirm signals before product writes.

Advisory direction layer:

- Treat `action` as the router's current processing tendency, not a final engineering command.
- Use `recommended_next_steps`, `safe_next_steps`, `analysis_directions`, `profile_repair_hints`, and `why_not_actions` as unblock directions and investigation prompts.
- When `action=review`, do not treat it as permanent refusal. It means evidence is insufficient for automatic writes; continue with read-only analysis, profile repair, or scoped user confirmation.
- Final implementation choices still require real code reading, dependency tracing, tests, and user-confirmed scope.

## Workflow

1. Detect whether the request is a feature addition, feature modification, refactor, migration, or bug fix.
2. Find the repository root and look for an existing `project-change-router/` bundle.
3. If the bundle is missing and the user explicitly wants durable routing metadata, bootstrap one from the current repository structure.
4. Resolve the route report with the repository-local catalog and module map.
5. Treat guardrail fields as mandatory constraints and action/review guidance as structured advice.
6. Read the required capability entries and public code entry points before editing.
7. Apply the change only in the routed layer.
8. Run the required guardrails and capability-bound tests.
9. If the route is `review`, stop automatic product-code editing and report `block_reason`, `missing_evidence`, `analysis_directions`, `safe_next_steps`, and scoped `override_requirements`.
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

Route actions are advisory direction labels. They help the agent decide what to inspect next and what risks to manage, but they do not replace engineering judgment from the actual repository.

`review` is not an implementation decision and not a permanent block. It is a request for more evidence before automatic writes. The skill should provide analysis directions and safe read-only next steps, while leaving the deeper engineering decision to the agent and user.

The governance outputs are not a separate add-on. They are first-class fields of the same route report and must be interpreted together with `action`, `primary_capability`, and confidence. Mandatory guardrails take precedence over advisory actions.

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
