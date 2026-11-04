"""Render design specs to PNG (and PDF for document carousels) with Pillow.

Text layout only: headings, body, footnotes, slide counters and a sources slide.
Anything that needs a real diagram or photo is drawn as a labelled placeholder and
spelled out in the Canva guide instead of being faked.
"""

from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from groundwork.design.theme import Theme
from groundwork.models import Post, Slide
from groundwork.research.store import SourceStore

MARGIN = 0.08


def _font(theme: Theme, weight: str, size: int):
    path = theme.font_file(weight)
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                line = trial
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def _fit(draw, text, theme, weight, width, max_height, start, minimum=18):
    """Largest font size at which `text` fits in the box."""
    size = start
    while size > minimum:
        font = _font(theme, weight, size)
        lines = _wrap(draw, text, font, width)
        if len(lines) * size * 1.3 <= max_height:
            return font, lines, size
        size -= 2
    font = _font(theme, weight, minimum)
    return font, _wrap(draw, text, font, width), minimum


def _draw_lines(d, lines, font, fs, x, y, width, theme, fill, step=1.3):
    for line in lines:
        if theme.align == "center":
            d.text((x + width / 2, y), line, font=font, fill=fill, anchor="ma")
        else:
            d.text((x, y), line, font=font, fill=fill)
        y += int(fs * step)
    return y


def _paste_image(img: Image.Image, path: str, box: tuple[int, int, int, int]) -> bool:
    try:
        pic = Image.open(path).convert("RGBA")
    except OSError:
        return False
    x0, y0, x1, y1 = box
    pic.thumbnail((x1 - x0, y1 - y0))
    img.paste(pic, (x0 + (x1 - x0 - pic.width) // 2, y0 + (y1 - y0 - pic.height) // 2), pic)
    return True


def render_slide(slide: Slide, size: tuple[int, int], theme: Theme, index: int, total: int,
                 kind: str) -> Image.Image:
    w, h = size
    if index == 1 and theme.cover_style == "inverted" and total > 1 or (
            kind in ("quote_card", "header") and theme.cover_style == "inverted"):
        theme = theme.inverted()
    img = Image.new("RGB", size, theme.background)
    d = ImageDraw.Draw(img)
    m = int(w * MARGIN)
    inner = w - 2 * m
    y = m
    center = theme.align == "center"
    bar_w, bar_h = int(w * 0.12), max(6, h // 160)
    bar_x = (w - bar_w) // 2 if center else m

    if theme.accent_style == "bar":
        d.rectangle([bar_x, y, bar_x + bar_w, y + bar_h], fill=theme.accent)
    elif theme.accent_style == "block":
        d.rectangle([0, 0, w, int(h * 0.025)], fill=theme.accent)
    y += int(h * 0.05)

    if theme.logo and Path(theme.logo).exists():
        lh = int(h * 0.05)
        _paste_image(img, theme.logo, (w - m - lh * 3, m - lh // 2, w - m, m + lh))

    if kind == "quote_card":
        qfont = _font(theme, "bold", int(h * 0.15))
        d.text((w / 2 if center else m, y - int(h * 0.02)), "\u201c", font=qfont,
               fill=theme.accent, anchor="ma" if center else "la")
        y += int(h * 0.12)

    if slide.heading:
        font, lines, fs = _fit(d, slide.heading, theme, "bold", inner, h * 0.28, int(h * 0.075))
        y = _draw_lines(d, lines, font, fs, m, y, inner, theme, theme.foreground, 1.25)
        if theme.accent_style == "underline":
            uw = int(w * 0.18)
            ux = (w - uw) // 2 if center else m
            d.rectangle([ux, y + 4, ux + uw, y + 4 + bar_h], fill=theme.accent)
            y += bar_h + 10
        y += int(h * 0.03)

    footer_h = int(h * 0.1)
    visual_h = int(h * 0.3) if (slide.visual or slide.image) else 0
    if slide.body:
        avail = h - y - m - footer_h - visual_h
        start = int(h * (0.05 if kind == "quote_card" else 0.042))
        font, lines, fs = _fit(d, slide.body, theme, "regular", inner, avail, start)
        _draw_lines(d, lines, font, fs, m, y, inner, theme, theme.foreground)

    if visual_h:
        top = h - m - footer_h - visual_h + int(h * 0.02)
        box = (m, top, w - m, top + visual_h - int(h * 0.03))
        if not (slide.image and _paste_image(img, slide.image, box)):
            d.rounded_rectangle(box, radius=16, outline=theme.muted, width=3)
            f = _font(theme, "regular", max(18, h // 50))
            label = _wrap(d, "Visual to add in Canva: " + slide.visual, f, inner - 40)
            for i, line in enumerate(label[:4]):
                d.text((m + 20, top + 20 + i * int(h / 40)), line, font=f, fill=theme.muted)

    small = _font(theme, "regular", max(16, h // 60))
    if slide.footnote:
        pos = (w / 2, h - m - int(h * 0.045)) if center else (m, h - m - int(h * 0.045))
        d.text(pos, slide.footnote, font=small, fill=theme.muted, anchor="ma" if center else "la")
    if theme.slide_counter and total > 1:
        counter = f"{index}/{total}"
        d.text((w - m, h - m), counter, font=small, fill=theme.muted, anchor="rs")
    if theme.handle:
        d.text((w / 2 if center else m, h - m), theme.handle, font=small, fill=theme.muted,
               anchor="ms" if center else "ls")
    return img


def sources_slide(post: Post, store: SourceStore) -> Slide:
    ids = list(dict.fromkeys(c.source_id for c in post.draft.claims))
    lines = []
    for sid in ids:
        s = store.get(sid)
        if s:
            lines.append(f"[{sid}] {s.title} ({s.publisher})")
    return Slide(heading="Sources", body="\n".join(lines))


def render_post(post: Post, store: SourceStore, size: tuple[int, int], theme: Theme,
                out_dir: Path) -> list[Path]:
    spec = post.draft.design
    if spec.kind == "none" or not spec.slides:
        return []
    def credit(text: str) -> str:  # "Source: S2" -> "Source: Example Docs"
        def sub(m):
            src = store.get(m.group(0))
            return (src.publisher or src.title) if src else m.group(0)
        return re.sub(r"\bS\d+\b", sub, text)

    slides = [s.model_copy(update={"footnote": credit(s.footnote)}) for s in spec.slides]
    if spec.kind == "carousel" and not any(s.heading.lower() == "sources" for s in slides):
        slides.append(sources_slide(post, store))
    out_dir.mkdir(parents=True, exist_ok=True)
    paths, images = [], []
    for i, slide in enumerate(slides, 1):
        img = render_slide(slide, size, theme, i, len(slides), spec.kind)
        path = out_dir / f"{post.id}-{i:02d}.png"
        img.save(path)
        paths.append(path)
        images.append(img)
    if spec.kind == "carousel" and post.draft.platform == "linkedin":
        pdf = out_dir / f"{post.id}.pdf"  # LinkedIn document posts take a PDF
        images[0].save(pdf, save_all=True, append_images=images[1:])
        paths.append(pdf)
    return paths
