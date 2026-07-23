from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Iterable


_TS_IMPORT_FROM = re.compile(
    r"""
    (?:^|[;\n])[ \t]*import[ \t]+
    (?P<clause>
        (?:type[ \t]+)?
        (?:
            [A-Za-z_$][\w$]*
            (?:[ \t\r\n]*,[ \t\r\n]*(?:\{[^{}]*\}|\*[ \t]+as[ \t]+[A-Za-z_$][\w$]*))?
            |\{[^{}]*\}
            |\*[ \t]+as[ \t]+[A-Za-z_$][\w$]*
        )
    )
    [ \t\r\n]+from[ \t\r\n]*(?P<quote>['"])(?P<path>[^'"]+)(?P=quote)
    """,
    re.MULTILINE | re.VERBOSE,
)
_TS_SIDE_EFFECT_IMPORT = re.compile(
    r"(?:^|[;\n])[ \t]*import[ \t]+(?P<quote>['\"])(?P<path>[^'\"]+)(?P=quote)",
    re.MULTILINE,
)
_TS_EXPORT_FROM = re.compile(
    r"""
    (?:^|[;\n])[ \t]*export[ \t]+
    (?P<export>type[ \t]+)?
    (?P<clause>\{[^{}]*\}|\*(?:[ \t]+as[ \t]+[A-Za-z_$][\w$]*)?)
    [ \t\r\n]+from[ \t\r\n]*(?P<quote>['"])(?P<path>[^'"]+)(?P=quote)
    """,
    re.MULTILINE | re.VERBOSE,
)
_TS_REQUIRE = re.compile(
    r"\brequire\s*\(\s*(?P<quote>['\"])(?P<path>[^'\"]+)(?P=quote)\s*\)"
)
_TS_REQUIRE_CALL = re.compile(r"\brequire\s*\(")
_TS_DYNAMIC_IMPORT = re.compile(
    r"\bimport\s*\(\s*(?P<quote>['\"])(?P<path>[^'\"]+)(?P=quote)\s*\)"
)
_TS_DYNAMIC_IMPORT_CALL = re.compile(r"\bimport\s*\(")
_TS_DECLARED_EXPORT = re.compile(
    r"(?:^|\n)\s*export\s+(?:declare\s+)?(?:const|let|var|class|function|interface|type|enum)\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE,
)
_TS_LIST_EXPORT = re.compile(
    r"(?:^|\n)\s*export\s+(?:type\s+)?\{([^{}]*)\}(?:\s+from\s+['\"][^'\"]+['\"])?",
    re.MULTILINE,
)
_TS_DEFAULT_EXPORT = re.compile(r"(?:^|\n)\s*export\s+default\b", re.MULTILINE)
_TS_MODULE_EXPORT_OBJECT = re.compile(
    r"\bmodule\s*\.\s*exports\s*=(?!=|>)\s*\{(?P<members>[^{}]*)\}"
)
_TS_MODULE_EXPORT_ASSIGN = re.compile(
    r"\bmodule\s*\.\s*exports\s*=(?!=|>)"
)
_TS_NAMED_EXPORT_ASSIGN = re.compile(
    r"\b(?:exports|module\s*\.\s*exports)\s*\.\s*(?P<name>[A-Za-z_$][\w$]*)\s*=(?!=|>)"
)
_TS_COMPUTED_EXPORT_ASSIGN = re.compile(
    r"\b(?:exports|module\s*\.\s*exports)\s*\[[^\]\r\n]*\]\s*=(?!=|>)"
)
_TS_EXPORT_EQUALS = re.compile(r"(?:^|[;\n])[ \t]*export[ \t]*=", re.MULTILINE)


def _literal_string_sequence(
    node: ast.AST | None, current: list[str]
) -> list[str] | None:
    if isinstance(node, ast.Name) and node.id == "__all__":
        return list(current)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        if all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in node.elts
        ):
            return [str(item.value) for item in node.elts]
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string_sequence(node.left, current)
        right = _literal_string_sequence(node.right, current)
        return None if left is None or right is None else [*left, *right]
    return None


def python_all_exports(tree: ast.Module) -> tuple[list[str], bool]:
    exports: list[str] = []
    incomplete = False
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            value = node.value
        if value is not None:
            resolved = _literal_string_sequence(value, exports)
            if resolved is None:
                incomplete = True
            else:
                exports = resolved
            continue
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            resolved = _literal_string_sequence(node.value, exports)
            if not isinstance(node.op, ast.Add) or resolved is None:
                incomplete = True
            else:
                exports.extend(resolved)
            continue
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        function = call.func
        if not (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "__all__"
        ):
            continue
        if function.attr == "append" and len(call.args) == 1:
            argument = call.args[0]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                exports.append(argument.value)
                continue
        elif function.attr == "extend" and len(call.args) == 1:
            resolved = _literal_string_sequence(call.args[0], exports)
            if resolved is not None:
                exports.extend(resolved)
                continue
        incomplete = True
    return sorted(set(exports)), incomplete


