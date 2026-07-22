# Reuse Scan Runtime

`check_reuse.py` is a capability-scoped duplicate-implementation guardrail. It is not a repository-wide semantic search engine and it does not replace source analysis.

## Execution Pipeline

1. Collect exact files from every `--changed-path`.
2. Resolve capabilities through the path map, owner modules, scope paths, public entries, module key/index files, related tests, and test bindings.
3. Expand to directly related dependency capabilities when configured.
4. Ignore repository-wide concrete mappings such as `** -> database-schema-migrations` when a specific mapping exists. A broad concrete mapping alone is not trusted as an automatic scope.
5. Enumerate owner and test surfaces only for the resolved capability scope.
6. Load or compute native fingerprints and rank candidate pairs.
7. Run exact text similarity only for bounded Top-K pairs.
8. Emit canonical, checkpoint, and diagnostic report classes.

If a changed path cannot be resolved, the scan returns `completion_status=incomplete`. It never falls back to unrelated capability owners.

## Native Fingerprint Cache

The cache uses Python's standard-library `sqlite3` and `hashlib`. It stores derived evidence only:

- file stat and sampled-content identity
- suffix and file size
- normalized length and token count
- bounded token hash sketch
- normalized-content digest
- fingerprint algorithm version

It does not persist normalized source text. Exact similarity reads full text only for Top-K pairs selected by the fingerprints.

If SQLite integrity prevents opening the cache, PCR preserves the corrupt database as a managed diagnostic artifact, rebuilds a fresh runtime database, and exposes `runtime_recovery` in scan metrics. The preserved artifact then follows diagnostic retention instead of being silently discarded.

Cache modes:

- `auto`: read and update fingerprints
- `read-only`: use existing fingerprints without updating them
- `off`: disable persistent fingerprints
- `rebuild`: clear fingerprints before the scan and repopulate them

By default, runtime state is outside the repository:

- Windows: `%LOCALAPPDATA%/project-change-router/repositories/<repo-key>/`
- Linux/macOS: `$XDG_CACHE_HOME/project-change-router/repositories/<repo-key>/` or `~/.cache/project-change-router/repositories/<repo-key>/`

Use `--runtime-dir` or `reuse_scan_runtime.runtime_dir` only when an explicit alternative is needed.

## Timeout and Cancellation

The CLI runs the scan in an isolated child process.

- The soft timeout stops scheduling new work and lets the worker write a checkpoint and structured result.
- The hard timeout terminates the child if one exact similarity operation does not return.
- `Ctrl+C` follows the same termination and report-finalization path.
- The hard timeout is always at least one second later than the soft timeout.

Timeout precedence:

```text
CLI override > repository profile/change-rules > generated defaults
```

Default generated values:

```yaml
reuse_scan_runtime:
  soft_timeout_seconds: 60
  hard_timeout_seconds: 75
  checkpoint_interval_seconds: 5
  cache_mode: auto
  diagnostics_mode: auto
  persist_reports: true
  slow_scan_diagnostic_seconds: 10
```

## Report Classes

### Canonical

The final machine contract consumed by agents and CI. It is emitted for complete, bounded, timed-out, cancelled, and errored runs.

### Checkpoint

Recoverable partial scan state. It is deleted after a complete run and retained temporarily after bounded, incomplete, timed-out, cancelled, or errored runs. It is never a final decision report.

### Diagnostic

Performance and scope evidence used to debug PCR itself. `auto` persists diagnostics for non-complete or slow runs; `always` persists every run; `never` disables diagnostic persistence.

Always interpret these fields together:

```text
result_status      = pass | warn | fail
completion_status  = complete | bounded | incomplete | timeout | cancelled | error
evidence_complete  = true | false
```

Examples:

| Meaning | result_status | completion_status |
| --- | --- | --- |
| No blocker in completed scope | `pass` | `complete` |
| Exact P1 duplicate found | `fail` | `complete` |
| No blocker found before budget limit | `warn` | `bounded` |
| Scope could not be resolved | `warn` | `incomplete` |
| Worker exceeded deadline | `warn` | `timeout` |
| P1 found before cancellation | `fail` | `cancelled` |

Only `completion_status=complete` and `evidence_complete=true` can support a completed-scope no-duplicate claim. Even then, PCR is scoped evidence, not proof about unrelated capabilities.

## Deduplication

The runtime deduplicates at three levels:

- comparison pairs: `A <-> B` is computed once even when multiple capabilities reference the pair
- findings: one file pair merges all implicated capability IDs and retains the strongest severity
- canonical artifacts: semantically identical input, scope, evidence, budget, and findings reuse one managed report artifact

Large pairs that pass fingerprint ranking but exceed exact-comparison limits are reported as `duplicate-fingerprint-candidate` P2 advisories. They require targeted source analysis and are not exact duplicate findings.

## Retention and Cleanup

Generated defaults:

```yaml
reuse_scan_retention:
  canonical_max_age_days: 90
  canonical_max_count: 500
  checkpoint_max_age_days: 7
  diagnostic_max_age_days: 3
  diagnostic_max_count: 200
  max_cache_entries: 50000
  max_runtime_bytes: 536870912
```

Blocking canonical reports are pinned. Cleanup deletes only artifacts registered in the runtime database and located under the resolved runtime root. It does not glob-delete repository files.

Run cleanup without scanning:

```powershell
python scripts/check_reuse.py --repo <repo-root> --cleanup-only --format json
```

## Exit Codes

- `0`: no P0/P1 blocker; bounded or unresolved results remain compatible unless `--strict-completeness` is used
- `1`: a P0/P1 blocker was found
- `2`: timeout, worker error, or strict completeness failure
- `130`: user cancellation

Consumers should use JSON fields rather than exit code alone.

## Existing Bundle Compatibility

The runtime reads bundle schema v1. Missing `reuse_scan_scope`, `reuse_scan_runtime`, and `reuse_scan_retention` sections receive code defaults without modifying the bundle.

Installing a newer skill:

- updates only the selected Codex/Claude Code skill directories
- uses staging, hash/API verification, and atomic replacement
- does not search for or modify repository-local `project-change-router/` directories
- does not run bootstrap or rebuild
- stores new runtime state outside repositories by default

Do not run `bootstrap_router.py` or `rebuild_index.py` merely to upgrade the installed skill. Rebuild only when repository structure or routing metadata actually needs refresh.
