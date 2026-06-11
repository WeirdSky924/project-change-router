# Existing Router Bundle Upgrade Prompt

Use this prompt when a repository already used `project-change-router` and now needs its repository-local bundle, generated router references, and agent guidance refreshed after installing a newer version of the skill.

```text
You are updating an existing project-change-router repository-local bundle after a project-change-router skill upgrade.

Target repository:
- <repo-root>

Scope:
- This task is governance metadata and generated router documentation maintenance only.
- Do not implement, refactor, delete, or move product code.
- Do not rewrite human-authored project documentation except for clearly marked project-change-router hint blocks.
- Preserve all user calibration unless the user explicitly confirms a replacement.

First, confirm the latest skill source:
- Locate the updated project-change-router skill or checkout that provides the latest scripts.
- Prefer running scripts from the updated skill source against the target repository with `--repo <repo-root>`.
- Do not run stale scripts copied from an old repository-local bundle if a newer installed skill is available.
- If the installed skill and repository checkout disagree, report both paths and ask which source should be authoritative before mutating the bundle.

Inventory the existing target repository state:
- Check whether `<repo-root>/project-change-router/` exists.
- Check whether `.project-change-router.yaml`, `.project-change-router.yml`, `project-change-router.profile.yaml`, or `project-change-router.profile.yml` exists.
- Check for existing `project-change-router/profiles/`, `project-change-router/reports/`, feedback files, evaluation sets, generated route reports, and injected agent hint blocks in `AGENTS.md`, `CLAUDE.md`, `.codex/`, or `.claude/`.
- Classify each file as generated, user-authored calibration, or unknown before editing it.

Preservation rules:
- Never blindly overwrite `.project-change-router.yaml` or other profile files.
- Never remove ownership rules, module overrides, capability lifecycle metadata, public entries, manual feedback, or curated evaluation cases without explicit user confirmation.
- If a generated file conflicts with a user-authored correction, preserve the correction and report the conflict.
- If a file cannot be confidently classified as generated, treat it as user-authored and do not overwrite it automatically.

Validate the existing bundle before refreshing:
- Run `python <latest-skill>/scripts/validate_router_bundle.py --repo <repo-root> --format json`.
- Run `python <latest-skill>/scripts/check_bundle_governance.py --repo <repo-root> --format json`.
- If validation fails because the bundle is old, continue only with metadata refresh steps. Do not treat old-schema failure as permission to delete the bundle.
- If validation reports P0 issues unrelated to schema age, stop and report the exact files and fields that need human confirmation.

Refresh sequence:
- If `project-change-router/` already exists, run `python <latest-skill>/scripts/rebuild_index.py --repo <repo-root> --format json`.
- If no bundle exists, do not silently bootstrap. Ask whether the user wants first-time onboarding instead.
- After rebuild, run:
  - `python <latest-skill>/scripts/validate_router_bundle.py --repo <repo-root> --format json`
  - `python <latest-skill>/scripts/check_bundle_governance.py --repo <repo-root> --format json`
  - `python <latest-skill>/scripts/check_index_freshness.py --repo <repo-root> --format json`
  - `python <latest-skill>/scripts/run_evaluation.py --repo <repo-root> --format json`

Update generated local guidance:
- Refresh only project-change-router generated or marked blocks in agent guidance files.
- If a marked block exists, replace only the block content between its start and end markers.
- If no marked block exists, append a new marked project-change-router block without rewriting the original document.
- The guidance must mention route-before-editing, dual confidence, review stop behavior, allowed/forbidden write paths, lifecycle review, closeout checks, feedback write-back, and `.gitignore` inclusion checks.

Update output expectations:
- New route reports should expose `routing_confidence`, `routing_confidence_level`, `decision_confidence`, `decision_confidence_level`, `decision_basis`, `recommended_next_action`, `recommended_next_steps`, and `why_not_actions` when available.
- Do not manually fabricate these fields in old saved reports. Regenerate reports with the latest scripts when examples or verification artifacts need to reflect the new schema.
- If old saved reports are retained for history, label them as historical instead of mixing them with current examples.

Profile and calibration follow-up:
- If governance audit reports generated-only capability boundaries, broad ownership rules, missing public entries, or weak evaluation coverage, propose profile updates instead of guessing.
- If a route changed compared with the old bundle, record the reason and add or update an evaluation case.
- If human confirmation changes a route, owner, public entry, or lifecycle state, prepare a feedback file and run `sync_feedback.py` after confirmation.

.gitignore inclusion check:
- Check every newly generated report, temporary route output, cache, or local-only handoff file.
- Add ignore entries only for generated artifacts that should not be committed.
- Do not ignore the repository-local router bundle, curated profiles, or evaluation cases if the project intends to version them.

Stop conditions:
- Product code edits would be required.
- A user-authored profile or feedback file would be overwritten.
- The bundle source cannot be distinguished from the updated skill source.
- Validation reports non-schema P0 issues.
- The refresh would remove curated evaluation or feedback data.
- The repository is on a protected branch and the user's execution rules require an explicit branch/worktree decision.

Final report:
- State which latest skill path was used.
- List files changed, grouped as generated bundle, injected guidance, profiles, evaluation, feedback, and `.gitignore`.
- Summarize validation, governance, freshness, and evaluation results.
- Report P0/P1/P2 findings separately.
- List preserved user-authored files that were not overwritten.
- List recommended next calibration actions, but do not perform product implementation unless the user starts a separate routed task.
```

