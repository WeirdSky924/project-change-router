from __future__ import annotations

import re


_JAVA_IMPORT = re.compile(
    r"^\s*import\s+(?:static\s+)?"
    r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\.\*)+)\s*;",
    re.MULTILINE,
)


def _blank(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] not in {"\n", "\r"}:
            chars[index] = " "


def java_code_view(source: str) -> str:
    """Blank Java comments and literals while preserving statement positions."""

    chars = list(source)
    index = 0
    length = len(source)
    while index < length:
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            _blank(chars, index, end)
            index = end
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            end = length if closing < 0 else closing + 2
            _blank(chars, index, end)
            index = end
            continue
        if source.startswith('"""', index):
            closing = source.find('"""', index + 3)
            end = length if closing < 0 else closing + 3
            _blank(chars, index, end)
            index = end
            continue
        if source[index] in {'"', "'"}:
            quote = source[index]
            end = index + 1
            while end < length:
                if source[end] == "\\":
                    end += 2
                    continue
                end += 1
                if source[end - 1] == quote:
                    break
            _blank(chars, index, min(end, length))
            index = end
            continue
        index += 1
    return "".join(chars)


def java_imports(source: str) -> list[str]:
    return _JAVA_IMPORT.findall(java_code_view(source))
