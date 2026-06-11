# Project Change Router Skill

English version. The default Chinese README is [README.md](./README.md).

`project-change-router` is an AI coding skill for large repositories, usable from both Codex and Claude Code. Its goal is not to make agents guess architecture more aggressively. Its goal is to make agents guess less: before editing code, the agent should use a repository-local router bundle to get capability ownership, canonical-root signals, owners, read/write boundaries, reuse risks, and action guidance.

It addresses common structural drift in large projects:

- Agents have limited context and should not spend every task rereading an entire large full-stack repository.
- Agents can lose attention and overfit to local files or similar names.
- Reusable capabilities can be implemented twice, creating parallel implementation centers.
- Code that belongs in a shared lower-level capability can drift into a facade, API route, UI layer, or temporary folder.
- Empty, early, and rebuild repositories have unstable boundaries, so automatic inference can easily freeze temporary structure as architecture fact.

This skill provides a low-token, verifiable, calibratable project direction index and boundary guardrail. It does not replace detailed engineering analysis, and it does not make final architecture decisions for the user. It gives the agent direction, evidence, mandatory constraints, risk reasons, and calibration guidance before implementation starts.

![Project Change Router overview](./assets/readme-hero.svg)

## Core Philosophy

Design principles:

- Guess less before trying to guess better. If evidence is weak, prefer `review` over a fake conclusion.
- Prefer profile data over pure heuristics. Real owners, public entries, capability boundaries, and path patterns should be added to `.project-change-router.yaml` over time.
- Prefer structural evidence over name similarity. Paths, owners, public APIs, dependencies, and test bindings are more reliable than semantic similarity.
- Be conservative for early repositories. `seed` and `emerging` repositories should not automatically `extend` or `extract` too easily.
- `review` is not a failure. It is a safety mechanism: automatic writes are unsafe, but read-only analysis and human confirmation can continue.
- Route output is an integrated contract. Mandatory guardrail fields must be followed; `action` and unblock suggestions guide the agent but do not replace source-code analysis.
- Results must get better over time. Human overrides, misroutes, profile fixes, and real cases should be written back into feedback and evaluation data.

## Two-Layer Usage Model

PCR output has two layers. Do not interpret them as the same thing.

Mandatory guardrail layer:

- Respect `allowed_write_paths`, `forbidden_write_paths`, and `must_read_before_edit`.
- Identify and protect existing owners, public entries, canonical roots, and dependency direction.
- Do not create a second parallel implementation center when an existing capability may already exist.
- When `veto_reasons`, lifecycle review, low routing confidence, provisional boundaries, or high-risk overlaps appear, stop for confirmation, read-only analysis, or profile repair before writing product code.

Advisory direction layer:

- `action` is the router's current processing tendency, not a final engineering command.
- `recommended_next_steps`, `safe_next_steps`, `analysis_directions`, `why_not_actions`, and `profile_repair_hints` are unblock directions and investigation prompts.
- `action=review` does not mean the task is impossible. It means the current evidence is insufficient for automatic product-code writes, so the agent should gather evidence, repair profile data, read source code, request a scoped override, or pass through a higher gate.
- The final implementation plan must still come from real source analysis, dependency tracing, tests, and user confirmation.

## Scope

This skill can:

- Bootstrap a repository-local `project-change-router/` bundle.
- Discover modules, capabilities, owners, public entries, path ownership, and dependency direction.
- Produce a route report from a request and changed path hints, including mandatory guardrails and advisory actions.
- Run guardrails for duplicate implementation, wrong boundaries, public API bypasses, and dependency direction.
- Generate `path-to-capability-map.yaml` to expose direct path ownership, shared ownership, and uncovered modules.
- Validate bundles and reports with schemas.
- Run evaluation cases to detect route quality regressions.
- Run governance audits for profile/catalog sync, ownership granularity, contract quality, forbidden density, evaluation coverage, and capability lifecycle metadata.
- Append marked hint blocks during Codex / Claude Code installation so agents are more likely to invoke the skill before feature-level create / modify / delete work.

It should not:

