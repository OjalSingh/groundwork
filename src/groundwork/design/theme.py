from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

# Searched in order when the config does not name a font file. Inter and DejaVu are
# both free (OFL / Bitstream Vera licence) and present on most Linux CI images.
FONT_CANDIDATES = {
    "bold": [
        "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "regular": [
        "/usr/share/fonts/opentype/inter/Inter-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


class Theme(BaseModel):
    background: str = "#0F172A"
    foreground: str = "#F8FAFC"
    accent: str = "#38BDF8"
    muted: str = "#94A3B8"
    heading_font: str = "Inter"          # the name to pick in Canva
    body_font: str = "Inter"
    heading_font_file: str | None = None  # a local file for rendering
    body_font_file: str | None = None
    handle: str = ""                      # e.g. @yourname, printed on every slide

    def font_file(self, weight: str) -> str | None:
        explicit = self.heading_font_file if weight == "bold" else self.body_font_file
        if explicit:
            return explicit
        return next((p for p in FONT_CANDIDATES[weight] if Path(p).exists()), None)
