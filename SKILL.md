---
name: project-change-router
description: >-
  Project-level direction, boundary, and reuse governance for large repositories.
  Use when Codex, Claude Code, or DeepSeek Harness needs mandatory routing
  guardrails before code edits: identify capability candidates, canonical roots, owners,
  allowed/forbidden write paths, reuse risks, and advisory actions such as reuse,
  extend, extract, new, or review. Also use when the agent should bootstrap,
  rebuild, validate, or evaluate a repository-local router bundle for Java,
  Python, TypeScript, or mixed monorepos.
---

# Project Change Router

## Overview

Use this skill to turn a large repository into a governed change-routing system. It helps the agent locate likely capability entries, avoid duplicate implementations, enforce boundary checks, and create or validate a repository-local router bundle.

PCR is a direction index and guardrail system, not an automatic architecture decision engine. Its boundary, risk, and read/write constraints are mandatory for the agent to respect. Its `action`, `recommended_next_steps`, `analysis_directions`, and `why_not_actions` are structured guidance for the agent's own source-code analysis and user-confirmed engineering decision.

The authoritative write decision is `execution_gate`, reduced from schema-valid typed findings as `pass`, `conditional`, or `blocked`. `action` remains independent advisory direction and is never rewritten merely to imitate a gate state.

## Two-Layer Contract

Mandatory guardrail layer:

- Read `execution_gate` before interpreting `action`. It is the authoritative write decision.
- For `execution_gate.state=blocked`, do not write product code. Resolve the decisive typed findings or obtain a valid, task-bound authorization grant where policy allows one.
- For `execution_gate.state=conditional`, run every `required_command` and stay inside the returned write envelope. Conditional means only proven unrelated or non-expanding historical debt remains; it is not a general bypass.
- For `execution_gate.state=pass`, continue only inside the returned write envelope after reading the precise targets.
- Respect `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`.
- Do not bypass confirmed owners, public entries, canonical roots, or dependency direction.
- Do not create a second implementation center when a reusable capability may already exist.
- Never ignore `veto_reasons`, unknown evidence, lifecycle findings, low routing confidence, provisional boundaries, or high-risk overlaps. Trace them to the decisive typed findings and gate policy rules.

Advisory direction layer:

- Treat `action` as the router's current processing tendency, not a final engineering command.
- Use `recommended_next_steps`, `safe_next_steps`, `analysis_directions`, `profile_repair_hints`, and `why_not_actions` as unblock directions and investigation prompts.
- `action=review` is an investigation direction, not a write decision. It may coexist with `pass`, `conditional`, or `blocked`; follow `execution_gate` and use review guidance to gather evidence.
- Final implementation choices still require real code reading, dependency tracing, tests, and user-confirmed scope.

## Workflow

1. Detect whether the request is a feature addition, feature modification, refactor, migration, or bug fix.
2. Find the repository root and look for an existing `project-change-router/` bundle.
3. If the bundle is missing and the user explicitly wants durable routing metadata, bootstrap one from the current repository structure.
4. Prefer `scripts/run_change_flow.py` to resolve the route and run freshness, dependency, public API, structure, governance, and reuse checks as one compact flow. Use the legacy commands separately only for focused diagnostics or compatibility.
5. Read `execution_gate`, the fixed safety envelope, decisive typed findings, and ordered `required_commands` before interpreting advisory `action` guidance.
6. Read each resolved `must_read_target` and its symbol/content digest. Inventory directories without reading them wholesale; run each structured query for unresolved targets.
7. If the gate is `blocked`, stop product writes and resolve the reported unknown or blocking evidence. If it is `conditional`, execute all pre-change commands and preserve the bounded envelope. If it is `pass`, continue inside the envelope.
8. Apply the change only in the routed layer. `action` helps choose reuse, extension, extraction, or a new boundary but never grants write authority.
9. Preserve the global report and its route-relevant delta: `task_local_new`, `task_local_expanded`, and `unknown` remain blocking under their policy rules; only trusted `baseline_unchanged` debt proven outside the forward/reverse closure may yield `conditional`.
10. Run `check_structure.py` for central-file growth, file-size bands, forbidden implementation roots, exclusive canonical owners, and exact pinned generated-output verification when the profile declares those baselines. For a new pin, require the user-approved exact fingerprint through `--initialize-generated-output-baseline` on structure verification and the first write-enabled rebuild; never treat profile text as authorization. While a current or committed pin remains active, malformed, or only worktree-removed, use the verified rebuild path and never bootstrap over its seven protected refs.
11. For reuse, inspect the independent `intra_capability`, `cross_capability`, and `extended` channels. A bounded, incomplete, timed-out, cancelled, or errored channel cannot prove that duplicates are absent.
12. Promote a baseline only from a clean, complete candidate bound to the current commit/profile/bundle/structure/index/tool/policy identity, using an exact accepted fingerprint or trusted CI authority. Never promote a dirty or incomplete first scan.
13. If policy permits an override, create an authorization request and require an externally confirmed grant. Grants are task/path/owner/route/mutation-bound, expire, are single-use by default, and never revive after consumption.
14. If the change reveals stale indexes, ownership gaps, or missing capability coverage, run the governance audit before deciding whether to rebuild.
15. Rebuild the bundle only when routing references are stale or the user explicitly asks to refresh repository-local routing data.
16. After a routed change, follow `post_change_closeout` and record feedback or evaluation regressions when review, override, delete, merge, or capability correction happened.
17. For concrete route interpretation examples, read `examples/agent-workflows/README.md` before inventing behavior that is not described by the route report.

