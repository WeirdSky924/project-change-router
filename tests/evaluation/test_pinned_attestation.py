from __future__ import annotations

import copy
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from router_support.bundle_io import (
    prepare_router_bundle_for_preserved_write,
    write_router_bundle,
)
from router_support.evaluation_policy import (
    evaluation_input_digest,
    make_evaluation_attestation,
    policy_for_bundle,
)
from .test_evaluation_policy import _bundle, _metrics
import router_core


def test_preserved_artifacts_rebind_attestation_to_effective_written_bundle(
    tmp_path: Path,
) -> None:
    pinned, bundle_root = _bundle(tmp_path)
    pinned["exception_registry"] = {"exceptions": []}
    rebuilt = copy.deepcopy(pinned)
    rebuilt["capability_catalog"]["source_commit"] = "b" * 40
    pinned["capability_catalog"]["source_commit"] = "a" * 40
    rebuilt["config"]["evaluation"]["attestation"] = (
        make_evaluation_attestation(rebuilt, _metrics())
    )

    effective = prepare_router_bundle_for_preserved_write(
        rebuilt,
        pinned,
        {"capability_catalog"},
    )

    attestation = effective["config"]["evaluation"]["attestation"]
    assert attestation["input_digest"] == evaluation_input_digest(effective)
    decision = policy_for_bundle(effective)
    assert decision.passed is True
    assert decision.enforcement_mode == "normal"

    write_router_bundle(bundle_root, effective)
    loaded = router_core.load_bundle(bundle_root)
    loaded_attestation = loaded["config"]["evaluation"]["attestation"]
    assert loaded_attestation["input_digest"] == evaluation_input_digest(loaded)
    assert policy_for_bundle(loaded).passed is True
