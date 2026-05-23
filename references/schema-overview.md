# Schema Overview

The generated bundle uses JSON Schema to validate both reference files and generated reports.

## Reference Schemas

- `router-config.schema.json`
- `capability-catalog.schema.json`
- `module-map.schema.json`
- `ownership.schema.json`
- `change-rules.schema.json`
- `exception-registry.schema.json`
- `evaluation-set.schema.json`

## Report Schemas

- `route-decision-report.schema.json`
- `guardrail-report.schema.json`
- `index-rebuild-report.schema.json`
- `evaluation-summary.schema.json`

## Validation Rules

- reference files must include metadata such as `schema_version`, `generated_at`, `generated_by`, `source_repository`, and `source_commit`
- capability and module identifiers must be stable and machine-readable
- generated reports must be serializable to JSON and schema-valid
- stale or missing referenced paths must be surfaced as freshness failures
