from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


@lru_cache(maxsize=16)
def schema_registry(schema_root_text: str) -> Registry:
    schema_root = Path(schema_root_text).resolve()
    registry = Registry()
    for path in sorted(schema_root.glob("*.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(schema)
        canonical_uri = str(schema.get("$id") or path.as_uri())
        registry = registry.with_resource(canonical_uri, resource)
        registry = registry.with_resource(path.as_uri(), resource)
    return registry


def validator_for_schema(schema_path: Path) -> Draft202012Validator:
    path = Path(schema_path).resolve()
    schema: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(
        schema,
        registry=schema_registry(str(path.parent)),
    )
