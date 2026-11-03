"""Shared fixtures. Source texts here are synthetic test data, not real citations."""

from datetime import datetime, timezone

import pytest

from groundwork.config import Config
from groundwork.models import Source
from groundwork.platforms.registry import load_templates
from groundwork.research.store import SourceStore

TEXT_A = (
    "Consistent hashing maps both keys and servers onto the same circular hash space. "
    "Each key is stored on the first server found by moving clockwise around the ring from "
    "the key's position. When a server is added, only the keys between it and its "
    "predecessor have to move. In a test cluster of 10 nodes, adding one node moved about "
    "9% of keys instead of nearly all of them. Virtual nodes give each physical server many "
    "positions on the ring, which evens out the load between servers of different sizes. "
) * 2

TEXT_B = (
    "A naive scheme assigns a key to server number hash(key) mod N. That works until N "
    "changes. Adding a fifth server to a four-server pool remaps roughly 80% of keys, which "
    "empties caches all at once and sends a burst of traffic to the database. Rendezvous "
    "hashing is an alternative that scores every server for each key and picks the highest "
    "score. Both approaches keep remapping proportional to the change in cluster size. "
) * 2


@pytest.fixture
def store() -> SourceStore:
    s = SourceStore()
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    s.add(Source(id="", url="https://example.com/ring", title="Rings and keys",
                 publisher="Example Eng Blog", retrieved_at=now, collector="url", text=TEXT_A))
    s.add(Source(id="", url="https://example.org/mod-n", title="Why mod N breaks",
                 publisher="Example Docs", retrieved_at=now, collector="url", text=TEXT_B))
    return s


@pytest.fixture
def templates():
    return load_templates()


@pytest.fixture
def cfg() -> Config:
    return Config(collectors=[], use_web_search=False, timezone="UTC")
