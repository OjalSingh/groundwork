import httpx

from groundwork.research import collectors
from groundwork.research.fetch import html_to_text
from groundwork.research.store import SourceStore, canonical_url

ARXIV = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/abs/1234.5678v1</id><published>2020-01-02T00:00:00Z</published>
<title>A Paper</title><summary>We study rings.</summary><author><name>Ada L</name></author>
</entry></feed>"""


def test_html_to_text_drops_chrome():
    html = """<html><head><title>T</title><meta property="og:site_name" content="Site"></head>
    <body><nav>Home About Contact links here for the menu</nav>
    <article><p>This is a real paragraph of article text that should survive extraction.</p>
    <script>var x = 'should not appear anywhere in the output at all';</script></article>
    <footer>Copyright footer text that is long enough to pass the filter</footer></body></html>"""
    title, text, meta = html_to_text(html)
    assert title == "T" and meta["og:site_name"] == "Site"
    assert "real paragraph" in text and "should not appear" not in text
    assert "Copyright" not in text and "Home About" not in text


def test_canonical_url_strips_tracking():
    assert canonical_url("HTTPS://Ex.com/a/?utm_source=x&id=2#frag") == "https://ex.com/a?id=2"


def test_store_dedupes_and_rejects_thin(store):
    assert [s.id for s in store] == ["S1", "S2"]
    again = store.get("S1").model_copy(update={"url": "https://example.com/ring/?utm_x=1"})
    assert store.add(again).id == "S1" and len(store) == 2
    thin = store.get("S1").model_copy(update={"url": "https://x.y", "text": "short"})
    assert store.add(thin) is None


def test_store_roundtrip(tmp_path, store):
    store.save(tmp_path / "s.json")
    loaded = SourceStore.load(tmp_path / "s.json")
    assert loaded.get("S2").title == store.get("S2").title


def test_parse_arxiv():
    (s,) = collectors.parse_arxiv(ARXIV)
    assert s.publisher == "arXiv (Ada L)" and s.published == "2020-01-02"
    assert "We study rings." in s.text


def test_parse_feed_rss_and_atom():
    rss = "<rss><channel><item><title>A</title><link>https://a</link></item></channel></rss>"
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>B</title>'
            '<link href="https://b"/></entry></feed>')
    assert collectors.parse_feed(rss) == [("A", "https://a")]
    assert collectors.parse_feed(atom) == [("B", "https://b")]


def test_wikipedia_collector_with_mock(monkeypatch):
    extract = "Consistent hashing is a technique. " * 30

    def handler(request: httpx.Request):
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json={"query": {"search": [{"title": "Consistent hashing"}]}})
        return httpx.Response(200, json={"query": {"pages": {"1": {
            "title": "Consistent hashing", "fullurl": "https://en.wikipedia.org/wiki/CH",
            "extract": extract}}}})

    monkeypatch.setattr(collectors, "_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    (s,) = collectors.WikipediaCollector().collect("consistent hashing", 1)
    assert s.publisher == "Wikipedia" and s.text == extract


def test_plain_text_sources_are_made_quotable():
    from groundwork.research.fetch import clean_plain, plain_publisher, plain_title
    raw = ("  * {@code consistentHash} will be a poor fit: It provides\n"
           "  *       no way to say which bucket is going away.\n// note")
    assert "consistentHash will be a poor fit: It provides no way".split()[0] in clean_plain(raw)
    assert "* " not in clean_plain(raw) and "{@code" not in clean_plain(raw)
    url = "https://raw.githubusercontent.com/envoyproxy/envoy/main/docs/x.rst"
    assert plain_publisher(url) == "envoyproxy/envoy" and plain_title(url, "text") == "x.rst"
    assert plain_title(url, "# Consistent\nbody") == "Consistent"
