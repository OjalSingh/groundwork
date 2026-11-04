import json

import pytest
from click.testing import CliRunner

from groundwork.cli import main
from groundwork.llm.base import WriteRequest
from groundwork.manual import build_prompt, extract_json, parse_draft

GOOD_QUOTE = "When a server is added, only the keys between it and its predecessor have to move."


def reply(quote=GOOD_QUOTE, statement="Only nearby keys move when a server is added"):
    return json.dumps({
        "platform": "x", "format": "thread", "title": "Rings", "hook": "Keys on a ring.",
        "parts": ["Only nearby keys move. [S1]"] * 4,
        "claims": [{"statement": statement, "source_id": "S1", "quote": quote}],
        "design": {"kind": "header", "alt_text": "Title card.",
                   "slides": [{"heading": "Keys on a ring", "body": "", "footnote": ""}]},
    })


def test_extract_json_variants():
    obj = {"a": 1}
    assert extract_json('Sure!\n```json\n{"a": 1}\n```\nHope it helps') == obj
    assert extract_json('Here you go: {"a": 1} thanks') == obj
    with pytest.raises(ValueError, match="no JSON"):
        extract_json("I could not do that")
    with pytest.raises(ValueError, match="invalid"):
        extract_json('{"a": 1,}')


def test_parse_draft_reports_schema_problems():
    with pytest.raises(ValueError, match="hook"):
        parse_draft('{"platform": "x", "format": "thread", "parts": []}')


def test_prompt_has_sources_rules_and_schema(store, templates):
    tpl = templates["x"]
    text = build_prompt(WriteRequest("rings", "", "", store, tpl, "thread", tpl.formats["thread"]))
    assert '<source id="S1"' in text and "Reply with ONE JSON object" in text
    assert '"claims"' in text and "280 characters" in text


def test_prompt_then_import_roundtrip(tmp_path, store, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store.save(tmp_path / "sources.json")
    runner = CliRunner()
    r = runner.invoke(main, ["prompt", "rings", "-p", "x:thread", "--sources", "sources.json"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "manual" / "prompt-x-thread.md").exists()

    (tmp_path / "good.txt").write_text("```json\n" + reply() + "\n```")
    r = runner.invoke(main, ["import", "good.txt", "--topic", "rings", "--sources",
                             "sources.json"])
    assert r.exit_code == 0, r.output
    assert "ready" in r.output and (tmp_path / "runs").exists()

    (tmp_path / "bad.txt").write_text(reply(quote="Keys move to the nearest server on the ring."))
    r = runner.invoke(main, ["import", "bad.txt", "--topic", "rings2", "--sources", "sources.json"])
    assert r.exit_code == 1 and "needs a fix" in r.output
    fixes = list((tmp_path / "runs").glob("*rings2*/posts/fix-*.md"))
    assert fixes and "grounding.quote_not_found" in fixes[0].read_text()
    assert "corrected JSON" in fixes[0].read_text()


def test_import_unusable_reply_tells_you_what_to_paste_back(tmp_path, store, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store.save(tmp_path / "sources.json")
    (tmp_path / "junk.txt").write_text("Sorry, I can't help with that.")
    r = CliRunner().invoke(main, ["import", "junk.txt", "--topic", "t", "--sources", "sources.json"])
    assert r.exit_code == 1 and "Paste this back" in r.output
