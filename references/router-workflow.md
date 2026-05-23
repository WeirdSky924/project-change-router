# Router Workflow

Use this workflow whenever the user asks to:

- add or modify product behavior in a large repository
- refactor repeated capability logic
- standardize change entry points for AI agents
- create a project-local change-router bundle
- validate that reuse and boundary rules are being followed

## Operating Model

1. Identify the repository root.
2. If `project-change-router/router-config.yaml` does not exist, bootstrap the bundle with `scripts/bootstrap_router.py`.
3. Use `scripts/resolve_entry.py` with the request text and known changed paths.
4. Read the routed capability entries before editing.
5. Run the required checks:
   - `scripts/check_reuse.py`
   - `scripts/check_deps.py`
   - `scripts/check_public_api.py`
   - `scripts/check_index_freshness.py`
6. If route confidence is low or multiple stable capabilities overlap, return `review`.
7. After changes, update the bundle if the change created a new capability or changed public boundaries.

## Route Outputs

The resolver emits:

- route action
- confidence
- primary capability
- secondary capabilities
- required reads
- required checks
- whether coordination or review is required

The resolver should never treat the catalog as infallible. Real code remains the final source of truth.
