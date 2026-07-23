#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path


SKILL_NAME = "project-change-router"


INSTALL_MANIFEST = ".installation-manifest.json"
INSTALL_IGNORED_NAMES = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    "project-change-router",
    INSTALL_MANIFEST,
)
INSTALL_IGNORE = shutil.ignore_patterns(*INSTALL_IGNORED_NAMES)


@dataclass(frozen=True)
class PreparedInstall:
    destination: Path
    staging_parent: Path
    staged: Path
    backup: Path
    had_destination: bool
    manifest: dict[str, object]


def handle_remove_readonly(func, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def source_version(skill_root: Path) -> dict[str, object]:
    version_path = skill_root / "skill-version.json"
    if not version_path.exists():
        raise FileNotFoundError(f"missing version metadata: {version_path}")
    return json.loads(version_path.read_text(encoding="utf-8"))


def install_payload_files(skill_root: Path) -> list[Path]:
    files = []
    for path in skill_root.rglob("*"):
        relative = path.relative_to(skill_root)
        if any(part in INSTALL_IGNORED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise RuntimeError(
                f"install payload symlink is not allowed: {relative.as_posix()}"
            )
        if not path.is_file():
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(skill_root).as_posix())


def install_manifest(skill_root: Path) -> dict[str, object]:
    hashes: dict[str, str] = {}
    required = ("SKILL.md", "skill-version.json", "scripts/router_core.py")
    for relative in required:
        if not (skill_root / relative).is_file():
            raise FileNotFoundError(f"required install file missing: {skill_root / relative}")
    for path in install_payload_files(skill_root):
        relative = path.relative_to(skill_root).as_posix()
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        **source_version(skill_root),
        "manifest_schema_version": 2,
        "files": hashes,
    }