- Replace detailed code reading, dependency tracing, test design, or architecture analysis.
- Treat `action` as a final command that can be executed without analysis.
- Continue writing product code automatically after `review` without evidence gathering, user confirmation, or a scoped override.
- Treat a generated-only bundle as mature architecture fact.
- Reuse or extend a capability only because its name looks similar.
- Create a second implementation center before confirming the canonical root.

## Route Actions

`resolve_entry.py` emits five route actions. These actions are processing guidance and investigation direction, not final architecture commands:

- `reuse`: use an existing capability without modifying its core implementation.
- `extend`: add behavior through an existing shared capability or compatible extension point.
- `extract`: move repeated logic into a shared capability before callers reuse it.
- `new`: create a new isolated capability boundary because no safe reuse target exists.
- `review`: gather evidence, repair profile data, request confirmation, or use a scoped override before writing because evidence is weak, risk is high, or multiple capabilities are involved.

`review` needs special interpretation. It does not mean the system is useless, and it is not a permanent block. It means the system is confident that automatic writing is unsafe. In an empty or early repository, a valid route can look like:

```json
{
  "action": "review",
  "routing_confidence": 0.0,
  "routing_confidence_level": "low",
  "decision_confidence": 0.95,
  "decision_confidence_level": "high"
}
```

This means the router has no confidence about which capability should receive the change, but high confidence that the agent should pause for evidence or confirmation before writing. The agent can still perform read-only analysis, propose profile repairs, trace callers, and ask for confirmation.

## Repository Stage Policy

The router infers `repo_stage`:

- `seed`: empty or very early repository; default to obvious new boundaries or `review`.
- `emerging`: some structure exists, but capability boundaries are still conservative; provisional boundaries should not become strong reuse targets automatically.
- `structured`: module boundaries are more stable; `reuse`, `extend`, and `extract` are more fully enabled.
- `governed`: routing is primarily driven by profile data, owners, public entries, evaluation, and guardrails.

Capabilities also have stages:

- `provisional`
- `candidate`
- `stable`
- `governed-capability`
- `deprecated`

Do not freeze generated capabilities too early. For early repositories, start with minimal ownership/profile data, then add capabilities, public entries, contracts, test bindings, and evaluation cases as real development confirms the boundaries.

## Integrated Route Report

A route report is not just an action. It is a complete route contract. Core fields include:

- `action`
- `decision_basis`
- `routing_confidence`
- `routing_confidence_level`
- `decision_confidence`
- `decision_confidence_level`
- `primary_capability`
- `primary_capability_stage`
- `secondary_capabilities`
- `candidate_capabilities`
- `required_reads`
- `required_checks`
- `recommended_next_action`
- `recommended_next_steps`
- `why_not_actions`
- `confidence_reasons`
- `veto_reasons`
- `positive_signals`
- `negative_signals`
- `risk_signals`

The seven governance output groups are first-class fields in the same route report, not an external add-on:

- post-`review` handling: `block_reason`, `missing_evidence`, `analysis_directions`, `safe_next_steps`, `suggested_questions`, `override_requirements`
- write constraints: `allowed_write_paths`, `forbidden_write_paths`, `must_read_before_edit`
- profile repair direction: `profile_repair_hints`, plus `repair_suggestions` in governance audit reports
- post-change closeout: `post_change_closeout`
- delete, merge, and deprecation governance: `capability_lifecycle_action`
- cross-stack composite routing: `composite_route`
- real regression capture: `evaluation_regression_hints`

See [references/governance-outputs.md](./references/governance-outputs.md) for the detailed contract.

![Integrated route contract](./assets/readme-route-contract.svg)

## Installation

Python requirement:

- Python `>= 3.10`

Install dependencies:

```powershell
pip install -r requirements.txt
```

Or install in development mode:

```powershell
pip install -e .[dev]
```

Install for Codex and Claude Code:

```powershell
python scripts/install_skill.py --target both --inject-hints
```

Install paths:

- Codex: `%USERPROFILE%\.codex\skills\project-change-router`
- Claude Code: `%USERPROFILE%\.claude\skills\project-change-router`

`--inject-hints` appends marked blocks instead of rewriting whole files:

- Codex: appends to `~/.codex/AGENTS.md`
- Claude Code: appends to `~/.claude/CLAUDE.md`

This is soft enforcement that reminds the agent to invoke the skill before feature-level create / modify / delete work. It is not a background daemon and it does not bypass the conversation trigger model.

