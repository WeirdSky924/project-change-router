import sys
from pathlib import Path, PurePosixPath

SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_core import (
    CapabilityEntry,
    ModuleEntry,
    build_write_constraints,
    required_read_paths,
)
from router_support.route_read_paths import module_scoped_read_path


GENERAL_REQUIRED_READS = [
    "docs/specs/data-processing.md",
    "docs/specs/reporting-pipeline.md",
    "src/catalog/repository.py",
    "src/analytics/repository.py",
    "src/infrastructure/database.py",
    "migrations/001_catalog.sql",
    "migrations/002_analytics.sql",
    "migrations/003_shared_readiness.sql",
    "src/pipelines/output_writer.py",
    "src/pipelines/context_assembly.py",
]

CATALOG_REQUIRED_READS = [
    "docs/specs/data-processing.md",
    "src/catalog/repository.py",
    "src/infrastructure/database.py",
    "src/api/application.py",
    "migrations/001_catalog.sql",
    "migrations/003_shared_readiness.sql",
    "src/pipelines/output_writer.py",
    "src/pipelines/catalog_completion.py",
    "src/pipelines/catalog_readiness.py",
]

ANALYTICS_REQUIRED_READS = [
    "docs/specs/data-processing.md",
    "src/analytics/repository.py",
    "src/infrastructure/database.py",
    "migrations/002_analytics.sql",
    "src/pipelines/output_writer.py",
    "tests/test_analytics_repository.py",
    "tests/test_analytics_schema.py",
    "tests/test_analytics_read_model.py",
]


def _multi_owner_data_capability() -> CapabilityEntry:
    return CapabilityEntry(
        id="data-processing",
        name="Data Processing",
        status="stable",
        maturity="curated",
        owner_modules=["src/catalog", "src/analytics"],
        lifecycle={
            "required_reads": GENERAL_REQUIRED_READS,
            "required_read_bindings": [
                {
                    "id": "catalog-readiness",
                    "when_changed_paths": [
                        "src/catalog/**",
                        "tests/catalog/**",
                    ],
                    "required_reads": CATALOG_REQUIRED_READS,
                },
                {
                    "id": "analytics-reporting",
                    "when_changed_paths": [
                        "src/analytics/**",
                        "tests/analytics/**",
                    ],
                    "required_reads": ANALYTICS_REQUIRED_READS,
                },
            ],
        },
    )


def test_dotted_public_api_for_file_module_keeps_python_suffix() -> None:
    assert module_scoped_read_path(
        "src/catalog/core.py",
        "src.catalog.core",
    ) == "src/catalog/core.py"


def test_dotted_public_api_for_package_entry_keeps_init_file() -> None:
    assert module_scoped_read_path(
        "src/catalog/__init__.py",
        "src.catalog",
    ) == "src/catalog/__init__.py"


def test_required_reads_do_not_prefix_already_rooted_module_paths() -> None:
    module = ModuleEntry(
        id="module-shared-runtime",
        path="src/runtime",
        layer="shared-capability",
        domain="shared-runtime",
        purpose="Operation Request lifecycle owner",
        public_api="__init__.py",
        key_files=[
            "src/runtime/context.py",
            "operation_persistence.py",
        ],
    )
    capability = CapabilityEntry(
        id="shared-runtime",
        name="Shared Runtime",
        status="stable",
        maturity="curated",
        owner_modules=[module.path],
        public_entries=["src/runtime/__init__.py"],
    )

    reads = required_read_paths(
        capability,
        [module],
        ["src/runtime/operation_persistence.py"],
    )

    assert reads == [
        "src/runtime/__init__.py",
        "src/runtime/context.py",
        "src/runtime/operation_persistence.py",
    ]
    assert all("src/runtime/src/runtime" not in path for path in reads)
    assert all(not PurePosixPath(path).is_absolute() for path in reads)


def test_required_reads_filter_prose_and_keep_file_module_sibling_paths_rooted() -> None:
    module = ModuleEntry(
        id="module-architecture-governance",
        path="docs/architecture/CANONICAL_ROOTS.md",
        layer="governance",
        domain="architecture-governance",
        purpose="Architecture governance",
        public_api="governance docs, repo plan state files, and router reference data",
        key_files=[
            "docs/architecture/CANONICAL_ROOTS.md",
            "docs/architecture/MODULE_MAP.md",
        ],
    )
    capability = CapabilityEntry(
        id="architecture-governance",
        name="Architecture Governance",
        status="stable",
        maturity="curated",
        owner_modules=[module.path],
        public_entries=[
            "docs/architecture/CANONICAL_ROOTS.md",
            "docs/architecture/CANONICAL_ROOTS.md/governance docs, repo plan state files",
        ],
    )

    reads = required_read_paths(capability, [module], [])

    assert reads == [
        "docs/architecture/CANONICAL_ROOTS.md",
        "docs/architecture/MODULE_MAP.md",
    ]


def test_planned_capability_reads_existing_predecessor_evidence() -> None:
    module = ModuleEntry(
        id="module-search-index",
        path="src/indexing",
        layer="shared-capability",
        domain="search-index",
        purpose="Planned Search Index canonical root",
        public_api="src.indexing",
        owner="search-index",
        status="planned",
    )
    capability = CapabilityEntry(
        id="search-index",
        name="Search Index",
        status="stable",
        maturity="curated",
        owner_modules=[module.path],
        public_entries=["src/indexing/__init__.py"],
        lifecycle={
            "canonical_root": {
                "symbol": "src.indexing",
                "status": "planned",
            },
            "required_reads": [
                "docs/specs/search-index.md",
                "src/legacy/index_store.py",
                "src/infrastructure/database.py",
            ],
        },
    )

    reads = required_read_paths(
        capability,
        [module],
        ["src/indexing/contracts.py"],
    )
    _, _, must_read = build_write_constraints(
        "extract",
        capability,
        ["src/indexing/contracts.py"],
        [],
        reads,
    )

    assert reads == capability.lifecycle["required_reads"]
    assert must_read == reads
    assert "src/indexing/__init__.py" not in reads


def test_catalog_binding_preserves_all_mandatory_reads_beyond_global_cap() -> None:
    reads = required_read_paths(
        _multi_owner_data_capability(),
        [],
        [r".\src\catalog\repository.py"],
    )

    assert len(CATALOG_REQUIRED_READS) == 9
    assert reads == CATALOG_REQUIRED_READS
    assert "src/analytics/repository.py" not in reads
    assert "migrations/002_analytics.sql" not in reads


def test_analytics_binding_excludes_catalog_only_reads_for_dot_prefixed_path() -> None:
    reads = required_read_paths(
        _multi_owner_data_capability(),
        [],
        ["./src/analytics/reports/repository.py"],
    )

    assert reads == ANALYTICS_REQUIRED_READS
    assert "src/catalog/repository.py" not in reads
    assert "src/api/application.py" not in reads
    assert "migrations/001_catalog.sql" not in reads
    assert "migrations/003_shared_readiness.sql" not in reads


def test_unmatched_binding_keeps_general_order_and_eight_item_cap() -> None:
    reads = required_read_paths(
        _multi_owner_data_capability(),
        [],
        ["src/other/repository.py"],
    )

    assert len(GENERAL_REQUIRED_READS) > 8
    assert reads == GENERAL_REQUIRED_READS[:8]
