from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from groundwork.design.theme import Theme, resolve_theme


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
    theme_preset: str | None = None
    themes_dir: str | None = None     # your own preset YAMLs, same format as the built-ins
    theme: Theme = Field(default_factory=Theme)

    @model_validator(mode="before")
    @classmethod
    def _merge_theme(cls, data):
        """`theme_preset` gives the base; fields under `theme:` override it."""
        if isinstance(data, dict) and data.get("theme_preset"):
            extra = Path(data["themes_dir"]) if data.get("themes_dir") else None
            overrides = data.get("theme") if isinstance(data.get("theme"), dict) else {}
            data = {**data, "theme": resolve_theme(data["theme_preset"], overrides, extra)}
        return data

    @classmethod
    def load(cls, path: Path | None) -> Config:
        if path is None:
            default = Path("groundwork.yaml")
            path = default if default.exists() else None
        if path is None:
            return cls()
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("themes_dir") and not Path(raw["themes_dir"]).is_absolute():
            raw["themes_dir"] = str((path.parent / raw["themes_dir"]).resolve())
        cfg = cls.model_validate(raw)
        for attr in ("templates_dir", "themes_dir"):
            value = getattr(cfg, attr)
            if value and not Path(value).is_absolute():
                setattr(cfg, attr, str((path.parent / value).resolve()))
        return cfg
