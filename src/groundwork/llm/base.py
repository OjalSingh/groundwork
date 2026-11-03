from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from groundwork.models import Draft, Finding
from groundwork.platforms.registry import FormatTemplate, PlatformTemplate
from groundwork.research.store import SourceStore


@dataclass
class WriteRequest:
    topic: str
    brief: str
    voice: str
    store: SourceStore
    platform: PlatformTemplate
    format_name: str
    format: FormatTemplate


class Writer(Protocol):
    def write(self, req: WriteRequest) -> Draft: ...

    def revise(self, req: WriteRequest, draft: Draft, findings: list[Finding]) -> Draft: ...


class WebResearcher(Protocol):
    def find_urls(self, topic: str, limit: int) -> list[str]: ...
