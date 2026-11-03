"""A deterministic, extractive writer for tests, CI and dry runs without an API key.

It builds posts only out of sentences lifted from the sources, so its output always
passes grounding. It is not meant to be good writing; it proves the pipeline works
end to end and gives a baseline to compare the real writer against.
"""

from __future__ import annotations

import re

from groundwork.grounding import normalize
from groundwork.lint import lint_slop
from groundwork.llm.base import WriteRequest
from groundwork.models import Claim, DesignSpec, Draft, Finding, Slide

_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _sentences(text: str) -> list[str]:
    out = []
    for para in text.splitlines():
        out += [s.strip() for s in _SENT.split(para) if s.strip()]
    return out


class OfflineWriter:
    def _ranked(self, req: WriteRequest, max_len: int) -> list[tuple[str, str]]:
        words = {w for w in re.findall(r"[a-z0-9]+", req.topic.lower()) if len(w) > 2}
        scored = []
        for src in req.store:
            for i, s in enumerate(_sentences(src.text)):
                if not 50 <= len(s) <= max_len or lint_slop(s):
                    continue
                hits = len(words & set(re.findall(r"[a-z0-9]+", s.lower())))
                scored.append((-hits, i, src.id, s))
        scored.sort()
        seen, out = set(), []
        for _, _, sid, s in scored:
            key = normalize(s)
            if key not in seen:
                seen.add(key)
                out.append((sid, s))
        return out

    def write(self, req: WriteRequest) -> Draft:
        fmt = req.format
        budget = min(fmt.parts.max_chars, 600) - 12  # room for the " [S12]" marker
        picks = self._ranked(req, max_len=budget)
        n_parts = max(fmt.parts.min, min(fmt.parts.max, 4))
        body = picks[:n_parts]
        parts = [f"{s} [{sid}]" for sid, s in body]
        claims = [Claim(statement=s, source_id=sid, quote=s) for sid, s in body]
        design = DesignSpec(kind="none")
        if fmt.design.kind != "none":
            n = max(fmt.design.min_slides, min(fmt.design.max_slides, 6))
            if fmt.design.kind in ("header", "quote_card"):
                n = 1
            slide_src = picks[n_parts:n_parts + n] or body[:n]
            slides = [Slide(heading=req.topic.title() if i == 0 else "",
                            body=s, footnote=f"Source: {sid}") for i, (sid, s) in enumerate(slide_src)]
            claims += [Claim(statement=s, source_id=sid, quote=s) for sid, s in slide_src]
            design = DesignSpec(kind=fmt.design.kind, slides=slides,
                                alt_text=f"Slides summarising sourced facts about {req.topic}.")
        hook = f"What the sources say about {req.topic}."[: fmt.hook_max_chars]
        return Draft(platform=req.platform.name, format=req.format_name, title=req.topic.title(),
                     hook=hook, parts=parts, claims=claims, design=design)

    def revise(self, req: WriteRequest, draft: Draft, findings: list[Finding]) -> Draft:
        return draft  # nothing smarter to do offline; the pipeline will flag it for review
