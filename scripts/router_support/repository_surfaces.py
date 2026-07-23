from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


STANDARD_REPOSITORY_SURFACE_DIRECTORIES = (
    ".github/workflows",
    ".github/actions",
    ".circleci",
    ".buildkite",
)
STANDARD_REPOSITORY_SURFACE_FILES = (
    ".gitlab-ci.yml",
    "azure-pipelines.yml",
    "bitbucket-pipelines.yml",
    "Jenkinsfile",
)


@dataclass(frozen=True)
class RepositorySurface:
    path: str
    kind: str
    purpose: str
    key_files: tuple[str, ...]


def _normalized(path: str) -> str:
    return path.replace("\\", "/").removeprefix("./").strip("/")


def standard_repository_surface_kind(path: str) -> str | None:
    normalized = _normalized(path)
    if normalized in STANDARD_REPOSITORY_SURFACE_DIRECTORIES:
        return "directory"
    if normalized in STANDARD_REPOSITORY_SURFACE_FILES:
        return "file"
    return None


def is_standard_repository_surface_file(path: str) -> bool:
    return standard_repository_surface_kind(path) == "file"


def is_within_standard_repository_surface(path: str) -> bool:
    normalized = _normalized(path)
    if normalized in STANDARD_REPOSITORY_SURFACE_FILES:
        return True
    return any(
        normalized == root or normalized.startswith(root + "/")
        for root in STANDARD_REPOSITORY_SURFACE_DIRECTORIES
    )


def files_for_standard_repository_surface(
    repo_root: Path,
    relative: str,
    is_ignored: Callable[[Path], bool] | None = None,
) -> tuple[Path, ...]:
    ignored = is_ignored or (lambda _path: False)
    root = repo_root / relative
    kind = standard_repository_surface_kind(relative)
    if not kind or ignored(root):
        return ()
    if kind == "file":
        return (root,) if root.is_file() else ()
    if not root.is_dir():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not ignored(path)
    )


def discover_standard_repository_surfaces(
    repo_root: Path,
    is_ignored: Callable[[Path], bool] | None = None,
) -> tuple[RepositorySurface, ...]:
    ignored = is_ignored or (lambda _path: False)
    surfaces: list[RepositorySurface] = []
    for relative in STANDARD_REPOSITORY_SURFACE_DIRECTORIES:
        root = repo_root / relative
        if not root.is_dir() or ignored(root):
            continue
        surfaces.append(
            RepositorySurface(
                path=relative,
                kind="directory",
                purpose=f"Standard CI repository surface at {relative}",
                key_files=tuple(
                    path.relative_to(root).as_posix()
                    for path in files_for_standard_repository_surface(
                        repo_root,
                        relative,
                        ignored,
                    )[:6]
                ),
            )
        )
    for relative in STANDARD_REPOSITORY_SURFACE_FILES:
        root = repo_root / relative
        if not root.is_file() or ignored(root):
            continue
        surfaces.append(
            RepositorySurface(
                path=relative,
                kind="file",
                purpose=f"Standard CI repository surface at {relative}",
                key_files=(root.name,),
            )
        )
    return tuple(surfaces)


def overlay_standard_repository_surface_records(
    records: Iterable[Mapping[str, Any]],
    surfaces: Iterable[RepositorySurface],
    allowed_outbound_layers: Iterable[str],
) -> tuple[dict[str, Any], ...]:
    by_path = {str(record["path"]): dict(record) for record in records}
    outbound_layers = list(allowed_outbound_layers)
    for surface in surfaces:
        existing = by_path.get(surface.path, {})
        lifecycle = dict(existing.get("lifecycle", {}))
        lifecycle.update(
            {
                "discovery_strategy": "standard-repository-surface",
                "repository_surface_kind": surface.kind,
                "allowed_outbound_layers": outbound_layers,
            }
        )
        lifecycle.setdefault("language", "generic")
        lifecycle.setdefault("source_roots", ["."])
        lifecycle.setdefault("import_names", [])
        by_path[surface.path] = {
            "id": "module-" + _slug(surface.path),
            "path": surface.path,
            "layer": "infra",
            "domain": "development-infrastructure",
            "purpose": surface.purpose,
            "public_api": existing.get("public_api"),
            "source_of_truth": "generated",
            "key_files": list(
                dict.fromkeys(
                    [*surface.key_files, *existing.get("key_files", [])]
                )
            ),
            "depends_on": list(existing.get("depends_on", [])),
            "allowed_inbound_from": list(
                existing.get("allowed_inbound_from", [])
            ),
            "allowed_outbound_to": list(
                existing.get("allowed_outbound_to", [])
            ),
            "generated": True,
            "index_sources": list(
                dict.fromkeys(
                    [
                        "standard-repository-surface",
                        *existing.get("index_sources", []),
                    ]
                )
            ),
            "owner": "unassigned",
            "status": str(existing.get("status", "active")),
            "lifecycle": lifecycle,
        }
    return tuple(
        sorted(
            by_path.values(),
            key=lambda item: (str(item["path"]).count("/"), str(item["path"])),
        )
    )


def _slug(value: str) -> str:
    normalized = "-".join(
        part for part in value.lower().replace("_", "-").split("/") if part
    )
    return "".join(
        character if character.isalnum() or character == "-" else "-"
        for character in normalized
    ).strip("-") or "item"


def has_standard_repository_surface(repo_root: Path) -> bool:
    return bool(discover_standard_repository_surfaces(repo_root))


__all__ = [
    "RepositorySurface",
    "STANDARD_REPOSITORY_SURFACE_DIRECTORIES",
    "STANDARD_REPOSITORY_SURFACE_FILES",
    "discover_standard_repository_surfaces",
    "files_for_standard_repository_surface",
    "has_standard_repository_surface",
    "is_standard_repository_surface_file",
    "is_within_standard_repository_surface",
    "overlay_standard_repository_surface_records",
    "standard_repository_surface_kind",
]
