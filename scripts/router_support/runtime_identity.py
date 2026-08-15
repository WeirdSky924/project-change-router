from __future__ import annotations

import hashlib
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from router_support.typed_findings import canonical_json, digest_value


INSTALL_MANIFEST = ".installation-manifest.json"
IGNORED_PAYLOAD_PARTS = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "project-change-router",
        INSTALL_MANIFEST,
    }
)


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value if value else None


def _source_payload_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_PAYLOAD_PARTS for part in relative.parts):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        hashes[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(hashes.items()))


def _payload_identity(root: Path) -> tuple[str, str]:
    manifest_path = root / INSTALL_MANIFEST
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = {}
        files = manifest.get("files")
        if isinstance(files, dict) and all(
            isinstance(path, str) and isinstance(digest, str)
            for path, digest in files.items()
        ):
            return digest_value(dict(sorted(files.items()))), "installation_manifest"
    return digest_value(_source_payload_hashes(root)), "source_payload"


def _quick_state_key(root: Path) -> str:
    manifest = root / INSTALL_MANIFEST
    if manifest.is_file():
        stat = manifest.stat()
        return f"manifest:{stat.st_mtime_ns}:{stat.st_size}"
    commit = _git_commit(root)
    if commit:
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            status = "git-status-unavailable"
        dirty_stats: list[tuple[str, int, int]] = []
        for line in status.splitlines():
            relative = line[3:].split(" -> ")[-1]
            path = root / relative
            if path.is_file():
                stat = path.stat()
                dirty_stats.append((relative, stat.st_mtime_ns, stat.st_size))
        return digest_value({"commit": commit, "status": status, "stats": dirty_stats})
    stats = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED_PAYLOAD_PARTS for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            stat = path.stat()
            stats.append((relative.as_posix(), stat.st_mtime_ns, stat.st_size))
    return digest_value(stats)


@lru_cache(maxsize=16)
def _runtime_identity_cached(root_text: str, state_key: str) -> dict[str, Any]:
    root = Path(root_text)
    version_path = root / "skill-version.json"
    if not version_path.is_file():
        raise FileNotFoundError(f"missing version metadata: {version_path}")
    version = json.loads(version_path.read_text(encoding="utf-8"))
    payload_digest, payload_source = _payload_identity(root)
    identity = {
        "skill_version": str(version.get("skill_version", "unknown")),
        "skill_git_commit": _git_commit(root),
        "installed_payload_digest": payload_digest,
        "installed_payload_source": payload_source,
        "bundle_schema_compatibility": list(
            version.get("bundle_schema_compatibility", [])
        ),
        "report_schema_version": int(version.get("report_schema_version", 0)),
        "reuse_engine_api_version": int(
            version.get("reuse_engine_api_version", 0)
        ),
        "architecture_governance_api_version": int(
            version.get("architecture_governance_api_version", 0)
        ),
        "typed_finding_schema_version": int(
            version.get("typed_finding_schema_version", 0)
        ),
        "gate_policy_version": int(version.get("gate_policy_version", 0)),
        "change_flow_api_version": int(version.get("change_flow_api_version", 0)),
        "authorization_api_version": int(
            version.get("authorization_api_version", 0)
        ),
        "parser_versions": dict(version.get("parser_versions", {})),
    }
    identity["identity_digest"] = hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()
    return identity


def runtime_identity(skill_root: Path | None = None) -> dict[str, Any]:
    root = Path(skill_root or _skill_root()).resolve()
    return dict(_runtime_identity_cached(str(root), _quick_state_key(root)))
