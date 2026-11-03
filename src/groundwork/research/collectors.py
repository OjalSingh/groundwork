"""Source collectors. Each one turns a topic into fetched, quotable documents.

All collectors here use free, keyless, documented endpoints:
  * Wikipedia   - MediaWiki Action API (search + plaintext extracts)
  * arXiv       - export.arxiv.org Atom API (abstracts)
  * Hacker News - hn.algolia.com search, then the linked article is fetched
  * RSS/Atom    - any feeds you list in groundwork.yaml
  * URLs        - seed links you pass by hand (often the best sources)
The Claude web-search collector lives in groundwork.llm.anthropic_llm because it
needs an API key.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from groundwork.models import Source
from groundwork.research.fetch import USER_AGENT, fetch_text

log = logging.getLogger(__name__)
ATOM = "{http://www.w3.org/2005/Atom}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20,
                        event_hooks={"response": [lambda r: r.raise_for_status()]})


class Collector(Protocol):
    name: str

    def collect(self, topic: str, limit: int) -> list[Source]: ...


def source_from_url(url: str, collector: str, client: httpx.Client | None = None) -> Source | None:
    try:
        title, text, meta = fetch_text(url, client)
    except httpx.HTTPError as exc:
        log.warning("skip %s: %s", url, exc)
        return None
    return Source(
        id="",
        url=url,
        title=title or url,
        publisher=meta.get("og:site_name", urlsplit(url).netloc),
        published=meta.get("article:published_time"),
        retrieved_at=_now(),
        collector=collector,
        text=text,
    )


class UrlCollector:
    name = "url"

    def __init__(self, urls: Iterable[str]):
        self.urls = list(urls)

    def collect(self, topic: str, limit: int) -> list[Source]:
        with _client() as c:
            found = [source_from_url(u, self.name, c) for u in self.urls[:limit]]
        return [s for s in found if s]


class WikipediaCollector:
    name = "wikipedia"
    api = "https://en.wikipedia.org/w/api.php"

    def collect(self, topic: str, limit: int) -> list[Source]:
        with _client() as c:
            hits = c.get(
                self.api,
                params={"action": "query", "list": "search", "srsearch": topic,
                        "srlimit": limit, "format": "json"},
            ).json()["query"]["search"]
            out = []
            for hit in hits:
                pages = c.get(
                    self.api,
                    params={"action": "query", "prop": "extracts|info", "explaintext": 1,
                            "inprop": "url", "titles": hit["title"], "format": "json"},
                ).json()["query"]["pages"]
                page = next(iter(pages.values()))
                out.append(Source(
                    id="", url=page.get("fullurl", ""), title=page["title"],
                    publisher="Wikipedia", retrieved_at=_now(), collector=self.name,
                    text=page.get("extract", ""),
                ))
        return out


class ArxivCollector:
    name = "arxiv"
    api = "https://export.arxiv.org/api/query"

    def collect(self, topic: str, limit: int) -> list[Source]:
        with _client() as c:
            resp = c.get(self.api, params={"search_query": f"all:{topic}", "start": 0,
                                           "max_results": limit, "sortBy": "relevance"})
        return parse_arxiv(resp.text)


def parse_arxiv(xml: str) -> list[Source]:
    root = ET.fromstring(xml)
    out = []
    for entry in root.findall(f"{ATOM}entry"):
        authors = ", ".join(a.findtext(f"{ATOM}name", "") for a in entry.findall(f"{ATOM}author"))
        title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
        abstract = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
        out.append(Source(
            id="", url=entry.findtext(f"{ATOM}id", ""), title=title,
            publisher=f"arXiv ({authors})" if authors else "arXiv",
            published=(entry.findtext(f"{ATOM}published") or "")[:10] or None,
            retrieved_at=_now(), collector="arxiv",
            # Abstracts are short; pad the threshold by including the title.
            text=f"{title}.\n{abstract}",
        ))
    return out


class HackerNewsCollector:
    """Finds what practitioners are linking to, then fetches the article itself.

    The HN comments are not used as sources: they are opinions, not evidence.
    """

    name = "hn"
    api = "https://hn.algolia.com/api/v1/search"

    def collect(self, topic: str, limit: int) -> list[Source]:
        with _client() as c:
            hits = c.get(self.api, params={"query": topic, "tags": "story",
                                           "hitsPerPage": limit * 2}).json()["hits"]
            urls = [h["url"] for h in hits if h.get("url")][:limit]
            found = [source_from_url(u, self.name, c) for u in urls]
        return [s for s in found if s]


class RssCollector:
    name = "rss"

    def __init__(self, feeds: Iterable[str]):
        self.feeds = list(feeds)

    def collect(self, topic: str, limit: int) -> list[Source]:
        words = [w.lower() for w in topic.split() if len(w) > 3]
        out: list[Source] = []
        with _client() as c:
            for feed in self.feeds:
                try:
                    items = parse_feed(c.get(feed).text)
                except (httpx.HTTPError, ET.ParseError) as exc:
                    log.warning("feed %s: %s", feed, exc)
                    continue
                for title, link in items:
                    if words and not any(w in title.lower() for w in words):
                        continue
                    src = source_from_url(link, self.name, c)
                    if src:
                        out.append(src)
                    if len(out) >= limit:
                        return out
        return out


def parse_feed(xml: str) -> list[tuple[str, str]]:
    """Return (title, link) pairs from RSS 2.0 or Atom."""
    root = ET.fromstring(xml)
    items = [(i.findtext("title", ""), i.findtext("link", "")) for i in root.iter("item")]
    for e in root.iter(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        href = link.get("href", "") if link is not None else ""
        items.append((e.findtext(f"{ATOM}title", ""), href))
    return [(t.strip(), u.strip()) for t, u in items if u]


REGISTRY = {
    "wikipedia": WikipediaCollector,
    "arxiv": ArxivCollector,
    "hn": HackerNewsCollector,
}
