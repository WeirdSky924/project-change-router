from __future__ import annotations

from router_support.reuse_channels import (
    comparison_channels,
    plan_reuse_channels,
    summarize_channel_coverage,
)


CAPABILITIES = [
    {
        "id": "workflow",
        "owner_modules": ["app/workflow"],
        "public_entries": ["app/workflow/api.py"],
        "lifecycle": {"canonical_root": {"path": "app/workflow"}},
    },
    {
        "id": "workflow-shared",
        "owner_modules": ["app/shared"],
        "public_entries": ["app/shared/workflow.py"],
        "lifecycle": {"canonical_root": {"path": "app/shared"}},
    },
    {
        "id": "reports",
        "owner_modules": ["app/reports"],
        "public_entries": ["app/reports/api.py"],
        "lifecycle": {"canonical_root": {"path": "app/reports"}},
    },
]


def test_channel_plan_keeps_direct_and_dependency_coverage_separate() -> None:
    plan = plan_reuse_channels(
        scope={
            "direct_capability_ids": ["workflow"],
            "dependency_capability_ids": ["workflow-shared"],
            "completion_status": "complete",
        },
        capabilities=CAPABILITIES,
        action="extend",
        lifecycle_intent=False,
    )

    assert plan["intra_capability"]["capability_ids"] == ["workflow"]
    assert plan["cross_capability"]["capability_ids"] == [
        "workflow",
        "workflow-shared",
    ]
    assert plan["extended"]["required"] is False


def test_new_and_extract_require_repository_capability_extension_channel() -> None:
    for action in ("new", "extract"):
        plan = plan_reuse_channels(
            scope={
                "direct_capability_ids": ["workflow"],
                "dependency_capability_ids": [],
                "completion_status": "complete",
            },
            capabilities=CAPABILITIES,
            action=action,
            lifecycle_intent=False,
        )

        assert plan["extended"]["required"] is True
        assert plan["extended"]["capability_ids"] == [
            "reports",
            "workflow-shared",
        ]


def test_bounded_channel_never_summarizes_as_no_duplicates() -> None:
    summary = summarize_channel_coverage(
        {
            "intra_capability": {
                "completion_status": "complete",
                "finding_count": 0,
            },
            "cross_capability": {
                "completion_status": "bounded",
                "finding_count": 0,
            },
            "extended": {
                "completion_status": "not_required",
                "finding_count": 0,
            },
        }
    )

    assert summary["evidence_complete"] is False
    assert summary["duplicate_conclusion"] == "not_proven"


def test_comparison_channel_is_derived_from_the_actual_pair() -> None:
    plan = plan_reuse_channels(
        scope={
            "direct_capability_ids": ["workflow"],
            "dependency_capability_ids": ["workflow-shared"],
            "completion_status": "complete",
        },
        capabilities=CAPABILITIES,
        action="new",
        lifecycle_intent=False,
    )

    assert comparison_channels(
        owner_capability_id="workflow",
        candidate_capability_ids=["workflow"],
        channels=plan,
    ) == ["intra_capability"]
    assert comparison_channels(
        owner_capability_id="workflow-shared",
        candidate_capability_ids=["workflow"],
        channels=plan,
    ) == ["cross_capability"]
    assert comparison_channels(
        owner_capability_id="reports",
        candidate_capability_ids=["workflow"],
        channels=plan,
    ) == ["extended"]