## Execution Modes

- Unified read-only flow: use `scripts/run_change_flow.py`; it runs route plus governed checks, persists the full content-addressed artifact, and returns compact safety output by default
- Focused read-only mode: use `scripts/resolve_entry.py`, `scripts/check_reuse.py`, `scripts/check_deps.py`, `scripts/check_public_api.py`, `scripts/check_structure.py`, `scripts/check_index_freshness.py`, `scripts/check_bundle_governance.py`, and `scripts/run_evaluation.py`
- Authorization mode: use `scripts/manage_authorization.py` to persist a request, record external confirmation as a bounded grant, consume it, or inspect its audit chain
- Write mode: use `scripts/bootstrap_router.py` or `scripts/rebuild_index.py` only when the user explicitly asks to create or refresh repository-local routing data

Do not silently create or rebuild `project-change-router/` during an unrelated code-edit request.

## Route Actions

- `reuse`: use an existing capability without changing its core
- `extend`: add behavior through a shared capability entry or compatible internal change
- `extract`: move repeated logic into a shared capability first
- `new`: introduce a new capability because no acceptable shared fit exists
- `review`: prioritize evidence gathering, profile repair, coordination, or user confirmation because the request is ambiguous, high-risk, or multi-capability

Route actions are advisory direction labels. They help the agent decide what to inspect next and what risks to manage, but they do not replace engineering judgment from the actual repository.

`review` is not an implementation decision, write denial, or permanent block. It is a request to investigate before choosing the engineering approach. Only `execution_gate` decides whether writes are currently `pass`, `conditional`, or `blocked`.

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

Canonical, legacy, and skill-profile locations are compatibility priority levels, not merge layers. Exactly one file may exist at the selected level; `.yaml` and `.yml` siblings at the same level are a fail-closed source conflict.

These overrides can define capability mappings, path-level ownership rules, explicit `capability_ownership` primary/reviewer records, repository-specific risk review phrases, and module overrides without patching the global skill code. Missing, duplicate, malformed, unknown, provisional, or same-person capability ownership remains review-only.

## References

- `references/router-workflow.md`
- `references/bootstrap.md`
- `references/repo-discovery.md`
- `references/schema-overview.md`
- `references/evaluation.md`
- `references/governance-outputs.md`
- `references/architecture-governance.md`
- `references/reuse-scan-runtime.md`
- `references/typed-findings-gate-todo.md`
- `examples/agent-workflows/README.md`

## Resources

- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_structure.py`
- `scripts/check_index_freshness.py`
- `scripts/check_bundle_governance.py`
- `scripts/run_evaluation.py`
- `scripts/run_change_flow.py`
- `scripts/manage_authorization.py`
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

- This skill is standalone and installable under `~/.codex/skills`, `~/.claude/skills`, or `~/.dsh/skills`.
- For Claude Code, install the same folder under `~/.claude/skills/project-change-router/` or `.claude/skills/project-change-router/`.
- For DeepSeek Harness, install the same folder under `~/.dsh/skills/project-change-router/`, `.dsh/skills/project-change-router/`, or use the repository's `dsh.bundle` plugin.
- Codex requests can invoke it as `$project-change-router`; Claude Code and DeepSeek Harness requests can invoke it as `/project-change-router`.
- DeepSeek Harness is currently a developer preview. Revalidate the filesystem and provider contracts when upgrading Harness across preview releases.
- It does not depend on a specific repository.
- The repository-local router bundle is generated on demand and is not the skill itself.
- Version 0.4 exposes architecture governance API v2, typed-finding/gate/change-flow/authorization API v1, and preserves reuse engine API v2.
- Every current report carries runtime identity: skill version, Git commit when available, installed payload digest/source, compatible bundle schemas, report/API/policy versions, parser versions, and an identity digest.
- Updating the installed skill does not bootstrap, rebuild, or overwrite an existing repository-local bundle. Bundle schema v1 remains readable; missing 0.4 precision becomes `unknown` and blocks when required instead of being fabricated or written back. Runtime fingerprints, baselines, authorization manifests, and managed artifacts live outside the repository by default.