## Installation Validation

Validate skill structure:

```powershell
python <codex-home>\skills\.system\skill-creator\scripts\quick_validate.py <codex-home>\skills\project-change-router
```

Expected output:

```text
Skill is valid!
```

Full smoke test in this repository:

```powershell
python -m pytest tests/test_router_core.py -q
python scripts/bootstrap_router.py --repo . --format json
python scripts/validate_router_bundle.py --repo . --format json
python scripts/check_bundle_governance.py --repo . --format json
python scripts/check_index_freshness.py --repo . --format json
python scripts/run_evaluation.py --repo . --format json
```

## Onboard a Target Repository

First onboarding for a target repository:

```powershell
python <skill-root>\scripts\bootstrap_router.py --repo <repo-root> --format json
```

This creates:

```text
<repo-root>/project-change-router/
```

The bundle contains:

- `router-config.yaml`
- `references/capability-catalog.yaml`
- `references/module-map.yaml`
- `references/ownership.yaml`
- `references/path-to-capability-map.yaml`
- `references/change-rules.yaml`
- `references/exception-registry.yaml`
- `references/evaluation-set.yaml`
- `schemas/`
- `reports/`

Bootstrap automatically adds this entry to the target repository `.gitignore`:

```text
project-change-router/
```

The target repository root can include a profile override file:

```text
.project-change-router.yaml
.project-change-router.yml
project-change-router.profile.yaml
project-change-router.profile.yml
```

Profiles can declare:

- capability-to-path mappings
- ownership rules
- module overrides
- public entries
- contracts
- forbidden patterns
- lifecycle metadata
- evaluation cases
- risk rules

Minimal profile templates are in [examples/profiles/README.md](./examples/profiles/README.md).

## Daily Use

Explicit invocation in Codex:

```text
Use $project-change-router to resolve the correct capability entry for this change.
```

Explicit invocation in Claude Code:

```text
/project-change-router resolve the correct capability entry for this change
```

Resolve one change from the command line:

```powershell
python scripts/resolve_entry.py --repo <repo-root> --request "Add invoice refund support" --changed-path services/billing/refund.py --format json
```

Or read the request from a file:

```powershell
python scripts/resolve_entry.py --repo <repo-root> --request-file request.md --changed-path services/billing/refund.py --format json --output route-report.json
```

Execution rules after resolution:

- If `action=review`: do not automatically write product code; run `safe_next_steps`, gather evidence, perform read-only analysis, and ask for a scoped override if needed.
- If `action=reuse`: treat it as a reuse tendency; read `must_read_before_edit` and `required_reads` first, and do not modify the core implementation.
- If `action=extend`: treat it as an extension tendency; write only inside `allowed_write_paths` and avoid bypassing public entries.
- If `action=extract`: treat it as an extraction tendency; confirm repeated surfaces, callers, and tests before extracting a shared capability.
- If `action=new`: treat it as a new-boundary tendency; name an isolated boundary first and do not create a second parallel center next to an existing capability.

## Codex / Claude Code Prompt

Recommended text for unattended plans or long-running tasks:

```text
Before any feature-level create, modify, delete, merge, deprecate, or migration work, invoke project-change-router for the target repository. Use it as a direction index and guardrail system, not as an automatic architecture decision engine.

Treat mandatory guardrails as binding: must_read_before_edit, allowed_write_paths, forbidden_write_paths, veto_reasons, canonical root, owner, public entry, lifecycle review, and duplicate-implementation warnings must be respected before product-code writes.

Treat action, recommended_next_steps, safe_next_steps, analysis_directions, profile_repair_hints, and why_not_actions as structured guidance for source-code analysis and user-confirmed decisions, not final architecture commands.

If action=review, do not implement product code automatically. Continue only with safe_next_steps, read-only analysis, profile repair proposals, or a scoped user override for the current task, phase, or changed paths. Do not reuse an override from an earlier phase.

Do not create a second implementation center when an existing capability or canonical root may exist. If routing evidence is weak, repair the profile or ask for confirmation instead of guessing.

After routed changes, run the required closeout checks and record feedback/evaluation cases when a review, override, lifecycle change, or routing correction occurred.
```

