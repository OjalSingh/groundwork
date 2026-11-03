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


def canva_guide(post: Post, size: tuple[int, int], theme: Theme,
                extra_slides: list[Slide] | None = None) -> str:
    spec = post.draft.design
    slides = list(spec.slides) + list(extra_slides or [])
    w, h = size
    m = _px(0.08, w)
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
        f"1. Accent bar: **Elements**, search \"square\", add one, set its colour to "
        f"**{theme.accent}**. In **Position**, set W {_px(0.12, w)}, H {max(6, h // 160)}, "
        f"X {m}, Y {m}.",
        "2. Heading: **Text** > **Add a heading**. Colour "
        f"**{theme.foreground}**, size about {_px(0.075, h) * 3 // 4} pt, left aligned, "
        f"X {m}, Y {m + _px(0.05, h)}, width {w - 2 * m}.",
        f"3. Body: **Text** > **Add a little bit of body text**. Colour **{theme.foreground}**, "
        f"size about {_px(0.042, h) * 3 // 4} pt, same left edge and width as the heading.",
        f"4. Footer: small text (about {max(16, h // 60) * 3 // 4} pt) in **{theme.muted}** "
        f"at the bottom left" + (f" reading **{theme.handle}**" if theme.handle else "")
        + (", and a page counter at the bottom right." if len(slides) > 1 else "."),
    ]
    if len(slides) > 1:
        out += ["5. When page 1 looks right, click **Duplicate page** "
                f"{len(slides) - 1} times so every page shares the layout.", ""]
    else:
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
