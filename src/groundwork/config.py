from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from groundwork.design.theme import Theme


class Config(BaseModel):
    voice: str = ""
    timezone: str = "UTC"
    collectors: list[str] = Field(default_factory=lambda: ["wikipedia", "arxiv", "hn"])
    use_web_search: bool = True
    sources_per_collector: int = 4
    rss_feeds: list[str] = Field(default_factory=list)
    extra_banned: list[str] = Field(default_factory=list)
    templates_dir: str | None = None
    model: str = "claude-opus-5-5"
    effort: str = "high"
    max_revisions: int = 2
    theme: Theme = Field(default_factory=Theme)

    @classmethod
    def load(cls, path: Path | None) -> Config:
        if path is None:
            default = Path("groundwork.yaml")
            path = default if default.exists() else None
        if path is None:
            return cls()
        cfg = cls.model_validate(yaml.safe_load(path.read_text()) or {})
        if cfg.templates_dir and not Path(cfg.templates_dir).is_absolute():
            cfg.templates_dir = str((path.parent / cfg.templates_dir).resolve())
        return cfg
