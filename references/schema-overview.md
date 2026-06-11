# Schema Overview

The generated bundle uses JSON Schema to validate both reference files and generated reports.

## Reference Schemas

- `router-config.schema.json`
- `capability-catalog.schema.json`
- `module-map.schema.json`
- `ownership.schema.json`
- `change-rules.schema.json`
- `path-to-capability-map.schema.json`
- `exception-registry.schema.json`
- `evaluation-set.schema.json`

## Report Schemas

- `route-decision-report.schema.json`
- `guardrail-report.schema.json`
- `index-rebuild-report.schema.json`
- `evaluation-summary.schema.json`
- `governance-report.schema.json`

## Validation Rules

- reference files must include metadata such as `schema_version`, `generated_at`, `generated_by`, `source_repository`, and `source_commit`
- capability and module identifiers must be stable and machine-readable
- generated reports must be serializable to JSON and schema-valid
- stale or missing referenced paths must be surfaced as freshness failures
- semantic governance drift is reported separately from schema validity through `check_bundle_governance.py`
- route decision reports must include review guidance, write constraints, closeout steps, composite route metadata, lifecycle action metadata, and regression capture hints

## Governance Output Contract

See `references/governance-outputs.md` for the behavioral contract behind the seven route output groups. Schema validation only proves the fields exist. The governance contract defines when agents may read, ask, repair profile metadata, or write code.
