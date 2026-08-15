# Bootstrap

This skill is global. It is not installed into a project repository by default.

When a repository needs durable routing metadata, generate a local bundle with:

```powershell
python scripts/bootstrap_router.py --repo <repo-root>
```

The generated bundle contains:

- `router-config.yaml`
- `references/capability-catalog.yaml`
- `references/module-map.yaml`
- `references/ownership.yaml`
- `references/change-rules.yaml`
- `references/path-to-capability-map.yaml`
- `references/exception-registry.yaml`
- `references/evaluation-set.yaml`
- `schemas/*.json`
- `reports/`

## Bundle Semantics

- the global skill stays in `~/.codex/skills/project-change-router`
- the generated bundle stays in `<repo>/project-change-router`
- the bundle is repository-local data and validation logic
- the skill remains reusable across repositories
- installing or verifying the global skill does not search for or modify repository bundles
- PCR 0.4 reads bundle schema v1, keeps reuse engine API v2, and adds architecture governance API v2 plus typed-finding/gate/change-flow/authorization API v1
- missing 0.4 precision becomes unknown/incomplete evidence without being written back by read-only checks

## Bootstrap Expectations

The bootstrap script must:

- discover repository modules from Java, Python, TypeScript, or mixed layouts
- classify modules into architecture layers
- infer a first-pass capability catalog
- generate a path-to-capability map with uncovered and ambiguous path diagnostics
- generate a starter evaluation set
- copy validation schemas
- create empty report directories
- preserve profile-backed exact architecture and structure guardrails in `references/change-rules.yaml`

After bootstrap, run:

```powershell
python scripts/check_bundle_governance.py --repo <repo-root>
python scripts/rebuild_index.py --repo <repo-root> --format json
```

Then aggregate the architecture evidence that applies to the repository:

```powershell
python scripts/check_index_freshness.py --repo <repo-root> --format json
python scripts/check_deps.py --repo <repo-root> --format json
python scripts/check_public_api.py --repo <repo-root> --format json
python scripts/check_structure.py --repo <repo-root> --format json
python scripts/run_evaluation.py --repo <repo-root> --format json
```

The initial generated evaluation set is seed evidence, not production calibration. Until the configured real-case threshold is met, evaluation is expected to report `review_only` and return a non-zero status. Preserve that evidence so the authoritative gate can block when required; curate real positive, boundary, veto, and false-positive/false-negative regression cases rather than lowering the threshold.

The first bundle is a starting point. The repository owner still needs to curate mature shared capabilities, stable owners, distinct reviewers, contracts, lifecycle metadata, public or internal-only boundaries, and positive plus boundary evaluation coverage.

## Existing Bundles

Do not bootstrap or rebuild only because the global skill was upgraded. First run the new skill's validation, governance, freshness, dependency, public API, structure, evaluation, and scoped reuse checks against the existing bundle. Continue using it when those read-only checks pass.

Rebuild only when repository structure, ownership, public entries, lifecycle state, or capability boundaries changed. Before that explicit write operation, move durable human truth into a root profile and preserve curated evaluation, feedback, owner, and lifecycle data. Schema-v1 read compatibility is not permission to rewrite old YAML with generated defaults.
