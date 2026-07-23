from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import router_core


def test_java_import_parser_handles_static_and_wildcard_without_comments(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Example.java"
    source.write_text(
        '''
package sample;
import static foo.Bar.VALUE;
import foo.api.*;
/*
import fake.Commented;
*/
class Example {
  String text = "import fake.StringValue;";
  String block = """
import fake.TextBlock;
""";
}
'''.lstrip(),
        encoding="utf-8",
    )

    assert router_core.parse_java_imports(source) == [
        "foo.Bar.VALUE",
        "foo.api.*",
    ]
