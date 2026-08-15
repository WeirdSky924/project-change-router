# Schema Overview

The generated bundle uses JSON Schema to validate both reference files and generated reports.

PCR 0.4 exposes architecture governance API v2, reuse engine API v2, and typed-finding, gate, change-flow, and authorization API v1. Repository bundle schema v1 remains read-compatible. Read-only validation and guardrail commands never write 0.4 fields back to old YAML. When a legacy bundle cannot provide the precision needed for a trusted baseline, relevance closure, or typed finding, the runtime emits `unknown` and blocks instead of fabricating a default. Installing or verifying the global skill never searches for, bootstraps, rebuilds, or modifies repository bundles.

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
- `typed-finding.schema.json`
- `execution-gate.schema.json`
- `evidence-baseline.schema.json`
- `change-flow-report.schema.json`
- `authorization-request.schema.json`
- `authorization-grant.schema.json`
- `runtime-identity.schema.json`
- `precise-read-targets.schema.json`

## Validation Rules

- reference files must include metadata such as `schema_version`, `generated_at`, `generated_by`, `source_repository`, and `source_commit`
- capability and module identifiers must be stable and machine-readable
- generated reports must be serializable to JSON and schema-valid
- stale or missing referenced paths must be surfaced as freshness failures
- route decisions expose `authorization_context` and a SHA-256 `route_fingerprint` for task-bound authorization invalidation
- all current reports expose one `runtime_identity` binding the skill/install/API/schema/parser/policy identity used to produce the result
- every gate-affecting result is a schema-valid typed finding with a stable content-derived ID, evidence digest, relevance trace, and policy rule
- `execution_gate` has exactly `pass`, `conditional`, and `blocked`; it is the authoritative write decision while `action` remains advisory
- compact change-flow output always includes the non-projectable safety envelope and a digest-verified content-addressed full artifact
- authorization requests and grants validate separately; a grant records external authority and cannot create or revive it
- semantic governance drift is reported separately from schema validity through `check_bundle_governance.py`
- route decision reports must include review guidance, write constraints, closeout steps, composite route metadata, lifecycle action metadata, and regression capture hints
- dependency findings distinguish runtime edges and cycles from Python `TYPE_CHECKING` and TypeScript type-only edges
- `architecture_baseline` entries must match one exact finding identity and include a stable owner, exit stage, and lowercase SHA-256 fingerprint; wildcard identities and provisional owners are invalid
- structure rules use the canonical `central_growth_baseline`, `forbidden_implementation_roots`, and `exclusive_source_owners` collections in `change-rules.yaml`
- evaluation summaries constrain all ratios to `[0,1]`; `normal` additionally requires non-lowerable policy floors, curated case IDs, the six-category matrix, catalog-valid exact primary/secondary expectations, and an attestation whose engine version and digest match current route-affecting truth

Schema compatibility is directional. A v0.4 runtime can read a schema-v1 bundle without rewriting it, but a historical generated report is not guaranteed to validate as a current report fixture. Regenerate reports that are intentionally kept as current examples or CI inputs.

## Typed Finding Origin Map

Adapters preserve the original report finding under `evidence` and bind it by digest. The current normalized origin/type map is:

| Origin | Finding types or families |
| --- | --- |
| `freshness` | unindexed/stale/coverage findings, `dynamic_import_unknown`, `historical_dynamic_import_debt`, or `freshness_evidence_incomplete` |
| `governance` | `duplicate_owner`, ownership/profile/catalog findings, `governance_violation`, or `governance_evidence_incomplete` |
| `dependency` | `dependency_violation`, unresolved/dynamic import findings, or `dependency_evidence_incomplete` |
| `public_api` | `public_export_conflict`, `historical_public_api_debt`, dynamic import findings, or `public_api_evidence_incomplete` |
| `structure` | `structure_violation`, `duplicate_owner`, `generated_output_pin_invalid`, or `structure_evidence_incomplete` |
| `reuse` | `duplicate_implementation`, `cross_capability_duplicate`, `reuse_evidence_incomplete`, or `reuse_evidence_incomplete` fallback |
| route/lifecycle evidence | unindexed path, owner/canonical/lifecycle/high-risk route findings produced directly by the route evidence adapter |

Rule-specific names remain stable normalized forms when no special family applies. A new origin or type must define invariant class, severity policy, delta/relevance behavior, and a regression fixture before it can influence the authoritative gate.

## Runtime Identity

`runtime-identity.schema.json` binds `skill_version`, optional Git commit, installed payload digest and source, compatible bundle schemas, report and API versions, gate policy version, parser versions, and the final identity digest. Caches, trusted baselines, typed findings, authorization contexts, and flow artifacts include or derive from this identity so results from different installed payloads cannot be silently mixed.

## Architecture Collections

Profile overrides declare architecture collections under `guardrails`; bootstrap or an explicit rebuild projects them into `references/change-rules.yaml`:

- `architecture_baseline`: exact dependency-direction, runtime/type-only cycle, or public-API debt identities
- `central_growth_baseline`: exact comparison commit, central file/symbol, measured limits, owner, and exit stage
- `forbidden_implementation_roots`: roots where new production implementations are not allowed
- `exclusive_source_owners`: one canonical source owner and the exact source patterns that may exist only there

Empty collections are valid when the repository has no approved debt or structure rule. Do not populate them merely to make a failing check pass.

## Governance Output Contract

See `references/governance-outputs.md` for the behavioral contract behind the seven route output groups. Schema validation only proves the fields exist. The governance contract defines when agents may read, ask, repair profile metadata, or write code.
