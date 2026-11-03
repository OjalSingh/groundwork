"""Fetch a URL and turn it into plain text we can ground claims against.

Deliberately dependency-light: stdlib HTMLParser, no headless browser. Pages that
need JavaScript to render simply produce too little text and get dropped by the
SourceStore, which is the right outcome for a pipeline that must quote sources.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser

import httpx

USER_AGENT = "groundwork-research/0.1 (+https://github.com/OjalSingh/groundwork)"
SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br", "tr", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta[key.lower()] = a["content"]
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str, dict[str, str]]:
    """Return (title, text, meta) for an HTML document."""
    parser = _TextExtractor()
    parser.feed(html)
    raw = unescape("".join(parser.parts))
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in raw.splitlines()]
    # Keep lines that look like prose; menus and button labels are short.
    text = "\n".join(line for line in lines if len(line) > 40 or line.endswith((".", ":", "?")))
    title = parser.meta.get("og:title") or parser.title.strip()
    return title, text, parser.meta


def fetch(url: str, client: httpx.Client | None = None, timeout: float = 20.0) -> httpx.Response:
    own = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=timeout
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp
    finally:
        if own:
            client.close()


def fetch_text(url: str, client: httpx.Client | None = None) -> tuple[str, str, dict[str, str]]:
    resp = fetch(url, client)
    ctype = resp.headers.get("content-type", "")
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        # No PDF text extraction yet; better to skip than to ground against garbage.
        raise httpx.HTTPError(f"PDF not supported yet: {url}")
    if "html" in ctype or resp.text.lstrip().startswith("<"):
        return html_to_text(resp.text)
    return url, resp.text, {}
