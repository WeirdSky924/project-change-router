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
from pathlib import Path


SKILL_NAME = "project-change-router"


INSTALL_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "project-change-router")
INSTALL_MANIFEST = ".installation-manifest.json"


def handle_remove_readonly(func, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


def source_version(skill_root: Path) -> dict[str, object]:
    version_path = skill_root / "skill-version.json"
    if not version_path.exists():
        raise FileNotFoundError(f"missing version metadata: {version_path}")
    return json.loads(version_path.read_text(encoding="utf-8"))


def install_manifest(skill_root: Path) -> dict[str, object]:
    hashes: dict[str, str] = {}
    for relative in [
        "SKILL.md",
        "skill-version.json",
        "scripts/check_reuse.py",
        "scripts/router_core.py",
        "scripts/reuse_runtime.py",
    ]:
        path = skill_root / relative
        if not path.exists():
            raise FileNotFoundError(f"required install file missing: {path}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        **source_version(skill_root),
        "manifest_schema_version": 1,
        "files": hashes,
    }


def verify_skill_install(skill_root: Path) -> dict[str, object]:
    manifest_path = skill_root / INSTALL_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else install_manifest(skill_root)
    expected_hashes = manifest.get("files", {})
    for relative, expected in expected_hashes.items():
        path = skill_root / str(relative)
        if not path.exists():
            raise RuntimeError(f"installed skill is missing {relative}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"installed skill hash mismatch for {relative}")
    for script in (skill_root / "scripts").glob("*.py"):
        compile(script.read_text(encoding="utf-8"), str(script), "exec")
    probe = """
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'scripts'))
import router_core
import reuse_runtime
assert callable(router_core.gather_reuse_report)
assert callable(router_core.gather_reuse_findings)
assert reuse_runtime.FINGERPRINT_VERSION >= 1
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


def atomic_install_skill(src: Path, dst: Path) -> dict[str, object]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    staging_parent = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-staging-", dir=str(dst.parent)))
    staged = staging_parent / SKILL_NAME
    backup = dst.parent / f".{SKILL_NAME}-backup-{uuid.uuid4().hex}"
    try:
        shutil.copytree(src, staged, ignore=INSTALL_IGNORE)
        manifest = install_manifest(staged)
        (staged / INSTALL_MANIFEST).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        verify_skill_install(staged)
        if dst.exists():
            os.replace(dst, backup)
        try:
            os.replace(staged, dst)
            verify_skill_install(dst)
        except BaseException:
            if dst.exists():
                shutil.rmtree(dst, onerror=handle_remove_readonly)
            if backup.exists():
                os.replace(backup, dst)
            raise
        if backup.exists():
            shutil.rmtree(backup, onerror=handle_remove_readonly)
        return manifest
    finally:
        if staging_parent.exists():
            shutil.rmtree(staging_parent, onerror=handle_remove_readonly)


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
    parser.add_argument("--verify-only", action="store_true", help="Verify installed files and reuse-engine API without replacing the skill.")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else (Path.home() / ".codex")
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else (Path.home() / ".claude")

    installed_paths: list[tuple[Path, dict[str, object]]] = []
    if args.target in {"codex", "both"}:
        codex_dst = codex_home / "skills" / SKILL_NAME
        manifest = verify_skill_install(codex_dst) if args.verify_only else atomic_install_skill(skill_root, codex_dst)
        installed_paths.append((codex_dst, manifest))
    if args.target in {"claude", "both"}:
        claude_dst = claude_home / "skills" / SKILL_NAME
        manifest = verify_skill_install(claude_dst) if args.verify_only else atomic_install_skill(skill_root, claude_dst)
        installed_paths.append((claude_dst, manifest))
        if not args.verify_only and (args.inject_claude_hint or args.inject_hints):
            ensure_marked_block(claude_home / "CLAUDE.md", f"{SKILL_NAME}-claude-hint", claude_hint_block())

    if not args.verify_only and args.target in {"codex", "both"} and (args.inject_codex_hint or args.inject_hints):
        ensure_marked_block(codex_home / "AGENTS.md", f"{SKILL_NAME}-codex-hint", codex_hint_block())

    for path, manifest in installed_paths:
        action = "verified" if args.verify_only else "installed"
        print(f"{action}={path} version={manifest.get('skill_version')} reuse_api={manifest.get('reuse_engine_api_version')}")
    print("repository_bundles_modified=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
