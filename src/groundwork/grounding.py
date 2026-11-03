"""Grounding: prove every factual claim against text we actually fetched.

This is the main defence against invented facts. The writer model must attach a
verbatim quote to each claim; we then check the quote really occurs in the cited
source, and that every number in the post is backed by a verified quote. A model
can still choose quotes badly, but it cannot make one up and pass.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from groundwork.models import Draft, Finding, Severity
from groundwork.research.store import SourceStore

MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 500
FUZZY_THRESHOLD = 0.9  # share of the quote that must match one contiguous span

_TRANSLATE = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})
_STOP = set("""a an the and or but of to in on for with by is are was were be been it its this
that these those as at from into than then so such can could will would may might not no""".split())


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_TRANSLATE)).strip().lower()


def quote_in_source(quote: str, source_text: str) -> bool:
    q, s = normalize(quote), normalize(source_text)
    if not q:
        return False
    if q in s:
        return True
    # Tolerate tiny differences (a dropped comma, an ellipsis) but not paraphrase.
    m = SequenceMatcher(None, s, q, autojunk=False).find_longest_match(0, len(s), 0, len(q))
    if m.size / len(q) >= FUZZY_THRESHOLD:
        return True
    # Elided quotes: "first half ... second half", each half must match exactly.
    pieces = [p.strip() for p in re.split(r"\.\.\.|…", q) if p.strip()]
    return len(pieces) > 1 and all(p in s for p in pieces)


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", normalize(text)) if w not in _STOP and len(w) > 2}


# Numbers that carry facts. Thread counters (3/7), list markers and small counts
# ("3 ideas") are structure, not claims.
_NUMBER = re.compile(r"(?<![\w/#])(\d[\d,]*(?:\.\d+)?)(\s?%|x\b|\s?(?:ms|s|gb|mb|tb|kb|k|m|bn)\b)?",
                     re.IGNORECASE)


def factual_numbers(text: str) -> set[str]:
    out = set()
    text = re.sub(r"\b\d+\s?/\s?\d+\b", " ", text)  # 1/7 thread counters
    for m in _NUMBER.finditer(text):
        value, unit = m.group(1).replace(",", ""), (m.group(2) or "").strip().lower()
        if not unit and value.isdigit() and int(value) <= 10:
            continue
        out.add(value)
    return out


def check_grounding(draft: Draft, store: SourceStore) -> list[Finding]:
    findings: list[Finding] = []

    def err(check: str, msg: str, excerpt: str = "", sev: Severity = Severity.ERROR):
        findings.append(Finding(check=check, severity=sev, message=msg, excerpt=excerpt[:200]))

    if not draft.claims:
        err("grounding.no_claims", "The post makes no sourced claims. Every post needs at least "
            "one claim tied to a quote from a fetched source.")

    verified_quotes: list[str] = []
    for claim in draft.claims:
        src = store.get(claim.source_id)
        if src is None:
            err("grounding.unknown_source", f"Claim cites {claim.source_id}, which was not "
                "fetched.", claim.statement)
            continue
        if len(claim.quote) < MIN_QUOTE_CHARS:
            err("grounding.quote_too_short", f"Quote for {claim.source_id} is too short to "
                "verify; copy a full sentence.", claim.quote)
            continue
        if len(claim.quote) > MAX_QUOTE_CHARS:
            err("grounding.quote_too_long", "Quote is longer than needed; cite the one or two "
                "sentences that support the claim.", claim.quote, Severity.WARNING)
        if not quote_in_source(claim.quote, src.text):
            err("grounding.quote_not_found", f"Quote not found in {claim.source_id} "
                f"({src.url}). Quotes must be copied verbatim.", claim.quote)
            continue
        verified_quotes.append(claim.quote)
        overlap = _content_words(claim.statement) & _content_words(claim.quote)
        if len(overlap) < 2:
            err("grounding.weak_support", f"The quote from {claim.source_id} shares almost no "
                "terms with the claim; check it really supports it.", claim.statement,
                Severity.WARNING)

    backed = set()
    for q in verified_quotes:
        backed |= factual_numbers(q)
    body = "\n".join([draft.hook, *draft.parts, *(s.body + " " + s.heading for s in draft.design.slides)])
    for n in sorted(factual_numbers(body) - backed):
        err("grounding.unbacked_number", f"The number {n} appears in the post but in no "
            "verified quote. Cite it or remove it.", n)
    return findings
