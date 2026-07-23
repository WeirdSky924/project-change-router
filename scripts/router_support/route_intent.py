from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Optional


def positive_request_scope(request_text: str) -> str:
    text = request_text.lower()
    negated_scope = re.compile(
        r"(?<![a-z0-9_])(?:no|without|do\s+not|does\s+not|must\s+not|excluding|exclude)"
        r"(?![a-z0-9_])[^;.\n]*"
    )
    return negated_scope.sub(" ", text)


def request_has_phrase(request_text: str, phrase: str) -> bool:
    if not phrase.isascii():
        return phrase in request_text
    pattern = re.escape(phrase).replace(r"\ ", r"\s+")
    return (
        re.search(
            rf"(?<![a-z0-9_]){pattern}(?![a-z0-9_])", request_text
        )
        is not None
    )


def parse_request_type(request_text: str) -> str:
    text = request_text.lower()
    if any(word in text for word in ("bug", "fix", "repair", "regression", "修复", "修正")):
        return "bug-fix"
    if any(word in text for word in ("refactor", "extract", "cleanup", "重构", "抽取")):
        return "refactor"
    if any(word in text for word in ("migrate", "migration", "升级", "迁移")):
        return "migration"
    if any(word in text for word in ("add", "new", "create", "introduce", "新增", "创建", "引入")):
        return "feature-addition"
    return "feature-modification"


def request_duplicate_signal(
    request_text: str, changed_paths: Iterable[str]
) -> tuple[bool, int]:
    if request_additive_intent(request_text) or request_prefers_reuse(request_text):
        return False, 0
    count = 1 if request_prefers_extract(request_text) else 0
    normalized_paths = [path.replace("\\", "/") for path in changed_paths]
    top_level = {item.split("/")[0] for item in normalized_paths if item}
    if len(top_level) > 1:
        count += 1
    if len(normalized_paths) >= 2:
        count += 1
    return count >= 2, count


def high_risk_keyword_scope(request_text: str, keyword: str) -> str:
    if keyword != "token":
        return request_text
    usage_term = r"(?:usage|accounting|consumption|statistics|stats|metrics|costs?)"
    token_usage = re.compile(
        rf"(?<![a-z0-9_])(?:token[-_\s]+{usage_term}|{usage_term}[-_\s]+token)"
        rf"(?![a-z0-9_])"
    )
    return token_usage.sub(" ", request_text)


def request_has_high_risk_keyword(
    request_text: str, keywords: Iterable[str]
) -> bool:
    positive_scope = positive_request_scope(request_text)
    sensitive_gateway = re.compile(
        r"(?:provider|execution|egress|database|postgres|sql|llm|model|credential|"
        r"payment|billing|tenant|auth|security)[a-z0-9 _/-]{0,48}gateway|"
        r"gateway[a-z0-9 _/-]{0,48}(?:provider|execution|egress|database|postgres|"
        r"sql|llm|model|credential|payment|billing|tenant|auth|security)"
    )
    for keyword in keywords:
        normalized = str(keyword).lower()
        if normalized == "gateway":
            if sensitive_gateway.search(positive_scope):
                return True
            continue
        keyword_scope = high_risk_keyword_scope(positive_scope, normalized)
        if request_has_phrase(keyword_scope, normalized):
            return True
    return False


def owner_evidence_paths(changed_paths: list[str]) -> list[str]:
    project_meta_prefixes = (
        ".agent-handoff/",
        ".claude/skills/project-change-router/",
        "docs/",
        "project-change-router/",
    )
    project_meta_files = {
        ".project-change-router.yaml",
        ".project-change-router.yml",
        "project-change-router.profile.yaml",
        "project-change-router.profile.yml",
        "AGENTS.md",
        "AGENT_HANDOFF.md",
        "README.md",
    }
    normalized = [path.replace("\\", "/") for path in changed_paths]
    non_meta_paths = [
        path
        for path in normalized
        if path not in project_meta_files and not path.startswith(project_meta_prefixes)
    ]
    return non_meta_paths or normalized


def module_path_proximity(capability: Any, changed_paths: list[str]) -> float:
    owner_paths = {
        path.replace("\\", "/").lower() for path in capability.owner_modules
    }
    if not owner_paths or not changed_paths:
        return 0.0
    evidence_paths = owner_evidence_paths(changed_paths)
    hits = 0
    for path in evidence_paths:
        normalized = path.replace("\\", "/").lower()
        if any(
            normalized == owner or normalized.startswith(owner.rstrip("/") + "/")
            for owner in owner_paths
        ):
            hits += 1
    return hits / max(1, len(evidence_paths))


def request_targets_existing_capability(request_text: str) -> bool:
    text = request_text.lower()
    negative_patterns = (
        "no existing",
        "not existing",
        "without existing",
        "does not map to any existing",
        "doesn't map to any existing",
        "不存在现有",
        "没有现有",
        "不属于现有",
    )
    if any(pattern in text for pattern in negative_patterns):
        return False
    phrases = (
        "existing",
        "reuse",
        "extend",
        "current",
        "already",
        "现有",
        "已有",
        "复用",
        "扩展",
    )
    return any(phrase in text for phrase in phrases)


