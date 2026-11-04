"""Write a step-by-step Canva recipe for a design spec.

Produced for every designed post: as the only route when a slide needs a visual we
cannot render, and as the editable route when you want to tweak a rendered image.
"""

from __future__ import annotations

from groundwork.design.theme import Theme
from groundwork.models import Post, Slide

EXPORT = {
    ("linkedin", "carousel"): "PDF Standard (LinkedIn takes carousels as a document upload)",
    ("instagram", "carousel"): "PNG, all pages (upload them together as one carousel post)",
    ("instagram", "quote"): "PNG",
    ("x", "thread"): "PNG (attach to the first post)",
    ("substack", "article"): "PNG or JPG (set as the post's cover image)",
}


def _px(fraction: float, total: int) -> int:
    return int(fraction * total)


def _accent_step(theme: Theme, w: int, h: int, m: int) -> list[str]:
    bar_h = max(6, h // 160)
    if theme.accent_style == "bar":
        return [f"1. Accent bar: **Elements**, search \"square\", add one, colour **{theme.accent}**. "
                f"In **Position**, set W {_px(0.12, w)}, H {bar_h}, "
                f"X {(w - _px(0.12, w)) // 2 if theme.align == 'center' else m}, Y {m}."]
    if theme.accent_style == "block":
        return [f"1. Top strip: **Elements**, search \"square\", add one, colour **{theme.accent}**. "
                f"Set W {w}, H {_px(0.025, h)}, X 0, Y 0."]
    if theme.accent_style == "underline":
        return [f"1. Accent underline: add a **square** element in **{theme.accent}**, W "
                f"{_px(0.18, w)}, H {bar_h}, placed directly under the heading on each page."]
    return ["1. This theme has no accent shape; skip to the text boxes."]


def canva_guide(post: Post, size: tuple[int, int], theme: Theme,
                extra_slides: list[Slide] | None = None) -> str:
    spec = post.draft.design
    slides = list(spec.slides) + list(extra_slides or [])
    w, h = size
    m = _px(0.08, w)
    align = theme.align
    export = EXPORT.get((post.draft.platform, post.draft.format), "PNG")
    out = [
        f"# Canva steps for {post.id}",
        "",
        f"About {3 + 2 * len(slides)} minutes. Rendered PNGs sit next to this file if you "
        "only need a quick edit; these steps rebuild the design from scratch.",
        "",
        "## 1. Set up the canvas",
        "",
        "1. On the Canva home page, click **Create a design**, then **Custom size**.",
        f"2. Enter **{w} x {h} px** and click **Create new design**.",
        f"3. Click the empty page, then the colour tile in the top toolbar, and enter "
        f"**{theme.background}** as the background.",
        f"4. Fonts used: **{theme.heading_font}** for headings, **{theme.body_font}** for body "
        "text. Pick them from the font dropdown when a text box is selected.",
        "",
        "## 2. Build the first page as a template",
        "",
        *_accent_step(theme, w, h, m),
        f"2. Heading: **Text** > **Add a heading**. Colour "
        f"**{theme.foreground}**, size about {_px(0.075, h) * 3 // 4} pt, {align} aligned, "
        f"X {m}, Y {m + _px(0.05, h)}, width {w - 2 * m}.",
        f"3. Body: **Text** > **Add a little bit of body text**. Colour **{theme.foreground}**, "
        f"size about {_px(0.042, h) * 3 // 4} pt, {align} aligned, same left edge and width as "
        "the heading.",
        f"4. Footer: small text (about {max(16, h // 60) * 3 // 4} pt) in **{theme.muted}** "
        f"at the bottom {'centre' if theme.align == 'center' else 'left'}"
        + (f" reading **{theme.handle}**" if theme.handle else "")
        + (", and a page counter at the bottom right."
           if len(slides) > 1 and theme.slide_counter else "."),
    ]
    if len(slides) > 1:
        out.append("5. When page 1 looks right, click **Duplicate page** "
                   f"{len(slides) - 1} times so every page shares the layout.")
        if theme.cover_style == "inverted":
            out.append(f"6. Cover page (page 1) only: set its background to **{theme.accent}** "
                       f"and recolour all its text to **{theme.background}**.")
    out.append("")
    out += ["## 3. Fill each page", ""]
    for i, s in enumerate(slides, 1):
        out.append(f"### Page {i}" + (f" of {len(slides)}" if len(slides) > 1 else ""))
        out.append("")
        if s.heading:
            out.append(f"- Heading: {s.heading}")
        if s.body:
            body = s.body.replace("\n", " / ")
            out.append(f"- Body: {body}")
        if s.footnote:
            out.append(f"- Footnote (small, muted, above the footer): {s.footnote}")
        if not s.heading:
            out.append("- Delete the heading box on this page and move the body up.")
        if s.visual:
            out += [
                f"- Visual: {s.visual}",
                "  1. Open **Elements** and search for the simplest matching graphic "
                "(line icons, plain shapes and arrows read best at phone size).",
                "  2. Recolour it to the accent and foreground colours above so it matches.",
                "  3. For a diagram, build it from **Shapes** plus **Lines**: boxes for "
                "components, arrows for flow, one short label per box.",
            ]
        out.append("")
    out += [
        "## 4. Check and export",
        "",
        "1. Read every page on your phone preview: text should be legible without zooming.",
        "2. Check each footnote matches the source list in the post file.",
        f"3. **Share** > **Download**, file type **{export}**.",
        f"4. When posting, paste this alt text: \"{spec.alt_text}\"" if spec.alt_text
        else "4. Write alt text describing the slides when you post.",
        "",
    ]
    return "\n".join(out)
