from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping

import yaml

from router_support.generated_output_baseline.contract import (
    normalize_rebuild_volatiles,
    projected_artifact_payload,
)


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def canonical_yaml_text(payload: Mapping[str, Any]) -> str:
    return yaml.safe_dump(dict(payload), sort_keys=False, allow_unicode=True)


def strict_yaml(source: str) -> dict[str, Any]:
    payload = yaml.load(source, Loader=UniqueKeyLoader) or {}
    if not isinstance(payload, dict):
        raise ValueError("generated artifact must contain a YAML mapping")
    return payload


def _sha256(source: str | bytes) -> str:
    encoded = source.encode("utf-8") if isinstance(source, str) else source
    return hashlib.sha256(encoded).hexdigest()


def semantic_digest(
    payload: Mapping[str, Any],
    *,
    bundle_key: str | None = None,
) -> str:
    encoded = json.dumps(
        projected_artifact_payload(payload, bundle_key=bundle_key),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(encoded)


def canonical_text_digest(
    payload: Mapping[str, Any],
    *,
    bundle_key: str | None = None,
) -> str:
    projected = projected_artifact_payload(payload, bundle_key=bundle_key)
    return _sha256(canonical_yaml_text(projected))


def generated_output_rule_fingerprint(rule: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(rule))
    payload.pop("fingerprint", None)
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(encoded)


def expected_text(
    expected_payload: Mapping[str, Any],
    actual_payload: Mapping[str, Any],
    *,
    bundle_key: str,
    normalize_source_commit: bool = False,
) -> str:
    adjusted = copy.deepcopy(dict(expected_payload))
    normalize_rebuild_volatiles(
        adjusted,
        actual_payload,
        bundle_key=bundle_key,
    )
    if normalize_source_commit:
        adjusted["source_commit"] = actual_payload.get("source_commit")
    return canonical_yaml_text(adjusted)