A fuller copyable version is available in [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md).

If the target repository already has a `project-change-router/` bundle generated by an older skill version, use [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md) after upgrading the skill. It tells the agent to refresh only governance metadata and generated hint blocks while preserving human-authored profiles, feedback, evaluation cases, and lifecycle data.

## Lifecycle Command Table

| Scenario | Command |
| --- | --- |
| First repository onboarding | `python scripts/bootstrap_router.py --repo <repo-root> --format json` |
| Major repository structure change | `python scripts/rebuild_index.py --repo <repo-root> --format json` |
| Resolve route before editing | `python scripts/resolve_entry.py --repo <repo-root> --request "<request>" --changed-path <path> --format json` |
| Pre-commit bundle validation | `python scripts/validate_router_bundle.py --repo <repo-root> --format json` |
| Check duplicate implementation | `python scripts/check_reuse.py --repo <repo-root> --format json` |
| Check dependency direction | `python scripts/check_deps.py --repo <repo-root> --format json` |
| Check public API boundaries | `python scripts/check_public_api.py --repo <repo-root> --format json` |
| Check index freshness | `python scripts/check_index_freshness.py --repo <repo-root> --format json` |
| Routing governance health check | `python scripts/check_bundle_governance.py --repo <repo-root> --format json` |
| Route quality regression evaluation | `python scripts/run_evaluation.py --repo <repo-root> --format json` |
| Manual feedback write-back | `python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json` |

## Governance Audit

`check_bundle_governance.py` checks whether the bundle is merely runnable or healthy enough for long-term routing governance.

It checks:

- profile-declared capabilities are present in the catalog.
- change rules do not reference unknown capabilities.
- generated-only capabilities are not excessive.
- the path-to-capability map has no uncovered modules or multi-capability conflicts.
- ownership rules are not too broad or too file-grained.
- contracts are not missing, too short, or too long.
- forbidden pattern density is sufficient for large capabilities.
- dependency priority covers all capabilities.
- the evaluation set covers profile-backed capabilities.
- deprecated capabilities include `superseded_by`, `deprecation_date`, and `migration_note`.

Default exit behavior:

- P0: fail.
- P1: warn by default, fail under `--strict`.
- P2: maintenance recommendation, not blocking.

## Manual Feedback and Continuous Calibration

![Continuous router calibration loop](./assets/readme-feedback-loop.svg)

When a human confirmation, override, misroute, capability merge, deprecation, or profile correction happens, record feedback:

```powershell
python scripts/sync_feedback.py --repo <repo-root> --feedback-file feedback.json --format json
```

Example:

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

Promote real misroutes into evaluation cases. Do not fix a rule without adding a regression sample.

Copyable samples:

- [examples/feedback/manual-route-correction.json](./examples/feedback/manual-route-correction.json)
- [examples/evaluation/route-regression-cases.yaml](./examples/evaluation/route-regression-cases.yaml)

## Real-Repository Calibration Reference

An anonymized real-structure calibration reference is available:

- [examples/calibration/README.md](./examples/calibration/README.md)
- [examples/calibration/anonymized-structure.md](./examples/calibration/anonymized-structure.md)
- [examples/calibration/anonymized-profile.yaml](./examples/calibration/anonymized-profile.yaml)
- [examples/calibration/anonymized-module-map.yaml](./examples/calibration/anonymized-module-map.yaml)
- [examples/calibration/anonymized-route-cases.yaml](./examples/calibration/anonymized-route-cases.yaml)
- [examples/calibration/anonymized-feedback.json](./examples/calibration/anonymized-feedback.json)

These samples show how a large full-stack project can turn real modules, owners, public entries, route cases, and feedback into reusable governance data.

## Example Files

Agent workflow examples:

- [examples/agent-workflows/README.md](./examples/agent-workflows/README.md)
- [examples/agent-workflows/unattended-plan-prompt.md](./examples/agent-workflows/unattended-plan-prompt.md)
- [examples/agent-workflows/update-existing-router-bundle-prompt.md](./examples/agent-workflows/update-existing-router-bundle-prompt.md)

Profile templates:

