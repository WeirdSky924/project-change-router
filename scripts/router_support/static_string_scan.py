from __future__ import annotations

import ast


def static_python_strings(source: str) -> set[str]:
    tree = ast.parse(source)

    def static_string(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = static_string(node.left)
            right = static_string(node.right)
            if left is not None and right is not None:
                return left + right
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    parts.append(" ")
                else:
                    return None
            return "".join(parts)
        return None

    return {
        value
        for node in ast.walk(tree)
        if (value := static_string(node)) is not None
    }


def static_javascript_strings(source: str) -> set[str]:
    strings: set[str] = set()

    def skip_comment(index: int, end: int) -> int | None:
        if source.startswith("//", index):
            newline = source.find("\n", index + 2, end)
            return end if newline < 0 else newline + 1
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2, end)
            if closing < 0:
                raise SyntaxError("unterminated JavaScript block comment")
            return closing + 2
        return None

    def constant_plus_separator(start: int, end: int) -> bool:
        index = start
        seen_plus = False
        while index < end:
            if source[index].isspace():
                index += 1
                continue
            comment_end = skip_comment(index, end)
            if comment_end is not None:
                index = comment_end
                continue
            token = source[index]
            if token == ")" and not seen_plus:
                index += 1
                continue
            if token == "+" and not seen_plus:
                seen_plus = True
                index += 1
                continue
            if token == "(" and seen_plus:
                index += 1
                continue
            return False
        return seen_plus

    def quoted(index: int, end: int) -> tuple[str, int]:
        quote = source[index]
        index += 1
        value: list[str] = []
        while index < end:
            current = source[index]
            if current == "\\":
                if index + 1 >= end:
                    raise SyntaxError("unterminated JavaScript string escape")
                value.append(source[index + 1])
                index += 2
                continue
            if current == quote:
                return "".join(value), index + 1
            value.append(current)
            index += 1
        raise SyntaxError("unterminated JavaScript string literal")

    def expression_end(index: int, end: int) -> int:
        depth = 1
        while index < end:
            comment_end = skip_comment(index, end)
            if comment_end is not None:
                index = comment_end
                continue
            current = source[index]
            if current in {"'", '"'}:
                _, index = quoted(index, end)
                continue
            if current == "`":
                _, index = template(index, end)
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        raise SyntaxError("unterminated JavaScript template expression")

    def template(index: int, end: int) -> tuple[str | None, int]:
        index += 1
        parts: list[str] = []
        fragment: list[str] = []
        dynamic = False
        while index < end:
            current = source[index]
            if current == "\\":
                if index + 1 >= end:
                    raise SyntaxError("unterminated JavaScript template escape")
                fragment.append(source[index + 1])
                index += 2
                continue
            if current == "`":
                parts.append("".join(fragment))
                strings.update(part for part in parts if part)
                return (None if dynamic else "".join(parts)), index + 1
            if source.startswith("${", index):
                dynamic = True
                parts.append("".join(fragment))
                fragment = []
                closing = expression_end(index + 2, end)
                scan(index + 2, closing)
                index = closing + 1
                continue
            fragment.append(current)
            index += 1
        raise SyntaxError("unterminated JavaScript template literal")

    def scan(start: int, end: int) -> None:
        literals: list[tuple[int, int, str]] = []
        index = start
        while index < end:
            comment_end = skip_comment(index, end)
            if comment_end is not None:
                index = comment_end
                continue
            current = source[index]
            if current in {"'", '"'}:
                literal_start = index
                value, index = quoted(index, end)
                strings.add(value)
                literals.append((literal_start, index, value))
                continue
            if current == "`":
                literal_start = index
                value, index = template(index, end)
                if value is not None:
                    strings.add(value)
                    literals.append((literal_start, index, value))
                continue
            index += 1

        chain = ""
        previous_end: int | None = None
        for literal_start, literal_end, value in literals:
            if previous_end is not None and constant_plus_separator(previous_end, literal_start):
                chain += value
            else:
                chain = value
            strings.add(chain)
            previous_end = literal_end

    scan(0, len(source))
    return strings
