#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
from pathlib import Path


SKILL_NAME = "project-change-router"


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, onerror=handle_remove_readonly)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "project-change-router"),
    )


def handle_remove_readonly(func, path, _exc_info) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


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
## Codex Skill Hint: {SKILL_NAME}

When a request involves deciding whether a repository change should reuse, extend, extract, introduce, or stop for review before editing code, explicitly invoke:

`/{SKILL_NAME}`

Prefer this for large repositories, architecture-sensitive changes, and any request that would benefit from repository-local routing, capability boundary checks, or guardrail validation.
"""


def codex_hint_block() -> str:
    return f"""
## Skill Hint: {SKILL_NAME}

When a request involves deciding whether a repository change should reuse, extend, extract, introduce, or stop for review before editing code, explicitly invoke:

`$project-change-router`

Prefer this for large repositories, architecture-sensitive changes, and any request that would benefit from repository-local routing, capability boundary checks, or guardrail validation.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the project-change-router skill for Codex and/or Claude Code.")
    parser.add_argument("--target", choices=["codex", "claude", "both"], default="both")
    parser.add_argument("--codex-home", help="Override Codex home directory. Defaults to ~/.codex")
    parser.add_argument("--claude-home", help="Override Claude home directory. Defaults to ~/.claude")
    parser.add_argument("--inject-claude-hint", action="store_true", help="Append a guidance block to CLAUDE.md in the Claude home directory.")
    parser.add_argument("--inject-codex-hint", action="store_true", help="Append a guidance block to AGENTS.md in the Codex home directory.")
    parser.add_argument("--inject-hints", action="store_true", help="Append guidance blocks to both Codex and Claude homes when those targets are installed.")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    codex_home = Path(args.codex_home).expanduser() if args.codex_home else (Path.home() / ".codex")
    claude_home = Path(args.claude_home).expanduser() if args.claude_home else (Path.home() / ".claude")

    installed_paths: list[Path] = []
    if args.target in {"codex", "both"}:
        codex_dst = codex_home / "skills" / SKILL_NAME
        copy_tree(skill_root, codex_dst)
        installed_paths.append(codex_dst)
    if args.target in {"claude", "both"}:
        claude_dst = claude_home / "skills" / SKILL_NAME
        copy_tree(skill_root, claude_dst)
        installed_paths.append(claude_dst)
        if args.inject_claude_hint or args.inject_hints:
            ensure_marked_block(claude_home / "CLAUDE.md", f"{SKILL_NAME}-claude-hint", claude_hint_block())

    if args.target in {"codex", "both"} and (args.inject_codex_hint or args.inject_hints):
        ensure_marked_block(codex_home / "AGENTS.md", f"{SKILL_NAME}-codex-hint", codex_hint_block())

    for path in installed_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
