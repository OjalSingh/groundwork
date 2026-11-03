"""Collect, dedupe and number sources so drafts can cite them as S1, S2, ..."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from groundwork.models import Source

MIN_TEXT_CHARS = 400


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = "&".join(
        q for q in parts.query.split("&") if q and not q.lower().startswith(("utm_", "ref="))
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))


class SourceStore:
    def __init__(self) -> None:
        self._by_url: dict[str, Source] = {}

    def __len__(self) -> int:
        return len(self._by_url)

    def __iter__(self):
        return iter(self._by_url.values())

    def get(self, source_id: str) -> Source | None:
        return next((s for s in self._by_url.values() if s.id == source_id), None)

    def add(self, source: Source) -> Source | None:
        """Add a source; returns it with its assigned id, or None if rejected."""
        key = canonical_url(source.url)
        if key in self._by_url:
            return self._by_url[key]
        if len(source.text) < MIN_TEXT_CHARS:
            return None
        stored = source.model_copy(update={"id": f"S{len(self._by_url) + 1}"})
        self._by_url[key] = stored
        return stored

    def save(self, path: Path) -> None:
        path.write_text(json.dumps([s.model_dump(mode="json") for s in self], indent=2))

    @classmethod
    def load(cls, path: Path) -> SourceStore:
        store = cls()
        for raw in json.loads(path.read_text()):
            src = Source.model_validate(raw)
            store._by_url[canonical_url(src.url)] = src
        return store

    def bibliography(self) -> str:
        lines = []
        for s in self:
            who = f" ({s.publisher})" if s.publisher else ""
            when = f", {s.published}" if s.published else ""
            lines.append(f"[{s.id}] {s.title}{who}{when}. {s.url}")
        return "\n".join(lines)
