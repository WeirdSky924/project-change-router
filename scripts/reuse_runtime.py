from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


RUNTIME_SCHEMA_VERSION = 1
FINGERPRINT_VERSION = 1


@dataclass
class ReuseRuntimePolicy:
    soft_timeout_seconds: float = 60.0
    hard_timeout_seconds: float = 75.0
    checkpoint_interval_seconds: float = 5.0
    cache_mode: str = "auto"
    diagnostics_mode: str = "auto"
    persist_reports: bool = True
    slow_scan_diagnostic_seconds: float = 10.0


@dataclass
class ReuseRetentionPolicy:
    canonical_max_age_days: int = 90
    canonical_max_count: int = 500
    checkpoint_max_age_days: int = 7
    diagnostic_max_age_days: int = 3
    diagnostic_max_count: int = 200
    max_cache_entries: int = 50_000
    max_runtime_bytes: int = 512 * 1024 * 1024


@dataclass
class ReportArtifact:
    path: Path
    deduplicated: bool
    semantic_digest: str
    occurrence_count: int


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "on"}:
            return True
        if lowered in {"false", "no", "0", "off"}:
            return False
    return default


def _policy_values(data: dict[str, Any], cls: type[Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field_info in dataclasses.fields(cls):
        raw = data.get(field_info.name, field_info.default)
        default = field_info.default
        try:
            if isinstance(default, bool):
                values[field_info.name] = _coerce_bool(raw, default)
            elif isinstance(default, int):
                values[field_info.name] = int(raw)
            elif isinstance(default, float):
                values[field_info.name] = float(raw)
            else:
                values[field_info.name] = str(raw)
        except (TypeError, ValueError):
            values[field_info.name] = default
    return values


def runtime_policy_from_bundle(bundle: dict[str, Any], overrides: Optional[dict[str, Any]] = None) -> ReuseRuntimePolicy:
    configured = dict(bundle.get("change_rules", {}).get("reuse_scan_runtime", {}))
    configured.update({key: value for key, value in (overrides or {}).items() if value is not None})
    policy = ReuseRuntimePolicy(**_policy_values(configured, ReuseRuntimePolicy))
    policy.soft_timeout_seconds = max(0.0, policy.soft_timeout_seconds)
    minimum_hard_timeout = policy.soft_timeout_seconds + 1.0 if policy.soft_timeout_seconds > 0 else 0.0
    policy.hard_timeout_seconds = max(minimum_hard_timeout, policy.hard_timeout_seconds)
    policy.checkpoint_interval_seconds = max(0.1, policy.checkpoint_interval_seconds)
    if policy.cache_mode not in {"auto", "read-only", "off", "rebuild"}:
        policy.cache_mode = "auto"
    if policy.diagnostics_mode not in {"auto", "always", "never"}:
        policy.diagnostics_mode = "auto"
    return policy


def retention_policy_from_bundle(bundle: dict[str, Any]) -> ReuseRetentionPolicy:
    configured = dict(bundle.get("change_rules", {}).get("reuse_scan_retention", {}))
    policy = ReuseRetentionPolicy(**_policy_values(configured, ReuseRetentionPolicy))
    for field_info in dataclasses.fields(ReuseRetentionPolicy):
        setattr(policy, field_info.name, max(0, int(getattr(policy, field_info.name))))
    return policy


def runtime_root_for_repo(repo_root: Path, bundle: dict[str, Any], override: Optional[str] = None) -> Path:
    configured = override or bundle.get("change_rules", {}).get("reuse_scan_runtime", {}).get("runtime_dir")
    if configured:
        path = Path(str(configured)).expanduser()
        if not path.is_absolute():
            raise ValueError("reuse runtime_dir must be absolute and outside the target repository")
        resolved = path.resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            return resolved
        raise ValueError("reuse runtime_dir must be outside the target repository")
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    repo_identity = f"{repo_root.resolve()}|{bundle.get('config', {}).get('repo_id', repo_root.name)}"
    repo_digest = hashlib.sha256(repo_identity.encode("utf-8")).hexdigest()[:16]
    safe_name = "".join(char if char.isalnum() or char in "-_" else "-" for char in repo_root.name).strip("-")
    return base / "project-change-router" / "repositories" / f"{safe_name or 'repo'}-{repo_digest}"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def semantic_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


class ReuseRuntimeStore:
    def __init__(self, runtime_root: Path, cache_mode: str = "auto") -> None:
        self.runtime_root = runtime_root.resolve()
        self.cache_mode = cache_mode
        self.recovery_event: Optional[dict[str, Any]] = None
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.runtime_root / "reuse-runtime.sqlite3"
        try:
            self.connection = self._connect()
            self._initialize()
        except sqlite3.DatabaseError as exc:
            try:
                self.connection.close()
            except (AttributeError, sqlite3.Error):
                pass
            backup = self.runtime_root / f"reuse-runtime.corrupt-{int(time.time())}-{uuid.uuid4().hex[:8]}.sqlite3"
            if self.db_path.exists():
                os.replace(self.db_path, backup)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(self.db_path) + suffix)
                if sidecar.exists():
                    sidecar.unlink()
            self.connection = self._connect()
            self._initialize()
            self.recovery_event = {
                "reason": "sqlite_database_rebuilt",
                "error": f"{type(exc).__name__}: {exc}",
                "preserved_corrupt_database": str(backup) if backup.exists() else None,
            }
            if backup.exists():
                now = time.time()
                self.connection.execute(
                    """
                    INSERT INTO reports(
                        report_class, semantic_digest, path, result_status,
                        pinned, created_at, last_seen_at, occurrence_count
                    ) VALUES('diagnostic', ?, ?, 'warn', 0, ?, ?, 1)
                    """,
                    (semantic_digest(self.recovery_event), str(backup), now, now),
                )
                self.connection.commit()

        if cache_mode == "rebuild":
            self.connection.execute("DELETE FROM fingerprints")
            self.connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA busy_timeout=10000")
            return connection
        except BaseException:
            connection.close()
            raise

    def _initialize(self) -> None:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        version_row = self.connection.execute(
            "SELECT value FROM metadata WHERE key = 'runtime_schema_version'"
        ).fetchone()
        previous_version = int(version_row["value"]) if version_row else None
        if previous_version is not None and previous_version != RUNTIME_SCHEMA_VERSION:
            self.connection.execute("DROP TABLE IF EXISTS fingerprints")
            self.recovery_event = {
                "reason": "runtime_schema_migrated",
                "from_version": previous_version,
                "to_version": RUNTIME_SCHEMA_VERSION,
            }
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fingerprints (
                path TEXT PRIMARY KEY,
                stat_key TEXT NOT NULL,
                fingerprint_version INTEGER NOT NULL,
                suffix TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                normalized_length INTEGER NOT NULL,
                token_count INTEGER NOT NULL,
                token_sketch TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_class TEXT NOT NULL,
                semantic_digest TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                result_status TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                occurrence_count INTEGER NOT NULL DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_reports_class_created
                ON reports(report_class, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_semantic
                ON reports(report_class, semantic_digest);
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('runtime_schema_version', ?)",
            (str(RUNTIME_SCHEMA_VERSION),),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ReuseRuntimeStore":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.close()

    def get_fingerprint(self, rel_path: str, stat_key: str) -> Optional[dict[str, Any]]:
        if self.cache_mode in {"off", "rebuild"}:
            return None
        row = self.connection.execute(
            "SELECT * FROM fingerprints WHERE path = ? AND stat_key = ? AND fingerprint_version = ?",
            (rel_path, stat_key, FINGERPRINT_VERSION),
        ).fetchone()
        if row is None:
            return None
        if self.cache_mode != "read-only":
            self.connection.execute("UPDATE fingerprints SET last_accessed = ? WHERE path = ?", (time.time(), rel_path))
            self.connection.commit()
        value = dict(row)
        value["token_sketch"] = json.loads(value["token_sketch"])
        return value

    def put_fingerprint(self, rel_path: str, stat_key: str, value: dict[str, Any]) -> None:
        if self.cache_mode in {"off", "read-only"}:
            return
        now = time.time()
        self.connection.execute(
            """
            INSERT INTO fingerprints(
                path, stat_key, fingerprint_version, suffix, file_size,
                normalized_length, token_count, token_sketch, content_digest,
                created_at, last_accessed
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                stat_key = excluded.stat_key,
                fingerprint_version = excluded.fingerprint_version,
                suffix = excluded.suffix,
                file_size = excluded.file_size,
                normalized_length = excluded.normalized_length,
                token_count = excluded.token_count,
                token_sketch = excluded.token_sketch,
                content_digest = excluded.content_digest,
                created_at = excluded.created_at,
                last_accessed = excluded.last_accessed
            """,
            (
                rel_path,
                stat_key,
                FINGERPRINT_VERSION,
                value["suffix"],
                value["file_size"],
                value["normalized_length"],
                value["token_count"],
                json.dumps(value["token_sketch"], separators=(",", ":")),
                value["content_digest"],
                now,
                now,
            ),
        )
        self.connection.commit()

    def persist_report(
        self,
        report_class: str,
        payload: dict[str, Any],
        semantic_value: Optional[dict[str, Any]] = None,
        pinned: bool = False,
    ) -> ReportArtifact:
        digest = semantic_digest(semantic_value if semantic_value is not None else payload)
        if report_class == "canonical":
            existing = self.connection.execute(
                "SELECT * FROM reports WHERE report_class = ? AND semantic_digest = ? ORDER BY id DESC LIMIT 1",
                (report_class, digest),
            ).fetchone()
            if existing is not None:
                existing_path = Path(existing["path"])
                if existing_path.exists() and self._is_managed_path(existing_path):
                    count = int(existing["occurrence_count"]) + 1
                    self.connection.execute(
                        "UPDATE reports SET last_seen_at = ?, occurrence_count = ?, pinned = MAX(pinned, ?) WHERE id = ?",
                        (time.time(), count, 1 if pinned else 0, existing["id"]),
                    )
                    self.connection.commit()
                    return ReportArtifact(existing_path, True, digest, count)

        run_id = str(payload.get("run_id") or payload.get("report_id") or uuid.uuid4().hex)
        safe_run_id = "".join(char if char.isalnum() or char in "-_" else "-" for char in run_id)
        target = self.runtime_root / "reports" / report_class / f"{safe_run_id}-{digest[:12]}.json"
        atomic_write_json(target, payload)
        now = time.time()
        self.connection.execute(
            """
            INSERT INTO reports(
                report_class, semantic_digest, path, result_status,
                pinned, created_at, last_seen_at, occurrence_count
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                report_class,
                digest,
                str(target),
                str(payload.get("result_status", payload.get("status", "unknown"))),
                1 if pinned else 0,
                now,
                now,
            ),
        )
        self.connection.commit()
        return ReportArtifact(target, False, digest, 1)

    def write_checkpoint(self, run_id: str, payload: dict[str, Any]) -> Path:
        target = self.runtime_root / "reports" / "checkpoint" / f"{run_id}.json"
        atomic_write_json(target, payload)
        now = time.time()
        digest = semantic_digest({"run_id": run_id, "report_class": "checkpoint"})
        self.connection.execute(
            """
            INSERT INTO reports(
                report_class, semantic_digest, path, result_status,
                pinned, created_at, last_seen_at, occurrence_count
            ) VALUES('checkpoint', ?, ?, ?, 0, ?, ?, 1)
            ON CONFLICT(path) DO UPDATE SET
                result_status = excluded.result_status,
                last_seen_at = excluded.last_seen_at
            """,
            (digest, str(target), str(payload.get("completion_status", "running")), now, now),
        )
        self.connection.commit()
        return target

    def load_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        target = self.runtime_root / "reports" / "checkpoint" / f"{run_id}.json"
        if not target.exists():
            return None
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def delete_checkpoint(self, run_id: str) -> None:
        target = self.runtime_root / "reports" / "checkpoint" / f"{run_id}.json"
        if target.exists() and self._is_managed_path(target):
            target.unlink()
        self.connection.execute("DELETE FROM reports WHERE path = ?", (str(target),))
        self.connection.commit()

    def cleanup(self, repo_root: Path, policy: ReuseRetentionPolicy) -> dict[str, int]:
        removed = {"fingerprints": 0, "canonical": 0, "checkpoint": 0, "diagnostic": 0}
        removed["fingerprints"] += self._prune_missing_fingerprints(repo_root)
        count_row = self.connection.execute("SELECT COUNT(*) AS count FROM fingerprints").fetchone()
        cache_count = int(count_row["count"] if count_row else 0)
        if cache_count > policy.max_cache_entries:
            remove_count = cache_count - policy.max_cache_entries
            rows = self.connection.execute(
                "SELECT path FROM fingerprints ORDER BY last_accessed ASC LIMIT ?", (remove_count,)
            ).fetchall()
            self.connection.executemany("DELETE FROM fingerprints WHERE path = ?", [(row["path"],) for row in rows])
            removed["fingerprints"] += len(rows)

        now = time.time()
        age_limits = {
            "canonical": policy.canonical_max_age_days,
            "checkpoint": policy.checkpoint_max_age_days,
            "diagnostic": policy.diagnostic_max_age_days,
        }
        for report_class, days in age_limits.items():
            cutoff = now - (days * 86400)
            rows = self.connection.execute(
                "SELECT * FROM reports WHERE report_class = ? AND pinned = 0 AND last_seen_at < ? ORDER BY last_seen_at ASC",
                (report_class, cutoff),
            ).fetchall()
            removed[report_class] += self._remove_report_rows(rows)

        removed["canonical"] += self._trim_report_count("canonical", policy.canonical_max_count)
        removed["diagnostic"] += self._trim_report_count("diagnostic", policy.diagnostic_max_count)
        self.connection.commit()
        self._trim_runtime_size(policy.max_runtime_bytes, removed)
        self.connection.commit()
        return removed

    def _prune_missing_fingerprints(self, repo_root: Path, batch_size: int = 1000) -> int:
        rows = self.connection.execute(
            "SELECT path FROM fingerprints ORDER BY last_accessed ASC LIMIT ?", (batch_size,)
        ).fetchall()
        missing = [(row["path"],) for row in rows if not (repo_root / row["path"]).exists()]
        if missing:
            self.connection.executemany("DELETE FROM fingerprints WHERE path = ?", missing)
        return len(missing)

    def _trim_report_count(self, report_class: str, maximum: int) -> int:
        rows = self.connection.execute(
            "SELECT * FROM reports WHERE report_class = ? AND pinned = 0 ORDER BY last_seen_at DESC",
            (report_class,),
        ).fetchall()
        return self._remove_report_rows(rows[maximum:]) if len(rows) > maximum else 0

    def _trim_runtime_size(self, maximum: int, removed: dict[str, int]) -> None:
        if maximum <= 0:
            return
        size = sum(path.stat().st_size for path in self.runtime_root.rglob("*") if path.is_file())
        if size <= maximum:
            return
        rows = self.connection.execute(
            """
            SELECT * FROM reports
            WHERE pinned = 0
            ORDER BY CASE report_class
                WHEN 'diagnostic' THEN 0
                WHEN 'checkpoint' THEN 1
                ELSE 2
            END, last_seen_at ASC
            """
        ).fetchall()
        for row in rows:
            if size <= maximum:
                break
            path = Path(row["path"])
            file_size = path.stat().st_size if path.exists() else 0
            if self._remove_report_rows([row]):
                removed[row["report_class"]] = removed.get(row["report_class"], 0) + 1
                size -= file_size

    def _remove_report_rows(self, rows: Iterable[sqlite3.Row]) -> int:
        removed = 0
        for row in rows:
            path = Path(row["path"])
            if path.exists() and self._is_managed_path(path):
                path.unlink()
            self.connection.execute("DELETE FROM reports WHERE id = ?", (row["id"],))
            removed += 1
        return removed

    def _is_managed_path(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.runtime_root)
            return True
        except ValueError:
            return False


def file_stat_key(path: Path) -> str:
    stat = path.stat()
    sample_size = 4096
    with path.open("rb") as handle:
        if stat.st_size <= sample_size * 3:
            sample = handle.read()
        else:
            first = handle.read(sample_size)
            handle.seek(max(0, (stat.st_size // 2) - (sample_size // 2)))
            middle = handle.read(sample_size)
            handle.seek(max(0, stat.st_size - sample_size))
            last = handle.read(sample_size)
            sample = first + middle + last
    sample_digest = hashlib.blake2b(sample, digest_size=12).hexdigest()
    payload = f"{stat.st_size}:{stat.st_mtime_ns}:{getattr(stat, 'st_ctime_ns', 0)}:{sample_digest}"
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def token_sketch(tokens: Iterable[str], maximum: int = 256) -> list[str]:
    hashes = {
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).hexdigest()
        for token in tokens
        if token
    }
    return sorted(hashes)[:maximum]


def semantic_report_value(report: dict[str, Any]) -> dict[str, Any]:
    scan = report.get("summary", {}).get("scan", {})
    return {
        "report_schema_version": report.get("report_schema_version"),
        "script": report.get("script"),
        "result_status": report.get("result_status"),
        "completion_status": report.get("completion_status"),
        "blocking": report.get("blocking"),
        "input_fingerprint": report.get("input_fingerprint"),
        "evidence_complete": report.get("evidence_complete"),
        "scope": scan.get("scope"),
        "fingerprint_version": scan.get("fingerprint_version"),
        "candidate_file_count": scan.get("candidate_file_count"),
        "owner_file_count": scan.get("owner_file_count"),
        "unique_pair_count": scan.get("unique_pair_count"),
        "comparisons_planned": scan.get("comparisons_planned"),
        "comparisons_run": scan.get("comparisons_run"),
        "comparisons_skipped_by_size": scan.get("comparisons_skipped_by_size"),
        "budget": scan.get("budget"),
        "findings": report.get("findings", []),
    }
