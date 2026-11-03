"""Checks the request shape sent to the Anthropic SDK, without calling the API."""

from types import SimpleNamespace

from groundwork.llm import anthropic_llm
from groundwork.llm.base import WriteRequest
from groundwork.models import Draft


class FakeMessages:
    def __init__(self):
        self.calls = []

    def parse(self, **kw):
        self.calls.append(kw)
        d = Draft(platform="x", format="thread", hook="h", parts=["p"])
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, parsed_output=d,
                               content=[{"type": "text", "text": d.model_dump_json()}])

    def create(self, **kw):
        self.calls.append(kw)
        result = SimpleNamespace(type="web_search_tool_result",
                                 content=[SimpleNamespace(url="https://a"),
                                          SimpleNamespace(url="https://b")])
        cited = SimpleNamespace(type="text", text="t",
                                citations=[SimpleNamespace(url="https://b")])
        return SimpleNamespace(stop_reason="end_turn", content=[result, cited])


def fake_client(monkeypatch):
    msgs = FakeMessages()
    monkeypatch.setattr(anthropic_llm, "_client",
                        lambda: SimpleNamespace(beta=SimpleNamespace(messages=msgs)))
    return msgs


def test_writer_request_and_append_only_revision(monkeypatch, store, templates):
    msgs = fake_client(monkeypatch)
    tpl = templates["x"]
    req = WriteRequest("t", "", "", store, tpl, "thread", tpl.formats["thread"])
    w = anthropic_llm.ClaudeWriter()
    w.write(req)
    first = msgs.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["output_format"] is Draft
    assert first["thinking"] == {"type": "adaptive"} and first["fallbacks"] == "default"
    assert '<source id="S1"' in first["messages"][0]["content"]
    w.revise(req, None, [])
    second = msgs.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[0] == first["messages"][0]


def test_web_researcher_puts_cited_urls_first(monkeypatch):
    msgs = fake_client(monkeypatch)
    urls = anthropic_llm.ClaudeWebResearcher().find_urls("t", 5)
    assert urls == ["https://b", "https://a"]
    assert msgs.calls[0]["tools"][0]["type"] == "web_search_20260209"
