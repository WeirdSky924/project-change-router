from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core
from router_support.architecture_baseline import finding_fingerprint


@pytest.mark.parametrize(
    ("collector", "identity"),
    (
        (
            router_core.gather_dependency_findings,
            {"rule": "dependency-direction", "source": "app/a", "target": "app/b"},
        ),
        (
            router_core.gather_public_api_findings,
            {
                "rule": "public-api-bypass",
                "source": "app/a",
                "target": "app/b/private.py",
                "import": "app.b.private",
            },
        ),
    ),
)
def test_product_guard_reports_orphaned_architecture_baseline(
    tmp_path: Path,
    collector: Callable[[Path, dict[str, object]], list[dict[str, object]]],
    identity: dict[str, object],
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    baseline = {
        "id": f"baseline-{identity['rule']}",
        **identity,
        "owner": "architecture-maintainers",
        "exit_stage": "G1",
        "fingerprint": finding_fingerprint(identity),
    }
    bundle: dict[str, object] = {
        "config": {},
        "module_map": {"modules": []},
        "capability_catalog": {"capabilities": []},
        "change_rules": {"architecture_baseline": [baseline]},
    }

    findings = collector(repo, bundle)

    diagnostic = next(
        finding
        for finding in findings
        if finding["rule"] == "architecture-baseline-diagnostic"
    )
    assert diagnostic["diagnostic_code"] == "baseline_orphan"
    assert diagnostic["blocking"] is True
