from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


@pytest.mark.parametrize(
    "request_text",
    [
        "Mark _LegacySkillExecutionLogFacadeAdapter deprecated after callers migrate.",
        (
            "Deprecate the child compatibility adapter while the "
            "rebuild-governance capability remains stable."
        ),
        (
            "Keep the shared-agent-runtime capability stable while marking the "
            "legacy resolver deprecated."
        ),
        "弃用兼容适配器，但 rebuild-governance 能力保持稳定。",
    ],
)
def test_child_lifecycle_does_not_target_owner_capability(request_text: str) -> None:
    assert router_core.request_lifecycle_intent(request_text) is None


@pytest.mark.parametrize(
    ("request_text", "target"),
    [
        (
            "Deprecate the existing payment-core capability and replace it.",
            "payment-core",
        ),
        ("Deprecate capability payment-core after caller migration.", "payment-core"),
        ("Mark payment-core capability as deprecated.", "payment-core"),
        ("弃用 payment-core 能力并迁移调用方。", "payment-core"),
    ],
)
def test_explicit_capability_deprecation_preserves_target(
    request_text: str,
    target: str,
) -> None:
    assert router_core.request_lifecycle_intent(request_text) == "deprecate"
    action = router_core.build_capability_lifecycle_action(
        request_text,
        "review",
        SimpleNamespace(id="rebuild-governance"),
    )
    assert action["target_capability"] == target
