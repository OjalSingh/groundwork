"""Interactive design questions, previews and theme saving.

The wizard talks to an `Asker`, so the same flow runs in a terminal (ClickAsker) and in
tests (ScriptedAsker).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import click
import yaml
from PIL import Image

from groundwork.design.render import render_slide
from groundwork.design.theme import (
    COLOR_FIELDS,
    Theme,
    load_presets,
    save_theme,
    theme_warnings,
)
from groundwork.models import Post, Slide

SAMPLE = [
    ("carousel", Slide(heading="Why mod-N sharding breaks",
                       body="Add one server to a pool of four and most keys land somewhere new.",
                       footnote="Source: Example Docs")),
    ("carousel", Slide(heading="Rings fix it",
                       body="Keys and servers share one circle. Only the keys next to a new "
                            "server move.", footnote="Source: Example Eng Blog")),
    ("quote_card", Slide(heading="", body="Only the keys between the new server and its "
                         "predecessor have to move.", footnote="Source: Example Eng Blog")),
]
EDITABLE = [
    ("colours", "Change colours (background, text, accent, muted)"),
    ("fonts", "Change fonts (names used in Canva, and the local render style)"),
    ("align", "Text alignment: left or centred"),
    ("accent_style", "Accent shape: bar, underline, block or none"),
    ("cover_style", "Cover slide: same as the rest, or inverted colours"),
    ("slide_counter", "Show slide numbers (1/6)"),
    ("handle", "Your handle printed on every slide"),
    ("logo", "A logo image (PNG) on every slide"),
    ("done", "I'm happy with it"),
]


class Asker(Protocol):
    def choose(self, prompt: str, options: list[str], default: str | None = None) -> str: ...
    def text(self, prompt: str, default: str = "") -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def say(self, message: str) -> None: ...


class ClickAsker:
    def choose(self, prompt, options, default=None):
        return click.prompt(prompt, type=click.Choice(options, case_sensitive=False),
                            default=default, show_choices=True)

    def text(self, prompt, default=""):
        return click.prompt(prompt, default=default, show_default=bool(default))

    def confirm(self, prompt, default=True):
        return click.confirm(prompt, default=default)

    def say(self, message):
        click.echo(message)


class ScriptedAsker:
    """Answers from a queue; records everything said. Used by tests and demos."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.log: list[str] = []

    def _next(self, default):
        return self.answers.pop(0) if self.answers else default

    def choose(self, prompt, options, default=None):
        value = self._next(default)
        assert value in options, f"{value!r} not in {options} for {prompt!r}"
        return value

    def text(self, prompt, default=""):
        return self._next(default)

    def confirm(self, prompt, default=True):
        return self._next(default)

    def say(self, message):
        self.log.append(message)


def preview_sheet(theme: Theme, out_path: Path, size: tuple[int, int] = (1080, 1350)) -> Path:
    """Render three sample slides side by side so a theme can be judged at a glance."""
    imgs = [render_slide(s, size, theme, i + 1, len(SAMPLE), kind)
            for i, (kind, s) in enumerate(SAMPLE)]
    scale = 0.4
    tw, th = int(size[0] * scale), int(size[1] * scale)
    gap = 24
    sheet = Image.new("RGB", (len(imgs) * tw + (len(imgs) + 1) * gap, th + 2 * gap), "#E5E7EB")
    for i, img in enumerate(imgs):
        sheet.paste(img.resize((tw, th)), (gap + i * (tw + gap), gap))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def describe_presets(presets: dict[str, Theme]) -> str:
    return "\n".join(f"  {name:<11} {t.background} / {t.foreground} / {t.accent}  {t.description}"
                     for name, t in presets.items())


