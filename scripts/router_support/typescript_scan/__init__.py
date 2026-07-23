from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass


_JSX_TAG_NAME = re.compile(r"[A-Za-z_$][\w$.:-]*")
CONTROL_HEADER_KEYWORDS = frozenset({
    "catch",
    "for",
    "if",
    "switch",
    "while",
    "with",
})
ELSE_STATEMENT_CONTROL_KEYWORDS = frozenset({"for", "if", "while", "with"})


@dataclass
class JsxContext:
    kind: str
    name: str = ""
    brace_depth: int = 0
    self_closing: bool = False
    type_argument_depth: int = 0


def _scan_tag_name(source: str, index: int) -> tuple[str, int] | None:
    match = _JSX_TAG_NAME.match(source, index)
    return (match.group(0), match.end()) if match is not None else None


def _skip_quoted(source: str, index: int) -> int:
    quote = source[index]
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == quote:
            return index + 1
        index += 1
    return len(source)


def _type_arguments_end(source: str, index: int) -> int | None:
    depth = 0
    while index < len(source):
        current = source[index]
        if current in {"'", '"', "`"}:
            index = _skip_quoted(source, index)
            continue
        if current == "<":
            depth += 1
        elif current == ">" and (index == 0 or source[index - 1] != "="):
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def opening_tag_name(source: str, index: int) -> str | None:
    following = source[index + 1] if index + 1 < len(source) else ""
    if following == ">":
        return ""
    parsed_name = _scan_tag_name(source, index + 1)
    if parsed_name is None:
        return None
    name, name_end = parsed_name
    if name_end < len(source) and source[name_end] == "<":
        type_end = _type_arguments_end(source, name_end)
        if type_end is None:
            return None
        name_end = type_end
    return name if name_end < len(source) and (
        source[name_end].isspace() or source[name_end] in {"/", ">"}
    ) else None


def generic_arrow_prefix(source: str, index: int) -> bool:
    type_end = _type_arguments_end(source, index)
    if type_end is None:
        return False
    parameters = source[index + 1 : type_end - 1]
    head = re.match(r"\s*(?:const\s+)?[A-Za-z_$][\w$]*", parameters)
    if head is None:
        return False
    remainder = parameters[head.end() :].lstrip()
    if not (
        remainder.startswith((",", "="))
        or re.match(r"extends(?:\s|/\*)", remainder)
    ):
        return False
    cursor = type_end
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    if cursor >= len(source) or source[cursor] != "(":
        return False
    depth = 0
    while cursor < len(source):
        current = source[cursor]
        if current in {"'", '"', "`"}:
            cursor = _skip_quoted(source, cursor)
            continue
        if current == "(":
            depth += 1
        elif current == ")":
            depth -= 1
            if depth == 0:
                cursor += 1
                break
        cursor += 1
    if depth != 0:
        return False
    while cursor < len(source) and source[cursor].isspace():
        cursor += 1
    return source.startswith("=>", cursor)


def closing_tag_name(source: str, index: int) -> str | None:
    name_start = index + 2
    if name_start < len(source) and source[name_start] == ">":
        return ""
    parsed_name = _scan_tag_name(source, name_start)
    if parsed_name is None:
        return None
    name, name_end = parsed_name
    while name_end < len(source) and source[name_end].isspace():
        name_end += 1
    return name if name_end < len(source) and source[name_end] == ">" else None


def _previous_code_index(
    source: str,
    code_positions: Sequence[int],
    cursor: int,
) -> int:
    while cursor >= 0 and (
        not code_positions[cursor] or source[cursor].isspace()
    ):
        cursor -= 1
    return cursor


def _identifier_before(
    source: str,
    code_positions: Sequence[int],
    cursor: int,
) -> tuple[str, int, int]:
    cursor = _previous_code_index(source, code_positions, cursor)
    end = cursor + 1
    while cursor >= 0 and code_positions[cursor] and (
        source[cursor].isalnum() or source[cursor] in {"_", "$"}
    ):
        cursor -= 1
    return source[cursor + 1 : end], cursor + 1, cursor


def _has_statement_boundary(
    source: str,
    code_positions: Sequence[int],
    keyword_start: int,
) -> bool:
    cursor = _previous_code_index(source, code_positions, keyword_start - 1)
    if cursor < 0:
        return True
    current = source[cursor]
    return current not in {".", "?"} and not (
        current.isalnum() or current in {"_", "$"}
    )


def _has_control_header_boundary(
    source: str,
    code_positions: Sequence[int],
    keyword: str,
    keyword_start: int,
) -> bool:
    if _has_statement_boundary(source, code_positions, keyword_start):
        return True
    if keyword not in ELSE_STATEMENT_CONTROL_KEYWORDS:
        return False
    prefix, prefix_start, _ = _identifier_before(
        source, code_positions, keyword_start - 1
    )
    return prefix == "else" and _has_statement_boundary(
        source, code_positions, prefix_start
    )


def closing_parenthesis_is_control_header(
    source: str,
    code_positions: Sequence[int],
    index: int,
) -> bool:
    cursor = _previous_code_index(source, code_positions, index - 1)
    if cursor < 0 or source[cursor] != ")":
        return False
    depth = 0
    while cursor >= 0:
        if not code_positions[cursor]:
            cursor -= 1
            continue
        current = source[cursor]
        if current == ")":
            depth += 1
        elif current == "(":
            depth -= 1
            if depth == 0:
                cursor -= 1
                break
        cursor -= 1
    keyword, keyword_start, before_keyword = _identifier_before(
        source, code_positions, cursor
    )
    if keyword in CONTROL_HEADER_KEYWORDS:
        return _has_control_header_boundary(
            source, code_positions, keyword, keyword_start
        )
    if keyword != "await":
        return False
    prefix, prefix_start, _ = _identifier_before(
        source, code_positions, before_keyword
    )
    return prefix == "for" and _has_control_header_boundary(
        source, code_positions, prefix, prefix_start
    )
