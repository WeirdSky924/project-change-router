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

## Bootstrap Expectations

The bootstrap script must:

- discover repository modules from Java, Python, TypeScript, or mixed layouts
- classify modules into architecture layers
- infer a first-pass capability catalog
- generate a path-to-capability map with uncovered and ambiguous path diagnostics
- generate a starter evaluation set
- copy validation schemas
- create empty report directories

After bootstrap, run:

```powershell
python scripts/check_bundle_governance.py --repo <repo-root>
```

The first bundle is a starting point. The repository owner still needs to curate mature shared capabilities, contracts, lifecycle metadata, and evaluation coverage.