def verify_skill_install(skill_root: Path) -> dict[str, object]:
    manifest_path = skill_root / INSTALL_MANIFEST
    if not manifest_path.is_file():
        raise RuntimeError(
            f"installed skill installation manifest is missing: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_schema = manifest.get("manifest_schema_version")
    if type(manifest_schema) is not int or manifest_schema != 2:
        raise RuntimeError(
            f"installed skill manifest schema {manifest_schema!r} cannot prove "
            "complete payload integrity; reinstall required"
        )
    expected_hashes = manifest.get("files", {})
    if not isinstance(expected_hashes, dict):
        raise RuntimeError("installed skill manifest files must be an object")
    actual_files = {
        path.relative_to(skill_root).as_posix(): path
        for path in install_payload_files(skill_root)
    }
    missing = sorted(set(expected_hashes) - set(actual_files))
    unexpected = sorted(set(actual_files) - set(expected_hashes))
    if missing or unexpected:
        raise RuntimeError(
            f"installed skill payload mismatch: missing={missing} unexpected={unexpected}"
        )
    for relative, expected in expected_hashes.items():
        path = actual_files.get(str(relative))
        if path is None:
            raise RuntimeError(f"installed skill is missing {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"installed skill hash mismatch for {relative}")
    for script in (path for path in actual_files.values() if path.suffix == ".py"):
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
    if manifest.get("reuse_engine_api_version") != 2:
        raise RuntimeError("installed skill reuse-engine API must remain version 2")
    if manifest.get("architecture_governance_api_version") != 1:
        raise RuntimeError("installed skill architecture-governance API must be version 1")
    probe = """
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
import check_deps
import check_index_freshness
import check_public_api
import check_structure
import router_core
import reuse_runtime
import run_evaluation
from router_support import evaluation_policy
from router_support import import_graph
from router_support import profile_loader
from router_support import route_authorization
from router_support import structure_guardrails
assert callable(router_core.gather_reuse_report)
assert callable(router_core.gather_reuse_findings)
assert callable(router_core.gather_dependency_findings)
assert callable(router_core.gather_public_api_findings)
assert callable(router_core.freshness_report)
assert callable(router_core.evaluate_bundle)
assert reuse_runtime.FINGERPRINT_VERSION >= 1
assert callable(import_graph.build_import_graph)
assert callable(import_graph.validate_architecture_baseline)
assert callable(structure_guardrails.gather_structure_findings)
assert callable(evaluation_policy.policy_for_bundle)
assert callable(profile_loader.load_active_profile)
assert callable(route_authorization.authorization_audit_fields)
assert callable(check_deps.main)
assert callable(check_public_api.main)
assert callable(check_structure.main)
assert callable(check_index_freshness.main)
assert callable(run_evaluation.main)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(skill_root)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"installed skill API verification failed: {result.stderr.strip()}")
    return manifest


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path, onerror=handle_remove_readonly)


def _validate_install_targets(src: Path, destinations: list[Path]) -> None:
    source = src.resolve()
    resolved_destinations: set[Path] = set()
    for destination in destinations:
        resolved = destination.resolve()
        if (
            source == resolved
            or resolved.is_relative_to(source)
            or source.is_relative_to(resolved)
        ):
            raise RuntimeError(
                "skill source and destination overlap: "
                f"source={source} destination={resolved}"
            )
        if resolved in resolved_destinations:
            raise RuntimeError(f"duplicate skill install destination: {resolved}")
        overlapping = next(
            (
                existing
                for existing in sorted(resolved_destinations, key=str)
                if resolved.is_relative_to(existing)
                or existing.is_relative_to(resolved)
            ),
            None,
        )
        if overlapping is not None:
            raise RuntimeError(
                "skill install destinations overlap: "
                f"first={overlapping} second={resolved}"
            )
        resolved_destinations.add(resolved)
    install_manifest(src)


def _prepare_install(src: Path, dst: Path) -> PreparedInstall:
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(
        tempfile.mkdtemp(
            prefix=f".{SKILL_NAME}-staging-",
            dir=str(dst.parent),
        )
    )
    staged = staging_parent / SKILL_NAME
    backup = dst.parent / f".{SKILL_NAME}-backup-{uuid.uuid4().hex}"
    try:
        shutil.copytree(src, staged, ignore=INSTALL_IGNORE, symlinks=True)
        manifest = install_manifest(staged)
        (staged / INSTALL_MANIFEST).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        verify_skill_install(staged)
    except BaseException:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, onerror=handle_remove_readonly)
        raise
    return PreparedInstall(
        destination=dst,
        staging_parent=staging_parent,
        staged=staged,
        backup=backup,
        had_destination=_path_exists(dst),
        manifest=manifest,
    )


def _rollback_install(prepared: PreparedInstall) -> None:
    if _path_exists(prepared.backup):
        _remove_path(prepared.destination)
        os.replace(prepared.backup, prepared.destination)
    elif not prepared.had_destination:
        _remove_path(prepared.destination)


def atomic_install_targets(
    src: Path,
    destinations: list[Path],
) -> list[tuple[Path, dict[str, object]]]:
    if not destinations:
        return []
    _validate_install_targets(src, destinations)
    prepared_installs: list[PreparedInstall] = []
    try:
        for destination in destinations:
            prepared_installs.append(_prepare_install(src, destination))
        try:
            for prepared in prepared_installs:
                if prepared.had_destination:
                    os.replace(prepared.destination, prepared.backup)
                os.replace(prepared.staged, prepared.destination)
                verify_skill_install(prepared.destination)
        except BaseException:
            rollback_errors = []
            for prepared in reversed(prepared_installs):
                try:
                    _rollback_install(prepared)
                except BaseException as error:
                    rollback_errors.append(
                        f"{prepared.destination}: {error}"
                    )
            if rollback_errors:
                raise RuntimeError(
                    "skill install failed and rollback was incomplete: "
                    + "; ".join(rollback_errors)
                )
            raise
        for prepared in prepared_installs:
            _remove_path(prepared.backup)
        return [
            (prepared.destination, prepared.manifest)
            for prepared in prepared_installs
        ]
    finally:
        for prepared in prepared_installs:
            if prepared.staging_parent.exists():
                shutil.rmtree(
                    prepared.staging_parent,
                    onerror=handle_remove_readonly,
                )


def atomic_install_skill(src: Path, dst: Path) -> dict[str, object]:
    return atomic_install_targets(src, [dst])[0][1]


def ensure_marked_block(path: Path, marker_name: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    begin = f"<!-- {marker_name}:begin -->"
    end = f"<!-- {marker_name}:end -->"
    block = f"{begin}\n{body.strip()}\n{end}"
    pattern = re.compile(
        rf"(?ms)^\s*{re.escape(begin)}.*?{re.escape(end)}\s*$"
    )
    if pattern.search(content):
        content = pattern.sub(block, content)
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        content += ("\n" if content else "") + block + "\n"
    path.write_text(content, encoding="utf-8")


def claude_hint_block() -> str:
    return f"""
## Claude Code Skill Hint: {SKILL_NAME}

When a request involves feature-level create, modify, delete, migration, reuse, extraction, or architecture-sensitive placement, explicitly invoke:

`/{SKILL_NAME}`

Use it as a direction index and guardrail system, not as an automatic architecture decision engine.

Mandatory: respect capability ownership, canonical roots, `must_read_before_edit`, `allowed_write_paths`, `forbidden_write_paths`, veto signals, lifecycle review requirements, and duplicate-implementation warnings before writing product code.

Advisory: treat `action`, `recommended_next_steps`, `analysis_directions`, `safe_next_steps`, and `why_not_actions` as structured unblock guidance. They inform source-code analysis and user-confirmed engineering decisions; they do not replace them.

For `check_reuse`, inspect both `result_status` and `completion_status`. `bounded`, `incomplete`, `timeout`, `cancelled`, or `error` means the scan did not prove that duplicate implementations are absent; use its scoped candidates for targeted analysis.
"""


def codex_hint_block() -> str:
    return f"""
## Skill Hint: {SKILL_NAME}

When a request involves feature-level create, modify, delete, migration, reuse, extraction, or architecture-sensitive placement, explicitly invoke:

`$project-change-router`

Use it as a direction index and guardrail system, not as an automatic architecture decision engine.

Mandatory: respect capability ownership, canonical roots, `must_read_before_edit`, `allowed_write_paths`, `forbidden_write_paths`, veto signals, lifecycle review requirements, and duplicate-implementation warnings before writing product code.

Advisory: treat `action`, `recommended_next_steps`, `analysis_directions`, `safe_next_steps`, and `why_not_actions` as structured unblock guidance. They inform source-code analysis and user-confirmed engineering decisions; they do not replace them.

For `check_reuse`, inspect both `result_status` and `completion_status`. `bounded`, `incomplete`, `timeout`, `cancelled`, or `error` means the scan did not prove that duplicate implementations are absent; use its scoped candidates for targeted analysis.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the project-change-router skill for Codex and/or Claude Code.")
    parser.add_argument("--target", choices=["codex", "claude", "both"], default="both")
    parser.add_argument("--codex-home", help="Override Codex home directory. Defaults to ~/.codex")
    parser.add_argument("--claude-home", help="Override Claude home directory. Defaults to ~/.claude")
    parser.add_argument("--inject-claude-hint", action="store_true", help="Append a guidance block to CLAUDE.md in the Claude home directory.")
    parser.add_argument("--inject-codex-hint", action="store_true", help="Append a guidance block to AGENTS.md in the Codex home directory.")
    parser.add_argument("--inject-hints", action="store_true", help="Append guidance blocks to both Codex and Claude homes when those targets are installed.")
    parser.add_argument("--verify-only", action="store_true", help="Verify the installed payload and public governance APIs without replacing the skill.")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else (Path.home() / ".codex")
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else (Path.home() / ".claude")

    destinations: list[Path] = []
    if args.target in {"codex", "both"}:
        destinations.append(codex_home / "skills" / SKILL_NAME)
    if args.target in {"claude", "both"}:
        destinations.append(claude_home / "skills" / SKILL_NAME)

    if args.verify_only:
        installed_paths = [
            (destination, verify_skill_install(destination))
            for destination in destinations
        ]
    else:
        installed_paths = atomic_install_targets(skill_root, destinations)

    if not args.verify_only and args.target in {"claude", "both"} and (
        args.inject_claude_hint or args.inject_hints
    ):
        ensure_marked_block(
            claude_home / "CLAUDE.md",
            f"{SKILL_NAME}-claude-hint",
            claude_hint_block(),
        )

    if not args.verify_only and args.target in {"codex", "both"} and (args.inject_codex_hint or args.inject_hints):
        ensure_marked_block(codex_home / "AGENTS.md", f"{SKILL_NAME}-codex-hint", codex_hint_block())

    for path, manifest in installed_paths:
        action = "verified" if args.verify_only else "installed"
        print(
            f"{action}={path} version={manifest.get('skill_version')} "
            f"reuse_api={manifest.get('reuse_engine_api_version')} "
            f"architecture_api={manifest.get('architecture_governance_api_version')}"
        )
    print("repository_bundles_modified=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
