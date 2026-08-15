from __future__ import annotations

from router_support.route_read_paths import build_precise_read_targets


def test_exact_file_with_one_public_symbol_is_digest_bound(tmp_path) -> None:
    source = tmp_path / "app/service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def execute_workflow():\n    return 'ok'\n", encoding="utf-8")

    report = build_precise_read_targets(tmp_path, ["app/service.py"])

    assert report["must_read_targets"] == [
        {
            "path": "app/service.py",
            "symbol": "execute_workflow",
            "content_digest": report["must_read_targets"][0]["content_digest"],
            "line_hint": 1,
            "reason": "routed required read",
            "resolution_status": "resolved",
        }
    ]
    assert len(report["must_read_targets"][0]["content_digest"]) == 64
    assert report["inventory_targets"] == []


def test_directory_is_inventory_target_not_full_read(tmp_path) -> None:
    (tmp_path / "app/services").mkdir(parents=True)

    report = build_precise_read_targets(tmp_path, ["app/services"])

    assert report["must_read_targets"] == []
    assert report["inventory_targets"] == [
        {
            "path": "app/services",
            "reason": "inventory routed directory before selecting a file",
        }
    ]


def test_ambiguous_file_stays_unresolved_with_query_command(tmp_path) -> None:
    source = tmp_path / "app/service.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def first():\n    pass\n\ndef second():\n    pass\n",
        encoding="utf-8",
    )

    report = build_precise_read_targets(tmp_path, ["app/service.py"])

    target = report["must_read_targets"][0]
    assert target["resolution_status"] == "unresolved"
    assert target["symbol"] is None
    assert target["candidate_symbols"] == ["first", "second"]
    assert report["unresolved_queries"][0]["command"].startswith("rg -n")


def test_content_change_invalidates_read_digest(tmp_path) -> None:
    source = tmp_path / "app/service.py"
    source.parent.mkdir(parents=True)
    source.write_text("def execute():\n    return 1\n", encoding="utf-8")
    before = build_precise_read_targets(tmp_path, ["app/service.py"])
    source.write_text("def execute():\n    return 2\n", encoding="utf-8")
    after = build_precise_read_targets(tmp_path, ["app/service.py"])

    assert (
        before["must_read_targets"][0]["content_digest"]
        != after["must_read_targets"][0]["content_digest"]
    )
