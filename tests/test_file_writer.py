import json

from groundwork.llm.file_writer import FileWriter
from groundwork.models import Claim, DesignSpec, Draft, Slide
from groundwork.pipeline import run


def draft(statement, quote, hook="Keys on a ring."):
    return Draft(platform="x", format="thread", hook=hook,
                 parts=[statement + " [S1]"] * 4,
                 claims=[Claim(statement=statement, source_id="S1", quote=quote)],
                 design=DesignSpec(kind="header", slides=[Slide(heading="Keys on a ring")],
                                   alt_text="Title card."))


GOOD = "When a server is added, only the keys between it and its predecessor have to move."


def test_file_writer_replays_revision_loop(tmp_path, store, templates, cfg):
    bad = draft("A server move touches 95% of keys.", "Nearly every key moves when a server is added.")
    good = draft("Only nearby keys move.", GOOD)
    f = tmp_path / "drafts.json"
    f.write_text(json.dumps({"x:thread": [bad.model_dump(), good.model_dump()]}), encoding="utf-8")
    (post,) = run("consistent hashing", ["x:thread"], cfg, templates, FileWriter(f), store,
                  tmp_path / "runs").posts
    assert post.revisions == 1 and post.status.value == "ready"
    assert post.draft.claims[0].quote == GOOD


def test_missing_target_is_a_clear_error(tmp_path, store, templates, cfg):
    f = tmp_path / "d.json"
    f.write_text(json.dumps({"linkedin:post": draft("a", GOOD).model_dump()}), encoding="utf-8")
    import pytest
    with pytest.raises(KeyError, match="x:thread"):
        run("t", ["x:thread"], cfg, templates, FileWriter(f), store, tmp_path / "r")
