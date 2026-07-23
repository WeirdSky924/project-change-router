from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]
INSTALL_MANIFEST = ".installation-manifest.json"
IGNORED_PAYLOAD_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "project-change-router",
    INSTALL_MANIFEST,
}

sys.path.insert(0, str(SKILL_ROOT / "scripts"))
import install_skill


def _run_installer(
    source_root: Path,
    codex_home: Path,
    *extra: str,
    target: str = "codex",
    claude_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(source_root / "scripts" / "install_skill.py"),
        "--target",
        target,
        "--codex-home",
        str(codex_home),
    ]
    if claude_home is not None:
        command.extend(("--claude-home", str(claude_home)))
    command.extend(extra)
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def _copy_skill_source(tmp_path: Path) -> Path:
    copied = tmp_path / "skill-source"
    shutil.copytree(
        SKILL_ROOT,
        copied,
        ignore=shutil.ignore_patterns(*IGNORED_PAYLOAD_NAMES),
    )
    return copied


def _payload_files(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED_PAYLOAD_NAMES for part in path.relative_to(root).parts)
    }


def test_v030_release_metadata_preserves_reuse_api_and_versions_architecture_api() -> None:
    version = json.loads((SKILL_ROOT / "skill-version.json").read_text(encoding="utf-8"))
    project = tomllib.loads((SKILL_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert version["skill_version"] == "0.3.0"
    assert project["project"]["version"] == "0.3.0"
    assert version["reuse_engine_api_version"] == 2
    assert version["architecture_governance_api_version"] == 1


def test_atomic_install_manifest_hashes_the_complete_payload(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    result = _run_installer(SKILL_ROOT, codex_home)

    assert result.returncode == 0, result.stderr
    installed = codex_home / "skills" / "project-change-router"
    manifest = json.loads((installed / INSTALL_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["manifest_schema_version"] == 2
    assert manifest["architecture_governance_api_version"] == 1
    assert set(manifest["files"]) == _payload_files(installed)
    assert "scripts/router_support/import_graph.py" in manifest["files"]
    assert "scripts/router_support/repository_surfaces.py" in manifest["files"]
    assert "scripts/router_support/structure_guardrails.py" in manifest["files"]
    assert "schemas/router-config.schema.json" in manifest["files"]


def test_verify_only_detects_nested_support_module_tampering(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    install = _run_installer(SKILL_ROOT, codex_home)
    assert install.returncode == 0, install.stderr
    support = codex_home / "skills" / "project-change-router" / "scripts" / "router_support" / "import_graph.py"
    support.write_text(support.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")

    verify = _run_installer(SKILL_ROOT, codex_home, "--verify-only")

    assert verify.returncode != 0
    assert "hash mismatch" in verify.stderr


def test_installed_repository_surface_helper_is_importable(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    install = _run_installer(SKILL_ROOT, codex_home)
    assert install.returncode == 0, install.stderr
    installed = codex_home / "skills" / "project-change-router"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(installed / 'scripts')!r}); "
                "from router_support import repository_surfaces; "
                "assert callable("
                "repository_surfaces.discover_standard_repository_surfaces)"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_verify_only_rejects_legacy_install_without_manifest(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    installed = codex_home / "skills" / "project-change-router"
    shutil.copytree(
        SKILL_ROOT,
        installed,
        ignore=shutil.ignore_patterns(*IGNORED_PAYLOAD_NAMES),
    )

    verify = _run_installer(SKILL_ROOT, codex_home, "--verify-only")

    assert verify.returncode != 0
    assert "installation manifest is missing" in verify.stderr


def test_verify_only_rejects_legacy_schema_manifest_as_reinstall_required(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install = _run_installer(SKILL_ROOT, codex_home)
    assert install.returncode == 0, install.stderr
    installed = codex_home / "skills" / "project-change-router"
    manifest_path = installed / INSTALL_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["manifest_schema_version"] = 1
    manifest["files"] = {"SKILL.md": manifest["files"]["SKILL.md"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    verify = _run_installer(SKILL_ROOT, codex_home, "--verify-only")

    assert verify.returncode != 0
    assert "manifest schema 1" in verify.stderr
    assert "reinstall required" in verify.stderr


def test_verify_only_rejects_v030_manifest_downgrade_and_subset_bypass(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    install = _run_installer(SKILL_ROOT, codex_home)
    assert install.returncode == 0, install.stderr
    installed = codex_home / "skills" / "project-change-router"
    manifest_path = installed / INSTALL_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["skill_version"] == "0.3.0"
    assert manifest["architecture_governance_api_version"] == 1
    manifest["manifest_schema_version"] = 1
    manifest["files"] = {"SKILL.md": manifest["files"]["SKILL.md"]}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    unlisted = installed / "references" / "evaluation.md"
    unlisted.write_text(
        unlisted.read_text(encoding="utf-8") + "\nTampered outside subset.\n",
        encoding="utf-8",
    )

    verify = _run_installer(SKILL_ROOT, codex_home, "--verify-only")

    assert verify.returncode != 0
    assert "manifest schema 1" in verify.stderr
    assert "reinstall required" in verify.stderr


def test_atomic_install_rejects_invalid_nested_python_and_restores_old_install(tmp_path: Path) -> None:
    source = _copy_skill_source(tmp_path)
    invalid = source / "scripts" / "router_support" / "invalid_payload.py"
    invalid.write_text("def invalid syntax\n", encoding="utf-8")
    codex_home = tmp_path / "codex-home"
    old_install = codex_home / "skills" / "project-change-router"
    old_install.mkdir(parents=True)
    marker = old_install / "old-install.txt"
    marker.write_text("preserve me\n", encoding="utf-8")

    result = _run_installer(source, codex_home)

    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8") == "preserve me\n"


def test_both_targets_prepare_before_replacing_codex_install(tmp_path: Path) -> None:
    source = _copy_skill_source(tmp_path)
    codex_home = tmp_path / "codex-home"
    codex_install = codex_home / "skills" / "project-change-router"
    codex_install.mkdir(parents=True)
    codex_marker = codex_install / "old-codex.txt"
    codex_marker.write_text("preserve codex\n", encoding="utf-8")
    claude_home = tmp_path / "claude-home"
    claude_home.mkdir()
    (claude_home / "skills").write_text(
        "not a directory\n",
        encoding="utf-8",
    )

    result = _run_installer(
        source,
        codex_home,
        target="both",
        claude_home=claude_home,
    )

    assert result.returncode != 0
    assert codex_marker.read_text(encoding="utf-8") == "preserve codex\n"
    assert not (codex_install / INSTALL_MANIFEST).exists()
    assert not list(codex_install.parent.glob(".project-change-router-*-*"))


def test_both_targets_roll_back_when_second_replacement_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_skill_source(tmp_path)
    codex_install = tmp_path / "codex-home" / "skills" / "project-change-router"
    claude_install = tmp_path / "claude-home" / "skills" / "project-change-router"
    codex_install.mkdir(parents=True)
    claude_install.mkdir(parents=True)
    codex_marker = codex_install / "old-codex.txt"
    claude_marker = claude_install / "old-claude.txt"
    codex_marker.write_text("preserve codex\n", encoding="utf-8")
    claude_marker.write_text("preserve claude\n", encoding="utf-8")
    real_replace = install_skill.os.replace
    injected = False

    def fail_second_staged_replace(source_path: object, target_path: object) -> None:
        nonlocal injected
        source_candidate = Path(source_path)
        if (
            not injected
            and Path(target_path) == claude_install
            and source_candidate.name == install_skill.SKILL_NAME
            and "-staging-" in source_candidate.parent.name
        ):
            injected = True
            raise OSError("injected second replacement failure")
        real_replace(source_path, target_path)

    monkeypatch.setattr(install_skill.os, "replace", fail_second_staged_replace)

    with pytest.raises(OSError, match="injected second replacement failure"):
        install_skill.atomic_install_targets(
            source,
            [codex_install, claude_install],
        )

    assert injected is True
    assert codex_marker.read_text(encoding="utf-8") == "preserve codex\n"
    assert claude_marker.read_text(encoding="utf-8") == "preserve claude\n"
    assert not (codex_install / INSTALL_MANIFEST).exists()
    assert not (claude_install / INSTALL_MANIFEST).exists()
    assert not list(codex_install.parent.glob(".project-change-router-*-*"))
    assert not list(claude_install.parent.glob(".project-change-router-*-*"))


def test_both_targets_do_not_replace_when_second_staging_validation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_skill_source(tmp_path)
    codex_install = tmp_path / "codex-home" / "skills" / "project-change-router"
    claude_install = tmp_path / "claude-home" / "skills" / "project-change-router"
    codex_install.mkdir(parents=True)
    claude_install.mkdir(parents=True)
    codex_marker = codex_install / "old-codex.txt"
    claude_marker = claude_install / "old-claude.txt"
    codex_marker.write_text("preserve codex\n", encoding="utf-8")
    claude_marker.write_text("preserve claude\n", encoding="utf-8")
    real_verify = install_skill.verify_skill_install
    injected = False

    def fail_claude_staging_validation(skill_root: Path) -> dict[str, object]:
        nonlocal injected
        if (
            claude_install.parent in skill_root.parents
            and "-staging-" in skill_root.parent.name
        ):
            injected = True
            raise RuntimeError("injected Claude staging validation failure")
        return real_verify(skill_root)

    monkeypatch.setattr(
        install_skill,
        "verify_skill_install",
        fail_claude_staging_validation,
    )

    with pytest.raises(RuntimeError, match="staging validation failure"):
        install_skill.atomic_install_targets(
            source,
            [codex_install, claude_install],
        )

    assert injected is True
    assert codex_marker.read_text(encoding="utf-8") == "preserve codex\n"
    assert claude_marker.read_text(encoding="utf-8") == "preserve claude\n"
    assert not list(codex_install.parent.glob(".project-change-router-*-*"))
    assert not list(claude_install.parent.glob(".project-change-router-*-*"))


def test_both_target_success_installs_both_and_reports_no_bundle_writes(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    claude_home = tmp_path / "claude-home"

    result = _run_installer(
        SKILL_ROOT,
        codex_home,
        target="both",
        claude_home=claude_home,
    )

    assert result.returncode == 0, result.stderr
    for home in (codex_home, claude_home):
        installed = home / "skills" / "project-change-router"
        assert (installed / INSTALL_MANIFEST).is_file()
    assert result.stdout.count("installed=") == 2
    assert "repository_bundles_modified=0" in result.stdout


@pytest.mark.parametrize("target_location", ("inside", "outside"))
def test_atomic_install_rejects_source_payload_symlinks_before_replacement(
    tmp_path: Path,
    target_location: str,
) -> None:
    source = _copy_skill_source(tmp_path)
    references = source / "references"
    if target_location == "inside":
        target = references / "symlink-target.txt"
        target.write_text("internal payload\n", encoding="utf-8")
        link_target = Path("symlink-target.txt")
    else:
        target = tmp_path / "outside-secret.txt"
        target.write_text("external payload\n", encoding="utf-8")
        link_target = target
    (references / "linked-payload.txt").symlink_to(link_target)
    codex_home = tmp_path / "codex-home"
    old_install = codex_home / "skills" / "project-change-router"
    old_install.mkdir(parents=True)
    marker = old_install / "old-install.txt"
    marker.write_text("preserve me\n", encoding="utf-8")

    result = _run_installer(source, codex_home)

    assert result.returncode != 0
    assert "symlink" in result.stderr.lower()
    assert marker.read_text(encoding="utf-8") == "preserve me\n"
    assert not (old_install / "references" / "linked-payload.txt").exists()


def test_atomic_install_rejects_source_equal_to_destination(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    source = codex_home / "skills" / "project-change-router"
    shutil.copytree(
        SKILL_ROOT,
        source,
        ignore=shutil.ignore_patterns(*IGNORED_PAYLOAD_NAMES),
    )
    git_marker = source / ".git" / "HEAD"
    git_marker.parent.mkdir()
    git_marker.write_text("ref: refs/heads/main\n", encoding="utf-8")

    result = _run_installer(source, codex_home)

    assert result.returncode != 0
    assert "source and destination" in result.stderr
    assert git_marker.read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert not (source / INSTALL_MANIFEST).exists()


@pytest.mark.parametrize(
    "relationship",
    ("destination_inside_source", "source_inside_destination"),
)
def test_install_validation_rejects_nested_source_destination_overlap(
    tmp_path: Path,
    relationship: str,
) -> None:
    source = _copy_skill_source(tmp_path)
    destination = (
        source / "nested-home" / "skills" / "project-change-router"
        if relationship == "destination_inside_source"
        else source.parent
    )

    with pytest.raises(RuntimeError, match="source and destination overlap"):
        install_skill._validate_install_targets(source, [destination])


@pytest.mark.parametrize("reverse", (False, True))
def test_install_validation_rejects_overlapping_destination_pair(
    tmp_path: Path,
    reverse: bool,
) -> None:
    source = _copy_skill_source(tmp_path)
    ancestor = tmp_path / "install-home" / "skills" / "project-change-router"
    descendant = ancestor / "nested-home" / "skills" / "project-change-router"
    destinations = [descendant, ancestor] if reverse else [ancestor, descendant]

    with pytest.raises(RuntimeError, match="install destinations overlap") as exc_info:
        install_skill._validate_install_targets(source, destinations)

    message = str(exc_info.value)
    assert str(ancestor.resolve()) in message
    assert str(descendant.resolve()) in message


def test_atomic_install_probes_architecture_governance_api(tmp_path: Path) -> None:
    source = _copy_skill_source(tmp_path)
    guardrails = source / "scripts" / "router_support" / "structure_guardrails.py"
    content = guardrails.read_text(encoding="utf-8")
    assert "def gather_structure_findings(" in content
    guardrails.write_text(
        content.replace("def gather_structure_findings(", "def removed_gather_structure_findings(", 1),
        encoding="utf-8",
    )
    codex_home = tmp_path / "codex-home"
    old_install = codex_home / "skills" / "project-change-router"
    old_install.mkdir(parents=True)
    marker = old_install / "old-install.txt"
    marker.write_text("preserve me\n", encoding="utf-8")

    result = _run_installer(source, codex_home)

    assert result.returncode != 0
    assert "API verification failed" in result.stderr
    assert marker.read_text(encoding="utf-8") == "preserve me\n"


def test_ci_smoke_runs_all_architecture_guardrail_clis() -> None:
    workflow = (SKILL_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "python scripts/check_deps.py --repo . --format json" in workflow
    assert "python scripts/check_public_api.py --repo . --format json" in workflow
    assert "python scripts/check_structure.py --repo . --format json" in workflow
    assert '"--strict-completeness",' in workflow
    assert 'assert report["completion_status"] == "complete"' in workflow
    assert 'assert report["evidence_complete"] is True' in workflow
    assert '"scripts/router_support/owner_identity.py",' in workflow
