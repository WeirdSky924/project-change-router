# Schema Overview

The generated bundle uses JSON Schema to validate both reference files and generated reports.

PCR 0.3 exposes architecture governance API v1 and keeps reuse engine API v2. Repository bundle schema v1 remains read-compatible: missing 0.3 fields receive safe in-memory defaults, and read-only validation or guardrail commands do not write those defaults back to YAML. Installing or verifying the global skill does not search for, bootstrap, rebuild, or modify repository bundles.

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
- `reuse-scan-report.schema.json`

## Validation Rules

- reference files must include metadata such as `schema_version`, `generated_at`, `generated_by`, `source_repository`, and `source_commit`
- capability and module identifiers must be stable and machine-readable
- generated reports must be serializable to JSON and schema-valid
- stale or missing referenced paths must be surfaced as freshness failures
- route decisions expose `authorization_context` and a SHA-256 `route_fingerprint` for task-bound authorization invalidation
- semantic governance drift is reported separately from schema validity through `check_bundle_governance.py`
- route decision reports must include review guidance, write constraints, closeout steps, composite route metadata, lifecycle action metadata, and regression capture hints
- dependency findings distinguish runtime edges and cycles from Python `TYPE_CHECKING` and TypeScript type-only edges
- `architecture_baseline` entries must match one exact finding identity and include a stable owner, exit stage, and lowercase SHA-256 fingerprint; wildcard identities and provisional owners are invalid
- structure rules use the canonical `central_growth_baseline`, `forbidden_implementation_roots`, and `exclusive_source_owners` collections in `change-rules.yaml`
- evaluation summaries constrain all ratios to `[0,1]`; `normal` additionally requires non-lowerable policy floors, curated case IDs, the six-category matrix, catalog-valid exact primary/secondary expectations, and an attestation whose engine version and digest match current route-affecting truth

Schema compatibility is directional. A v0.3 runtime can read a schema-v1 bundle without rewriting it, but a historical generated report is not guaranteed to validate as a current report fixture. Regenerate reports that are intentionally kept as current examples or CI inputs.

## Architecture Collections

Profile overrides declare architecture collections under `guardrails`; bootstrap or an explicit rebuild projects them into `references/change-rules.yaml`:

- `architecture_baseline`: exact dependency-direction, runtime/type-only cycle, or public-API debt identities
- `central_growth_baseline`: exact comparison commit, central file/symbol, measured limits, owner, and exit stage
- `forbidden_implementation_roots`: roots where new production implementations are not allowed
- `exclusive_source_owners`: one canonical source owner and the exact source patterns that may exist only there

Empty collections are valid when the repository has no approved debt or structure rule. Do not populate them merely to make a failing check pass.

## Governance Output Contract

See `references/governance-outputs.md` for the behavioral contract behind the seven route output groups. Schema validation only proves the fields exist. The governance contract defines when agents may read, ask, repair profile metadata, or write code.
