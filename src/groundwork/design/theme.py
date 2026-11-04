"""Themes: built-in presets, user presets, and per-field tweaks.

A theme is plain data (colours, fonts, layout switches). Presets are YAML files in
design/presets/ (built in) and in a project's `themes_dir` (yours). A config picks a
preset with `theme_preset: paper` and can override any field under `theme:`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator

PRESET_DIR = Path(__file__).parent / "presets"

# Local font files used for rendering PNGs. The *names* (heading_font/body_font) are what
# the Canva guide tells you to pick, so they can be fonts we don't have locally.
FONT_CANDIDATES = {
    ("sans", "bold"): [
        "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    ("sans", "regular"): [
        "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    ("serif", "bold"): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/Library/Fonts/Georgia Bold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
    ],
    ("serif", "regular"): [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/Library/Fonts/Georgia.ttf",
        "C:/Windows/Fonts/georgia.ttf",
    ],
    ("mono", "bold"): [
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consolab.ttf",
    ],
    ("mono", "regular"): [
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "C:/Windows/Fonts/consola.ttf",
    ],
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
COLOR_FIELDS = ("background", "foreground", "accent", "muted")


class Theme(BaseModel):
    name: str = "midnight"
    description: str = ""
    background: str = "#0F172A"
    foreground: str = "#F8FAFC"
    accent: str = "#38BDF8"
    muted: str = "#94A3B8"
    heading_font: str = "Inter"            # the name to pick in Canva
    body_font: str = "Inter"
    font_family: Literal["sans", "serif", "mono"] = "sans"   # which local font renders it
    heading_font_file: str | None = None   # point at your own .ttf/.otf to render exactly
    body_font_file: str | None = None
    align: Literal["left", "center"] = "left"
    accent_style: Literal["bar", "underline", "block", "none"] = "bar"
    cover_style: Literal["same", "inverted"] = "same"   # first slide swaps bg/accent
    slide_counter: bool = True
    handle: str = ""                       # e.g. @yourname, printed on every slide
    logo: str | None = None                # path to a PNG, drawn top right

    @field_validator("background", "foreground", "accent", "muted")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX.match(v):
            raise ValueError(f"{v!r} is not a #RRGGBB colour")
        return v.upper()

    def font_file(self, weight: str) -> str | None:
        explicit = self.heading_font_file if weight == "bold" else self.body_font_file
        if explicit:
            return explicit
        return next((p for p in FONT_CANDIDATES[(self.font_family, weight)] if Path(p).exists()),
                    None)

    def inverted(self) -> Theme:
        """Colours for a cover slide: accent becomes the background."""
        return self.model_copy(update={"background": self.accent,
                                       "foreground": self.background,
                                       "accent": self.background,
                                       "muted": self.background})


def contrast_ratio(a: str, b: str) -> float:
    def lum(hex_: str) -> float:
        rgb = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def theme_warnings(theme: Theme) -> list[str]:
    """Readability checks. Phone-sized slides need real contrast."""
    out = []
    r = contrast_ratio(theme.foreground, theme.background)
    if r < 4.5:
        out.append(f"Text/background contrast is {r:.1f}:1; aim for at least 4.5:1.")
    r = contrast_ratio(theme.muted, theme.background)
    if r < 3:
        out.append(f"Muted/background contrast is {r:.1f}:1; footnotes will be hard to read.")
    if theme.accent_style != "none":
        r = contrast_ratio(theme.accent, theme.background)
        if r < 3:
            out.append(f"Accent/background contrast is {r:.1f}:1; the accent will vanish.")
    if theme.cover_style == "inverted":
        inv = theme.inverted()
        r = contrast_ratio(inv.foreground, inv.background)
        if r < 4.5:
            out.append(f"Inverted cover contrast is {r:.1f}:1; pick a darker accent or "
                       "set cover_style to same.")
    return out


def load_presets(extra_dir: Path | None = None) -> dict[str, Theme]:
    presets: dict[str, Theme] = {}
    for d in [PRESET_DIR] + ([extra_dir] if extra_dir else []):
        if not d or not d.exists():
            continue
        for path in sorted(d.glob("*.y*ml")):
            raw = yaml.safe_load(path.read_text()) or {}
            raw.setdefault("name", path.stem)
            presets[raw["name"]] = Theme.model_validate(raw)
    return presets


def resolve_theme(preset: str | None, overrides: dict | None = None,
                  extra_dir: Path | None = None) -> Theme:
    """Start from a preset (if any) and apply overrides on top."""
    data: dict = {}
    if preset:
        presets = load_presets(extra_dir)
        if preset not in presets:
            raise KeyError(f"Unknown theme preset {preset!r}; options: {sorted(presets)}")
        data = presets[preset].model_dump()
    data.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return Theme.model_validate(data)


def save_theme(theme: Theme, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = theme.model_dump(exclude_none=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