def _tweak(theme: Theme, field: str, ask: Asker) -> Theme:
    upd: dict = {}
    if field == "colours":
        for name in COLOR_FIELDS:
            upd[name] = ask.text(f"{name} colour (#RRGGBB)", getattr(theme, name))
    elif field == "fonts":
        upd["heading_font"] = ask.text("Heading font name (as it appears in Canva)",
                                       theme.heading_font)
        upd["body_font"] = ask.text("Body font name (as it appears in Canva)", theme.body_font)
        upd["font_family"] = ask.choose("Render style for the PNG previews",
                                        ["sans", "serif", "mono"], theme.font_family)
        if ask.confirm("Do you have the font files and want PNGs rendered with them?", False):
            upd["heading_font_file"] = ask.text("Path to the bold/heading font file") or None
            upd["body_font_file"] = ask.text("Path to the regular/body font file") or None
    elif field == "align":
        upd["align"] = ask.choose("Alignment", ["left", "center"], theme.align)
    elif field == "accent_style":
        upd["accent_style"] = ask.choose("Accent shape", ["bar", "underline", "block", "none"],
                                         theme.accent_style)
    elif field == "cover_style":
        upd["cover_style"] = ask.choose("Cover slide", ["same", "inverted"], theme.cover_style)
    elif field == "slide_counter":
        upd["slide_counter"] = ask.confirm("Show slide numbers?", theme.slide_counter)
    elif field == "handle":
        upd["handle"] = ask.text("Handle, e.g. @yourname (blank for none)", theme.handle)
    elif field == "logo":
        path = ask.text("Path to a PNG logo (blank for none)", theme.logo or "")
        upd["logo"] = path or None
    try:
        return Theme.model_validate({**theme.model_dump(), **upd})
    except ValueError as exc:
        ask.say(f"Not applied: {exc}")
        return theme


def run_wizard(ask: Asker, preview_dir: Path, start: Theme | None = None,
               themes_dir: Path | None = None, max_rounds: int = 12) -> Theme:
    """Ask design questions until the user is happy; returns the final theme."""
    presets = load_presets(themes_dir)
    if start is None:
        ask.say("Theme presets:\n" + describe_presets(presets))
        name = ask.choose("Start from which preset?", list(presets), "midnight")
        theme = presets[name]
    else:
        theme = start
    for _ in range(max_rounds):
        ask.say(f"Preview: {preview_sheet(theme, preview_dir / 'theme-preview.png')}")
        for warning in theme_warnings(theme):
            ask.say(f"Heads up: {warning}")
        field = ask.choose("What would you like to change?", [k for k, _ in EDITABLE], "done")
        if field == "done":
            break
        theme = _tweak(theme, field, ask)
    return theme


def save_wizard_result(theme: Theme, config_path: Path, save_as: str | None,
                       themes_dir: Path) -> list[Path]:
    """Persist the theme: an optional named preset file, and groundwork.yaml pointing at it."""
    written = []
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    raw = raw or {}
    presets = load_presets(themes_dir)
    if save_as:
        theme = theme.model_copy(update={"name": save_as})
        target = themes_dir / f"{save_as}.yaml"
        save_theme(theme, target)
        written.append(target)
        raw["theme_preset"] = save_as
        raw["themes_dir"] = str(themes_dir.relative_to(config_path.parent)
                                if themes_dir.is_relative_to(config_path.parent) else themes_dir)
        raw.pop("theme", None)
    else:
        base = presets.get(theme.name)
        raw["theme_preset"] = theme.name if base else None
        diff = theme.model_dump(exclude_none=True)
        if base:
            base_d = base.model_dump(exclude_none=True)
            diff = {k: v for k, v in diff.items() if base_d.get(k) != v}
        raw["theme"] = diff
        if raw["theme_preset"] is None:
            raw.pop("theme_preset")
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    written.append(config_path)
    return written


def ask_for_images(post: Post, ask: Asker) -> None:
    """For each slide that needs a visual, ask for an image path (blank = do it in Canva)."""
    for i, slide in enumerate(post.draft.design.slides, 1):
        if not slide.visual or slide.image:
            continue
        ask.say(f"{post.id}, slide {i} needs: {slide.visual}")
        path = ask.text("Image file for this slide (blank to build it in Canva)", "")
        if path and Path(path).exists():
            slide.image = str(Path(path).resolve())
        elif path:
            ask.say(f"No file at {path}; leaving it for Canva.")