- [examples/profiles/early-repo.project-change-router.yaml](./examples/profiles/early-repo.project-change-router.yaml)
- [examples/profiles/python-monorepo.project-change-router.yaml](./examples/profiles/python-monorepo.project-change-router.yaml)
- [examples/profiles/ts-workspace.project-change-router.yaml](./examples/profiles/ts-workspace.project-change-router.yaml)
- [examples/profiles/mixed-repo.project-change-router.yaml](./examples/profiles/mixed-repo.project-change-router.yaml)
- [examples/profiles/skill-repo.project-change-router.yaml](./examples/profiles/skill-repo.project-change-router.yaml)

Feedback and evaluation samples:

- [examples/feedback/manual-route-correction.json](./examples/feedback/manual-route-correction.json)
- [examples/evaluation/route-regression-cases.yaml](./examples/evaluation/route-regression-cases.yaml)

Bundle samples:

- [examples/bundle/router-config.yaml](./examples/bundle/router-config.yaml)
- [examples/bundle/references/capability-catalog.yaml](./examples/bundle/references/capability-catalog.yaml)
- [examples/bundle/references/module-map.yaml](./examples/bundle/references/module-map.yaml)
- [examples/bundle/references/ownership.yaml](./examples/bundle/references/ownership.yaml)
- [examples/bundle/references/path-to-capability-map.yaml](./examples/bundle/references/path-to-capability-map.yaml)
- [examples/bundle/references/change-rules.yaml](./examples/bundle/references/change-rules.yaml)
- [examples/bundle/references/exception-registry.yaml](./examples/bundle/references/exception-registry.yaml)
- [examples/bundle/references/evaluation-set.yaml](./examples/bundle/references/evaluation-set.yaml)

Output samples:

- [examples/outputs/resolve-entry.pass.json](./examples/outputs/resolve-entry.pass.json)
- [examples/outputs/resolve-entry.review-guidance.json](./examples/outputs/resolve-entry.review-guidance.json)
- [examples/outputs/resolve-entry.composite-review.json](./examples/outputs/resolve-entry.composite-review.json)
- [examples/outputs/resolve-entry.seed-new-capability.json](./examples/outputs/resolve-entry.seed-new-capability.json)
- [examples/outputs/check-deps.pass.json](./examples/outputs/check-deps.pass.json)
- [examples/outputs/check-public-api.pass.json](./examples/outputs/check-public-api.pass.json)
- [examples/outputs/check-reuse.pass.json](./examples/outputs/check-reuse.pass.json)
- [examples/outputs/check-bundle-governance.warn.json](./examples/outputs/check-bundle-governance.warn.json)
- [examples/outputs/run-evaluation.pass.json](./examples/outputs/run-evaluation.pass.json)

Reference documents:

- [references/router-workflow.md](./references/router-workflow.md)
- [references/governance-outputs.md](./references/governance-outputs.md)
- [references/bootstrap.md](./references/bootstrap.md)
- [references/repo-discovery.md](./references/repo-discovery.md)
- [references/evaluation.md](./references/evaluation.md)
- [references/schema-overview.md](./references/schema-overview.md)

## Scripts

- `scripts/install_skill.py`
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

## CI

The GitHub Actions workflow is in [.github/workflows/ci.yml](./.github/workflows/ci.yml). It runs:

- dependency installation.
- skill structure validation.
- unit tests.
- bootstrap against this repository.
- bundle validation.
- governance audit.
- freshness check.
- route evaluation.

## Boundaries and Risks

Be explicit about these limits:

- First bootstrap is only a first pass.
- Without a profile, results intentionally skew conservative.
- Generated-only evaluation only proves system self-consistency, not architecture maturity.
- When `review_required=true` or `forbidden_write_paths=["**"]`, agents should not automatically write product code; they may perform read-only analysis, gather evidence, propose profile repairs, or request a scoped override.
- `decision_confidence=high` does not mean writing is allowed; it may mean the router is highly confident that the agent should stop.
- `action` is advisory direction, not a final engineering command; write boundaries, vetoes, owners, canonical roots, and lifecycle constraints have higher priority.
- Lifecycle operations such as delete, merge, deprecate, replace, and migrate must be review-first.
- This skill provides direction, evidence, and constraints. The final implementation plan still must come from real code analysis, tests, and user confirmation.

## License

See [LICENSE](./LICENSE).
