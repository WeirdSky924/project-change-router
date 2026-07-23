from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from router_support.evaluation_policy import make_evaluation_attestation


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data or {}


def write_text_in_chunks(
    path: Path,
    content: str,
    max_lines: int = 300,
    max_chars: int = 12_000,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = content.splitlines(keepends=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        chunk: list[str] = []
        char_count = 0
        for line in lines:
            if len(line) > max_chars:
                if chunk:
                    handle.write("".join(chunk))
                    chunk, char_count = [], 0
                for offset in range(0, len(line), max_chars):
                    handle.write(line[offset : offset + max_chars])
                continue
            if chunk and (
                len(chunk) >= max_lines or char_count + len(line) > max_chars
            ):
                handle.write("".join(chunk))
                chunk, char_count = [], 0
            chunk.append(line)
            char_count += len(line)
        if chunk:
            handle.write("".join(chunk))


def dump_yaml_file(path: Path, data: Mapping[str, Any]) -> None:
    content = yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
    if path.exists() and path.read_bytes() == content.encode("utf-8"):
        return
    write_text_in_chunks(path, content)


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json_file(path: Path, data: Mapping[str, Any]) -> None:
    normalized = dict(data)
    if path.exists() and load_json_file(path) == normalized:
        return
    write_text_in_chunks(
        path,
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
    )


def write_router_bundle(
    bundle_root: Path,
    bundle: Mapping[str, Any],
    *,
    preserve_bundle_keys: Iterable[str] = (),
) -> None:
    preserved = frozenset(preserve_bundle_keys)
    bundle_root.mkdir(parents=True, exist_ok=True)
    (bundle_root / "references").mkdir(parents=True, exist_ok=True)
    for relative in (
        "schemas",
        "reports/route-decisions",
        "reports/index-rebuild",
        "reports/guardrail-results",
        "reports/evaluation",
    ):
        (bundle_root / relative).mkdir(parents=True, exist_ok=True)
    dump_yaml_file(bundle_root / "router-config.yaml", bundle["config"])
    artifacts = {
        "capability_catalog": "capability-catalog.yaml",
        "module_map": "module-map.yaml",
        "ownership": "ownership.yaml",
        "change_rules": "change-rules.yaml",
        "path_to_capability_map": "path-to-capability-map.yaml",
        "exception_registry": "exception-registry.yaml",
        "evaluation_set": "evaluation-set.yaml",
    }
    for bundle_key, filename in artifacts.items():
        if bundle_key not in preserved:
            dump_yaml_file(
                bundle_root / "references" / filename,
                bundle[bundle_key],
            )


def prepare_router_bundle_for_preserved_write(
    rebuilt: Mapping[str, Any],
    existing: Mapping[str, Any],
    preserve_bundle_keys: Iterable[str],
) -> dict[str, Any]:
    effective = copy.deepcopy(dict(rebuilt))
    for bundle_key in preserve_bundle_keys:
        if bundle_key not in existing:
            raise ValueError(
                f"preserved router artifact is missing from the loaded bundle: {bundle_key}"
            )
        effective[bundle_key] = copy.deepcopy(existing[bundle_key])
    config = effective.get("config", {})
    evaluation = config.get("evaluation", {}) if isinstance(config, Mapping) else {}
    attestation = (
        evaluation.get("attestation")
        if isinstance(evaluation, Mapping)
        else None
    )
    metrics = (
        attestation.get("metrics")
        if isinstance(attestation, Mapping)
        else None
    )
    if isinstance(evaluation, dict) and isinstance(metrics, Mapping):
        evaluation["attestation"] = make_evaluation_attestation(
            effective,
            metrics,
        )
    return effective