def request_prefers_extract(request_text: str) -> bool:
    text = positive_request_scope(request_text).strip()
    leading_actions = (
        "extract",
        "refactor",
        "split",
        "deduplicate",
        "consolidate",
        "calibrate",
        "抽取",
        "重构",
        "拆分",
    )
    if any(
        request_has_phrase(text, action) and text.startswith(action)
        for action in leading_actions
    ):
        return True
    phrases = (
        "by extracting",
        "helper extraction",
        "planning parity",
        "planning from source",
        "merge defaults",
        "repository gateway behavior",
        "重复实现",
    )
    return any(request_has_phrase(text, phrase) for phrase in phrases)


def request_additive_intent(request_text: str) -> bool:
    text = positive_request_scope(request_text)
    actions = (
        "add",
        "extend",
        "expose",
        "update",
        "modify",
        "implement",
        "introduce",
        "create",
        "aggregate",
        "narrow",
        "restore",
        "change",
        "新增",
        "扩展",
        "修改",
        "实现",
        "创建",
    )
    return any(request_has_phrase(text, action) for action in actions)


def request_prefers_reuse(request_text: str) -> bool:
    text = positive_request_scope(request_text).strip()
    return text.startswith("preserve ") or text.startswith("keep existing ")


def request_requires_review(request_text: str) -> bool:
    text = positive_request_scope(request_text)
    stripped = text.strip()
    if stripped.startswith(("review ", "review:", "please review ", "审查")):
        return True
    phrases = (
        "manual review",
        "requires review",
        "request review",
        "ambiguous",
        "unclear",
        "cross-cutting",
        "broad",
        "审查",
        "模糊",
        "不明确",
        "跨模块",
    )
    return any(request_has_phrase(text, phrase) for phrase in phrases)


def request_duplicates_existing_owner(request_text: str) -> bool:
    text = positive_request_scope(request_text)
    phrases = (
        "parallel implementation",
        "independent cache",
        "instead of reusing",
        "instead of reuse",
        "second transport",
        "second cache",
        "second store",
        "second repository root",
        "second formal repository root",
        "parallel repository root",
        "second implementation center",
        "parallel implementation center",
    )
    if any(request_has_phrase(text, phrase) for phrase in phrases):
        return True
    duplicate_surface = re.compile(
        r"(?<![a-z0-9_])duplicate(?:\s+[a-z0-9_-]+){0,2}\s+"
        r"(?:store|selector|cache|transport|runtime|service|implementation|framework)"
        r"(?![a-z0-9_])"
    )
    return bool(duplicate_surface.search(text))


def request_requires_sensitive_review(
    request_text: str, configured_phrases: Iterable[str] = ()
) -> bool:
    text = positive_request_scope(request_text)
    return any(
        request_has_phrase(text, str(phrase).lower())
        for phrase in configured_phrases
        if str(phrase).strip()
    )


def request_lifecycle_target(request_text: str) -> Optional[str]:
    text = positive_request_scope(request_text)
    capability_id = r"[a-z0-9][a-z0-9_.:/-]*"
    qualifiers = r"(?:(?:the|a|an|existing|current|legacy|named)\s+)*"
    patterns = (
        re.compile(
            rf"(?<![a-z0-9_])(?:deprecate|supersede)(?![a-z0-9_])\s+"
            rf"{qualifiers}(?P<target>{capability_id})\s+"
            rf"capabilit(?:y|ies)(?![a-z0-9_])"
        ),
        re.compile(
            rf"(?<![a-z0-9_])(?:deprecate|supersede)(?![a-z0-9_])\s+"
            rf"capabilit(?:y|ies)\s+{qualifiers}(?P<target>{capability_id})"
            rf"(?![a-z0-9_])"
        ),
        re.compile(
            rf"(?<![a-z0-9_])mark(?![a-z0-9_])\s+{qualifiers}"
            rf"(?P<target>{capability_id})\s+capabilit(?:y|ies)\s+"
            rf"(?:as\s+)?deprecated(?![a-z0-9_])"
        ),
        re.compile(rf"(?:废弃|弃用|替代)\s*(?P<target>{capability_id})\s*能力"),
        re.compile(rf"(?:废弃|弃用|替代)\s*能力\s*(?P<target>{capability_id})"),
        re.compile(
            rf"将\s*(?P<target>{capability_id})\s*能力\s*"
            rf"(?:标记为|设为)?\s*(?:废弃|弃用|替代)"
        ),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return match.group("target")
    return None


def request_lifecycle_intent(request_text: str) -> Optional[str]:
    text = positive_request_scope(request_text)
    if any(
        request_has_phrase(text, word)
        for word in (
            "delete capability",
            "remove capability",
            "drop capability",
            "删除能力",
            "移除能力",
        )
    ):
        return "delete"
    if any(
        request_has_phrase(text, word)
        for word in (
            "merge capability",
            "combine capability",
            "consolidate capability",
            "合并能力",
            "整合能力",
        )
    ):
        return "merge"
    if request_lifecycle_target(text):
        return "deprecate"
    if any(
        request_has_phrase(text, word)
        for word in (
            "rename capability",
            "move capability",
            "迁移能力",
            "重命名能力",
        )
    ):
        return "migrate"
    return None