@dataclass(frozen=True)
class PythonDynamicBindings:
    bound: frozenset[str]
    import_module_aliases: frozenset[str]
    importlib_aliases: frozenset[str]


class _PythonBindingCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.bound: set[str] = set()
        self.import_module_aliases: set[str] = set()
        self.importlib_aliases: set[str] = set()
        self.outer_bindings: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.bound.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.bound.add(node.arg)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".", 1)[0]
            self.bound.add(name)
            if alias.name == "importlib":
                self.importlib_aliases.add(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self.bound.add(name)
            if not node.level and node.module == "importlib" and alias.name == "import_module":
                self.import_module_aliases.add(name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bound.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bound.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_Global(self, node: ast.Global) -> None:
        self.outer_bindings.update(node.names)

    visit_Nonlocal = visit_Global

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def python_dynamic_bindings(
    statements: Iterable[ast.stmt], arguments: ast.arguments | None = None
) -> PythonDynamicBindings:
    collector = _PythonBindingCollector()
    if arguments is not None:
        collector.visit(arguments)
    for statement in statements:
        collector.visit(statement)
    bound = collector.bound - collector.outer_bindings
    return PythonDynamicBindings(
        frozenset(bound),
        frozenset(collector.import_module_aliases - collector.outer_bindings),
        frozenset(collector.importlib_aliases - collector.outer_bindings),
    )


@dataclass(frozen=True)
class TypeScriptImport:
    specifier: str
    runtime: bool
    imported_symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypeScriptSourceScan:
    imports: tuple[TypeScriptImport, ...]
    exports: tuple[str, ...]
    incomplete_dynamic_imports: int = 0
    incomplete_lexical_regions: int = 0
    incomplete_public_exports: int = 0


@dataclass(frozen=True)
class _TemplateLiteral:
    start: int
    end: int
    value: str | None


@dataclass(frozen=True)
class _LexicalView:
    source: str
    code_positions: bytes
    templates: tuple[_TemplateLiteral, ...]
    incomplete_regions: int

    def keyword_is_code(self, match: re.Match[str], keyword: str) -> bool:
        offset = match.group(0).find(keyword)
        position = match.start() + offset
        return offset >= 0 and bool(self.code_positions[position])

def _typescript_lexical_view(source: str) -> _LexicalView:
    """Blank comments/template text while retaining interpolation code."""
    scrubbed = list(source)
    code = bytearray(len(source))
    templates: list[_TemplateLiteral] = []
    incomplete_regions = 0

    def blank(start: int, end: int) -> None:
        for position in range(start, min(end, len(source))):
            if scrubbed[position] not in {"\n", "\r"}:
                scrubbed[position] = " "

    def scan_quoted(index: int) -> int:
        quote = source[index]
        index += 1
        while index < len(source):
            if source[index] == "\\":
                index += 2
                continue
            index += 1
            if source[index - 1] == quote:
                break
        return index

    def scan_regex(index: int) -> int | None:
        cursor = index + 1
        in_character_class = False
        while cursor < len(source):
            current = source[cursor]
            if current in {"\n", "\r"}:
                return None
            if current == "\\":
                cursor += 2
                continue
            if current == "[":
                in_character_class = True
            elif current == "]":
                in_character_class = False
            elif current == "/" and not in_character_class:
                cursor += 1
                while cursor < len(source) and source[cursor].isalpha():
                    cursor += 1
                return cursor
            cursor += 1
        return None

    def scan_template(index: int) -> int:
        start = index
        literal = True
        value: list[str] = []
        blank(index, index + 1)
        index += 1
        while index < len(source):
            following = source[index + 1] if index + 1 < len(source) else ""
            if source[index] == "\\":
                literal = False
                blank(index, index + 2)
                index += 2
            elif source[index] == "`":
                blank(index, index + 1)
                end = index + 1
                templates.append(
                    _TemplateLiteral(start, end, "".join(value) if literal else None)
                )
                return end
            elif source[index] == "$" and following == "{":
                literal = False
                blank(index, index + 2)
                index = scan_code(index + 2, stop_at_template_brace=True)
            else:
                value.append(source[index])
                blank(index, index + 1)
                index += 1
        templates.append(_TemplateLiteral(start, index, None))
        return index

    def scan_code(index: int, *, stop_at_template_brace: bool = False) -> int:
        nonlocal incomplete_regions
        brace_depth = 0
        regex_allowed = True
        last_token = ""
        line_break_since_token = False
        while index < len(source):
            current = source[index]
            following = source[index + 1] if index + 1 < len(source) else ""
            if current.isspace():
                code[index] = 1
                line_break_since_token = line_break_since_token or current in {"\n", "\r"}
                index += 1
                continue
            if current in {"'", '"'}:
                index = scan_quoted(index)
                regex_allowed = False
                last_token = "value"
                line_break_since_token = False
                continue
            if current == "`":
                index = scan_template(index)
                regex_allowed = False
                last_token = "value"
                line_break_since_token = False
                continue
            if current == "/" and following == "/":
                newline = source.find("\n", index + 2)
                end = len(source) if newline < 0 else newline
                blank(index, end)
                index = end
                continue
            if current == "/" and following == "*":
                closing = source.find("*/", index + 2)
                end = len(source) if closing < 0 else closing + 2
                line_break_since_token = line_break_since_token or "\n" in source[index:end]
                blank(index, end)
                index = end
                continue
            if current == "/":
                regex_end = scan_regex(index)
                ambiguous = line_break_since_token or last_token in {")", "]", "}"}
                if regex_end is not None and (regex_allowed or ambiguous):
                    blank(index, regex_end)
                    if not regex_allowed:
                        incomplete_regions += 1
                    index = regex_end
                    regex_allowed = False
                    last_token = "value"
                    line_break_since_token = False
                    continue
                if regex_allowed and regex_end is None:
                    newline = source.find("\n", index + 1)
                    end = len(source) if newline < 0 else newline
                    blank(index, end)
                    incomplete_regions += 1
                    index = end
                    continue
                code[index] = 1
                if following == "=":
                    code[index + 1] = 1
                    index += 1
                index += 1
                regex_allowed = True
                last_token = "/"
                line_break_since_token = False
                continue
            if current.isalpha() or current in {"_", "$"}:
                start = index
                index += 1
                while index < len(source) and (
                    source[index].isalnum() or source[index] in {"_", "$"}
                ):
                    index += 1
                for position in range(start, index):
                    code[position] = 1
                word = source[start:index]
                regex_allowed = word in {
                    "await", "case", "delete", "in", "instanceof", "new",
                    "of", "return", "throw", "typeof", "void", "yield",
                }
                last_token = "identifier"
                line_break_since_token = False
                continue
            if current.isdigit():
                start = index
                index += 1
                while index < len(source) and (
                    source[index].isalnum() or source[index] in {"_", "."}
                ):
                    index += 1
                for position in range(start, index):
                    code[position] = 1
                regex_allowed = False
                last_token = "value"
                line_break_since_token = False
                continue
            if stop_at_template_brace and current == "{":
                brace_depth += 1
            elif stop_at_template_brace and current == "}":
                if brace_depth == 0:
                    blank(index, index + 1)
                    return index + 1
                brace_depth -= 1
            code[index] = 1
            if current in ")]}":
                regex_allowed = False
            elif current == ".":
                regex_allowed = False
            else:
                regex_allowed = True
            last_token = current
            line_break_since_token = False
            index += 1
        return index

    scan_code(0)
    return _LexicalView(
        "".join(scrubbed), bytes(code), tuple(templates), incomplete_regions
    )


def _type_only_clause(clause: str | None, export_type: str | None) -> bool:
    if export_type:
        return True
    normalized = (clause or "").strip()
    if normalized.startswith("type "):
        return True
    if not (normalized.startswith("{") and normalized.endswith("}")):
        return False
    members = [item.strip() for item in normalized[1:-1].split(",") if item.strip()]
    return bool(members) and all(item.startswith("type ") for item in members)


def _typescript_imported_symbols(clause: str | None) -> tuple[str, ...]:
    normalized = (clause or "").strip()
    if not normalized:
        return ()
    symbols: list[str] = []
    brace_match = re.search(r"\{([^{}]*)\}", normalized)
    if brace_match:
        for item in brace_match.group(1).split(","):
            value = re.sub(r"^type\s+", "", item.strip())
            if value:
                symbols.append(value.split(" as ")[-1].strip())
    prefix = normalized.split(",", 1)[0].strip()
    if prefix and not prefix.startswith(("{", "*", "type {")):
        symbols.append(re.sub(r"^type\s+", "", prefix))
    namespace = re.search(r"\*\s+as\s+([A-Za-z_$][\w$]*)", normalized)
    if namespace:
        symbols.append(namespace.group(1))
    return tuple(sorted(set(symbols)))


def _template_argument(
    view: _LexicalView, call: re.Match[str]
) -> _TemplateLiteral | None:
    for template in sorted(view.templates, key=lambda item: item.start):
        if template.start < call.end():
            continue
        if view.source[call.end() : template.start].strip():
            return None
        if re.match(r"[ \t\r\n]*\)", view.source[template.end :]):
            return template
        return None
    return None


def _literal_and_incomplete_calls(
    view: _LexicalView,
    literal_pattern: re.Pattern[str],
    call_pattern: re.Pattern[str],
    keyword: str,
) -> tuple[list[TypeScriptImport], int]:
    literal_matches = [
        match
        for match in literal_pattern.finditer(view.source)
        if view.keyword_is_code(match, keyword)
    ]
    imports = [
        TypeScriptImport(match.group("path"), True) for match in literal_matches
    ]
    consumed_starts = {match.start() for match in literal_matches}
    incomplete = 0
    for call in call_pattern.finditer(view.source):
        if not view.keyword_is_code(call, keyword) or call.start() in consumed_starts:
            continue
        template = _template_argument(view, call)
        if template is not None and template.value is not None:
            imports.append(TypeScriptImport(template.value, True))
        else:
            incomplete += 1
    return imports, incomplete


def _commonjs_object_members(source: str) -> tuple[set[str], bool]:
    members: set[str] = set()
    incomplete = False
    for raw_member in source.split(","):
        member = raw_member.strip()
        if not member:
            continue
        match = re.fullmatch(
            r"(?P<name>[A-Za-z_$][\w$]*)(?:\s*:\s*[^,]+)?", member
        )
        if match is None:
            incomplete = True
        else:
            members.add(match.group("name"))
    return members, incomplete


def scan_typescript_source(source: str) -> TypeScriptSourceScan:
    view = _typescript_lexical_view(source)
    imports: list[TypeScriptImport] = []
    for match in _TS_IMPORT_FROM.finditer(view.source):
        if not view.keyword_is_code(match, "import"):
            continue
        imports.append(
            TypeScriptImport(
                match.group("path"),
                not _type_only_clause(match.group("clause"), None),
                _typescript_imported_symbols(match.group("clause")),
            )
        )
    imports.extend(
        TypeScriptImport(match.group("path"), True)
        for match in _TS_SIDE_EFFECT_IMPORT.finditer(view.source)
        if view.keyword_is_code(match, "import")
    )
    for match in _TS_EXPORT_FROM.finditer(view.source):
        if not view.keyword_is_code(match, "export"):
            continue
        imports.append(
            TypeScriptImport(
                match.group("path"),
                not _type_only_clause(match.group("clause"), match.group("export")),
                _typescript_imported_symbols(match.group("clause")),
            )
        )
    require_imports, incomplete_requires = _literal_and_incomplete_calls(
        view, _TS_REQUIRE, _TS_REQUIRE_CALL, "require"
    )
    dynamic_imports, incomplete_imports = _literal_and_incomplete_calls(
        view, _TS_DYNAMIC_IMPORT, _TS_DYNAMIC_IMPORT_CALL, "import"
    )
    imports.extend([*require_imports, *dynamic_imports])
    incomplete_dynamic_imports = incomplete_requires + incomplete_imports

    exports = {
        match.group(1)
        for match in _TS_DECLARED_EXPORT.finditer(view.source)
        if view.keyword_is_code(match, "export")
    }
    for match in _TS_LIST_EXPORT.finditer(view.source):
        if not view.keyword_is_code(match, "export"):
            continue
        for item in match.group(1).split(","):
            value = re.sub(r"^type\s+", "", item.strip())
            if value:
                exports.add(value.split(" as ")[-1].strip())
    if any(
        view.keyword_is_code(match, "export")
        for match in _TS_DEFAULT_EXPORT.finditer(view.source)
    ):
        exports.add("default")
    literal_module_assignments: set[int] = set()
    incomplete_public_exports = 0
    for match in _TS_MODULE_EXPORT_OBJECT.finditer(view.source):
        if not view.keyword_is_code(match, "module"):
            continue
        literal_module_assignments.add(match.start())
        members, incomplete = _commonjs_object_members(match.group("members"))
        exports.update(members)
        incomplete_public_exports += int(incomplete)
    for match in _TS_MODULE_EXPORT_ASSIGN.finditer(view.source):
        if view.keyword_is_code(match, "module") and match.start() not in literal_module_assignments:
            incomplete_public_exports += 1
    for match in _TS_NAMED_EXPORT_ASSIGN.finditer(view.source):
        if view.keyword_is_code(match, "exports"):
            exports.add(match.group("name"))
    incomplete_public_exports += sum(
        1
        for match in _TS_COMPUTED_EXPORT_ASSIGN.finditer(view.source)
        if view.keyword_is_code(match, "exports")
    )
    if any(
        view.keyword_is_code(match, "export")
        for match in _TS_EXPORT_EQUALS.finditer(view.source)
    ):
        exports.add("default")
    return TypeScriptSourceScan(
        tuple(imports),
        tuple(sorted(exports)),
        incomplete_dynamic_imports,
        view.incomplete_regions,
        incomplete_public_exports,
    )
