from __future__ import annotations

import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def _module(
    *,
    module_id: str,
    path: str,
    layer: str,
    import_name: str,
) -> router_core.ModuleEntry:
    return router_core.ModuleEntry(
        id=module_id,
        path=path,
        layer=layer,
        domain="memory-core",
        purpose=module_id,
        lifecycle={"import_names": [import_name]},
    )


def test_absolute_import_prefers_the_most_specific_file_module(tmp_path: Path) -> None:
    source_file = tmp_path / "app" / "api" / "routes" / "memory.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("", encoding="utf-8")
    parent = _module(
        module_id="module-memory",
        path="app/services/memory",
        layer="domain-service",
        import_name="app.services.memory",
    )
    wiring = _module(
        module_id="module-memory-postgres-wiring",
        path="app/services/memory/postgres_wiring.py",
        layer="adapter",
        import_name="app.services.memory.postgres_wiring",
    )
    source = router_core.ModuleEntry(
        id="module-api",
        path="app/api",
        layer="adapter",
        domain="api-facade",
        purpose="API",
    )

    target, _ = router_core.infer_import_reference(
        "app.services.memory.postgres_wiring",
        source,
        [parent, wiring, source],
        tmp_path,
        source_file,
    )

    assert target is wiring


def test_relative_import_resolves_the_specific_sibling_file_module(tmp_path: Path) -> None:
    source_file = tmp_path / "app" / "services" / "memory" / "persistence.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("from .core import SharedMemoryAPIFacade\n", encoding="utf-8")
    parent = _module(
        module_id="module-memory",
        path="app/services/memory",
        layer="domain-service",
        import_name="app.services.memory",
    )
    core = _module(
        module_id="module-memory-core",
        path="app/services/memory/core.py",
        layer="shared-capability",
        import_name="app.services.memory.core",
    )
    (source_file.parent / "core.py").write_text("", encoding="utf-8")

    target, resolved_path = router_core.infer_import_reference(
        ".core",
        parent,
        [parent, core],
        tmp_path,
        source_file,
    )

    assert target is core
    assert resolved_path == "app/services/memory/core.py"
