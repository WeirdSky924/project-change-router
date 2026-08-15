from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


TYPED_FINDING_SCHEMA_VERSION = 1

SEVERITIES = frozenset({"P0", "P1", "P2", "P3", "info"})
INVARIANT_CLASSES = frozenset({"always_global", "closure_global", "task_local"})
DELTA_STATES = frozenset(
    {
        "task_local_new",
        "task_local_expanded",
        "baseline_unchanged",
        "baseline_reduced",
        "resolved",
        "unknown",
    }
)
TASK_RELEVANCE = frozenset({"relevant", "unrelated", "unknown"})
EVIDENCE_STATES = frozenset(
    {"complete", "bounded", "incomplete", "stale", "invalid", "unavailable"}
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def digest_value(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalized_strings(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value).replace("\\", "/").strip()
                for value in values
                if str(value).strip()
            }
        )
    )


@dataclass(frozen=True)
class TypedFinding:
    finding_id: str
    type: str
    severity: str
    invariant_class: str
    origin: str
    delta_state: str
    task_relevance: str
    evidence_status: str
    policy_rule_id: str
    evidence_digest: str
    paths: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    relevance_trace: tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    message: str = ""
    schema_version: int = TYPED_FINDING_SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        type: object,
        severity: object,
        invariant_class: object,
        origin: object,
        delta_state: object,
        task_relevance: object,
        evidence_status: object,
        policy_rule_id: object,
        paths: Iterable[object] = (),
        capabilities: Iterable[object] = (),
        relevance_trace: Iterable[object] = (),
        evidence: Mapping[str, Any] | None = None,
        message: object = "",
    ) -> "TypedFinding":
        normalized_paths = _normalized_strings(paths)
        normalized_capabilities = _normalized_strings(capabilities)
        normalized_trace = _normalized_strings(relevance_trace)
        if not normalized_trace:
            targets = normalized_paths or normalized_capabilities
            normalized_trace = tuple(
                f"path:{value} -> finding:{type}"
                if value in normalized_paths
                else f"capability:{value} -> finding:{type}"
                for value in targets
            )
        normalized_evidence = dict(evidence or {})
        identity = {
            "type": str(type),
            "severity": str(severity),
            "invariant_class": str(invariant_class),
            "origin": str(origin),
            "policy_rule_id": str(policy_rule_id),
            "paths": normalized_paths,
            "capabilities": normalized_capabilities,
        }
        return cls(
            finding_id=digest_value(identity),
            type=str(type),
            severity=str(severity),
            invariant_class=str(invariant_class),
            origin=str(origin),
            delta_state=str(delta_state),
            task_relevance=str(task_relevance),
            evidence_status=str(evidence_status),
            policy_rule_id=str(policy_rule_id),
            evidence_digest=digest_value(normalized_evidence),
            paths=normalized_paths,
            capabilities=normalized_capabilities,
            relevance_trace=normalized_trace,
            evidence=normalized_evidence,
            message=str(message),
        )

    def with_classification(
        self,
        *,
        delta_state: str | None = None,
        task_relevance: str | None = None,
        evidence_status: str | None = None,
    ) -> "TypedFinding":
        return dataclasses.replace(
            self,
            delta_state=delta_state or self.delta_state,
            task_relevance=task_relevance or self.task_relevance,
            evidence_status=evidence_status or self.evidence_status,
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TypedFinding":
        errors = validate_typed_finding(value)
        if errors:
            raise ValueError("invalid typed finding fields: " + ", ".join(errors))
        return cls(
            finding_id=str(value["finding_id"]),
            type=str(value["type"]),
            severity=str(value["severity"]),
            invariant_class=str(value["invariant_class"]),
            origin=str(value["origin"]),
            delta_state=str(value["delta_state"]),
            task_relevance=str(value["task_relevance"]),
            evidence_status=str(value["evidence_status"]),
            policy_rule_id=str(value["policy_rule_id"]),
            evidence_digest=str(value["evidence_digest"]),
            paths=tuple(value.get("paths", [])),
            capabilities=tuple(value.get("capabilities", [])),
            relevance_trace=tuple(value.get("relevance_trace", [])),
            evidence=dict(value.get("evidence", {})),
            message=str(value.get("message", "")),
            schema_version=int(value.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "finding_id": self.finding_id,
            "type": self.type,
            "severity": self.severity,
            "invariant_class": self.invariant_class,
            "origin": self.origin,
            "delta_state": self.delta_state,
            "task_relevance": self.task_relevance,
            "evidence_status": self.evidence_status,
            "policy_rule_id": self.policy_rule_id,
            "paths": list(self.paths),
            "capabilities": list(self.capabilities),
            "relevance_trace": list(self.relevance_trace),
            "evidence_digest": self.evidence_digest,
            "evidence": dict(self.evidence),
            "message": self.message,
        }


def validate_typed_finding(value: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    required_strings = (
        "finding_id",
        "type",
        "severity",
        "invariant_class",
        "origin",
        "delta_state",
        "task_relevance",
        "evidence_status",
        "policy_rule_id",
        "evidence_digest",
    )
    for name in required_strings:
        if not isinstance(value.get(name), str) or not value.get(name):
            errors.append(name)
    enums = {
        "severity": SEVERITIES,
        "invariant_class": INVARIANT_CLASSES,
        "delta_state": DELTA_STATES,
        "task_relevance": TASK_RELEVANCE,
        "evidence_status": EVIDENCE_STATES,
    }
    for name, choices in enums.items():
        if value.get(name) not in choices and name not in errors:
            errors.append(name)
    for name in ("finding_id", "evidence_digest"):
        raw = value.get(name)
        if isinstance(raw, str) and (
            len(raw) != 64 or any(char not in "0123456789abcdef" for char in raw)
        ):
            errors.append(name)
    for name in ("paths", "capabilities", "relevance_trace"):
        raw = value.get(name, [])
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            errors.append(name)
    return tuple(dict.fromkeys(errors))


def findings_digest(findings: Iterable[TypedFinding]) -> str:
    return digest_value(
        [
            finding.to_dict()
            for finding in sorted(findings, key=lambda item: item.finding_id)
        ]
    )
