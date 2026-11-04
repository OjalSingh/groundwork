"""Load platform templates from YAML so requirements can change without code changes.

Built-in templates live in groundwork/platforms/templates. A project can override
or add platforms by dropping YAML files in its own templates directory (see
`templates_dir` in groundwork.yaml); a file with the same `name` replaces the
built-in one entirely.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

BUILTIN_DIR = Path(__file__).parent / "templates"
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class PartRules(BaseModel):
    min: int = 1
    max: int = 1
    max_chars: int
    total_max_chars: int | None = None


class HashtagRules(BaseModel):
    max: int = 0
    hard_max: int | None = None


class DesignRules(BaseModel):
    kind: str = "none"
    size: tuple[int, int] = (1080, 1350)
    min_slides: int = 1
    max_slides: int = 1
    hard_max_slides: int | None = None


class FormatTemplate(BaseModel):
    description: str
    parts: PartRules
    hook_max_chars: int = 280
    hashtags: HashtagRules = Field(default_factory=HashtagRules)
    citations: str = "inline"
    design: DesignRules = Field(default_factory=DesignRules)
    guidance: str = ""


class PostingWindow(BaseModel):
    days: list[str]
    times: list[str]


class PlatformTemplate(BaseModel):
    name: str
    display_name: str
    formats: dict[str, FormatTemplate]
    posting_windows: list[PostingWindow] = Field(default_factory=list)
    max_posts_per_day: int = 1

    def format(self, name: str | None = None) -> tuple[str, FormatTemplate]:
        if name is None:
            name = next(iter(self.formats))
        if name not in self.formats:
            raise KeyError(f"{self.name} has no format {name!r}; options: {list(self.formats)}")
        return name, self.formats[name]


def load_templates(extra_dir: Path | None = None) -> dict[str, PlatformTemplate]:
    templates: dict[str, PlatformTemplate] = {}
    dirs = [BUILTIN_DIR] + ([extra_dir] if extra_dir else [])
    for d in dirs:
        for path in sorted(d.glob("*.y*ml")):
            tpl = PlatformTemplate.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            for w in tpl.posting_windows:
                bad = [x for x in w.days if x not in DAYS]
                if bad:
                    raise ValueError(f"{path}: unknown day(s) {bad}")
            templates[tpl.name] = tpl
    return templates
