from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_non_private_cross_module_public_api_bypass_is_blocking(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _write(repo / "app/shared/__init__.py", "from .helpers import helper\n")
    _write(repo / "app/shared/helpers.py", "def helper(): return True\n")
    _write(
        repo / "app/feature/use_shared.py",
        "from app.shared.helpers import helper\n",
    )
    bundle = {
        "config": {"ignore_paths": []},
        "module_map": {
            "modules": [
                {
                    "id": "module-shared",
                    "path": "app/shared",
                    "layer": "shared-capability",
                    "domain": "shared",
                    "purpose": "Shared API",
                    "public_api": "__init__.py",
                },
                {
                    "id": "module-feature",
                    "path": "app/feature",
                    "layer": "domain-service",
                    "domain": "feature",
                    "purpose": "Feature",
                    "depends_on": ["app/shared"],
                },
            ]
        },
        "change_rules": {"architecture_baseline": []},
    }

    findings = router_core.gather_public_api_findings(repo, bundle)

    bypass = next(item for item in findings if item["rule"] == "public-api-bypass")
    assert bypass["source"] == "app/feature/use_shared.py"
    assert bypass["target"] == "app/shared/helpers.py"
    assert bypass["severity"] == "P1"
    assert bypass["blocking"] is True
