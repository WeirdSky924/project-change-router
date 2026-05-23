---
name: project-change-router
description: Project-level change routing and reuse governance for large repositories. Use when Codex needs to decide whether a request should reuse, extend, extract, introduce, or review a capability before editing code, and when Codex should bootstrap or validate a repository-local router bundle for Java, Python, TypeScript, or mixed monorepos.
---

# Project Change Router

## Overview

Use this skill to turn a large repository into a governed change-routing system. It helps Codex locate the correct capability entry, avoid duplicate implementations, enforce boundary checks, and create or validate a repository-local router bundle.

## Workflow

1. Detect whether the request is a feature addition, feature modification, refactor, migration, or bug fix.
2. Find the repository root and look for an existing `project-change-router/` bundle.
3. If the bundle is missing, bootstrap one from the current repository structure.
4. Resolve the route action with the repository-local catalog and module map.
5. Read the required capability entries and public code entry points.
6. Apply the change only in the routed layer.
7. Run the required guardrails and capability-bound tests.
8. If the route is `review`, stop automatic editing and report the ambiguity or risk.
9. If the change reveals stale indexes or missing capability coverage, update the bundle and record the outcome.

## Route Actions

- `reuse`: use an existing capability without changing its core
- `extend`: add behavior through a shared capability entry or compatible internal change
- `extract`: move repeated logic into a shared capability first
- `new`: introduce a new capability because no acceptable shared fit exists
- `review`: stop automatic routing because the request is ambiguous, high-risk, or multi-capability

## Repository Bundle

The skill can create or validate a repository-local bundle named `project-change-router/` with:

- `router-config.yaml`
- `references/`
- `schemas/`
- `reports/`

Use the bundle when you need a durable, repo-specific routing index. Use the global skill when you need the process itself.

## References

- `references/router-workflow.md`
- `references/bootstrap.md`
- `references/repo-discovery.md`
- `references/schema-overview.md`
- `references/evaluation.md`

## Resources

- `scripts/bootstrap_router.py`
- `scripts/resolve_entry.py`
- `scripts/rebuild_index.py`
- `scripts/check_reuse.py`
- `scripts/check_deps.py`
- `scripts/check_public_api.py`
- `scripts/check_index_freshness.py`
- `scripts/run_evaluation.py`
- `scripts/sync_feedback.py`
- `scripts/validate_router_bundle.py`

### assets

- `assets/router-icon.svg`

## Notes

- This skill is standalone and installable under `~/.codex/skills`.
- It does not depend on a specific repository.
- The repository-local router bundle is generated on demand and is not the skill itself.
