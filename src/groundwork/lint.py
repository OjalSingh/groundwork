"""Anti-slop and format linting.

Two families of checks:
  * slop: phrases and shapes that make text read as machine filler
  * format: the hard and house limits from the platform template

Rules are data, so a project can extend them in groundwork.yaml (`extra_banned`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from groundwork.models import Draft, Finding, Severity
from groundwork.platforms.registry import FormatTemplate


@dataclass(frozen=True)
class Rule:
    check: str
    pattern: str
    message: str
    severity: Severity = Severity.ERROR


def _w(words: str) -> str:
    return r"\b(?:" + "|".join(re.escape(w).replace(r"\ ", r"\s+") for w in words.split("|")) + r")\b"


SLOP_RULES: list[Rule] = [
    Rule("slop.filler_phrase", _w(
        "delve|delves|delving|in today's fast-paced|ever-evolving|ever-changing landscape|"
        "game-changer|game changer|unlock the power|unleash|revolutionize|revolutionise|supercharge|"
        "it's important to note|it is important to note|in conclusion|tapestry|elevate your|"
        "harness the power|let's dive in|dive into|buckle up|a testament to|embark on|"
        "in the realm of|paradigm shift|secret sauce|mind-blowing|navigate the complexities|"
        "look no further|without further ado|plays a crucial role|stands as a|"
        "the world of|more than ever"),
        "Filler phrase. Say the specific thing instead."),
    Rule("slop.buzzword", _w("leverage|synergy|robust|cutting-edge|seamless|seamlessly|"
                             "landscape|holistic|empower|transformative|deep dive|"
                             "10x engineer|10x developer"),
         "Buzzword. Use a plain word or a concrete detail.", Severity.WARNING),
    Rule("slop.unsourced_authority", _w(
        "studies show|research shows|experts say|science says|data shows|statistics show|"
        "everyone knows|it is well known|it's well known"),
        "Appeal to unnamed authority. Name the source and cite it as a claim."),
    Rule("slop.engagement_bait", r"(?i)(\bagree\?|\bthoughts\?|comment (?:below|yes)|"
         r"like and share|tag (?:someone|a friend)|smash that|follow for more|repost if)",
         "Engagement bait. End with something useful instead."),
    Rule("slop.not_x_but_y", r"(?i)\b(?:it's|it is|this is)\s+not\s+(?:just\s+)?[^.?!]{1,40}"
         r"[,;]\s*(?:it's|it is|but)\b", "\"It's not X, it's Y\" construction. State Y directly.",
         Severity.WARNING),
    Rule("slop.fake_suspense", r"(?m)(?:^|\.\s)(?:The (?:result|kicker|twist|answer|truth)\s*\?|"
         r"Here's the (?:thing|kicker|catch)\s*[?:])", "Fake suspense beat. Just say it.",
         Severity.WARNING),
]

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def lint_slop(text: str, extra_banned: list[str] | None = None) -> list[Finding]:
    rules = list(SLOP_RULES)
    if extra_banned:
        rules.append(Rule("slop.custom", _w("|".join(extra_banned)), "Banned by project config."))
    findings = []
    for rule in rules:
        for m in re.finditer(rule.pattern, text, flags=re.IGNORECASE):
            start = max(0, m.start() - 30)
            findings.append(Finding(check=rule.check, severity=rule.severity, message=rule.message,
                                    excerpt=text[start:m.end() + 30].replace("\n", " ")))
    dashes = text.count("—")
    if dashes and dashes > max(1, len(text) // 400):
        findings.append(Finding(check="slop.em_dash", severity=Severity.WARNING,
                                message=f"{dashes} em dashes. Use full stops or commas."))
    emojis = len(EMOJI.findall(text))
    if emojis > 3:
        findings.append(Finding(check="slop.emoji", severity=Severity.WARNING,
                                message=f"{emojis} emoji. Keep to three or fewer."))
    if text.count("!") > 2:
        findings.append(Finding(check="slop.exclamation", severity=Severity.WARNING,
                                message="More than two exclamation marks."))
    return findings


def x_length(text: str) -> int:
    """Approximate X's weighted count: every URL counts as 23 characters."""
    return len(re.sub(r"https?://\S+", "x" * 23, text))


def lint_format(draft: Draft, fmt: FormatTemplate) -> list[Finding]:
    f: list[Finding] = []

    def add(check, msg, sev=Severity.ERROR, excerpt=""):
        f.append(Finding(check=check, severity=sev, message=msg, excerpt=excerpt[:120]))

    measure = x_length if draft.platform == "x" else len
    rules = fmt.parts
    if not rules.min <= len(draft.parts) <= rules.max:
        add("format.part_count", f"{len(draft.parts)} parts; this format needs "
            f"{rules.min} to {rules.max}.")
    for i, part in enumerate(draft.parts, 1):
        n = measure(part)
        if n > rules.max_chars:
            add("format.part_too_long", f"Part {i} is {n} characters (max {rules.max_chars}).",
                excerpt=part)
    if draft.platform == "x" and draft.parts and draft.hook:
        # On X the hook is the first tweet, so it must fit by itself.
        if measure(draft.hook) > fmt.hook_max_chars:
            add("format.hook_too_long", f"Hook is {measure(draft.hook)} characters.")
    elif len(draft.hook) > fmt.hook_max_chars:
        add("format.hook_too_long", f"Hook is {len(draft.hook)} characters "
            f"(max {fmt.hook_max_chars}).", Severity.WARNING)
    total = len(draft.full_text())
    if rules.total_max_chars and total > rules.total_max_chars:
        add("format.total_too_long", f"Post is {total} characters (max {rules.total_max_chars}).")
    tags = len(draft.hashtags)
    hard = fmt.hashtags.hard_max
    if hard is not None and tags > hard:
        add("format.hashtags", f"{tags} hashtags exceeds the platform cap of {hard}.")
    elif tags > fmt.hashtags.max:
        add("format.hashtags", f"{tags} hashtags; house style allows {fmt.hashtags.max}.",
            Severity.WARNING)
    d = fmt.design
    if d.kind != "none":
        n = len(draft.design.slides)
        if not d.min_slides <= n <= d.max_slides:
            sev = Severity.ERROR if (n == 0 or (d.hard_max_slides and n > d.hard_max_slides)) \
                else Severity.WARNING
            add("format.slide_count", f"{n} slides; aim for {d.min_slides} to {d.max_slides}.", sev)
        for i, s in enumerate(draft.design.slides, 1):
            words = len(f"{s.heading} {s.body}".split())
            if d.kind == "carousel" and words > 45:
                add("format.slide_wordy", f"Slide {i} has {words} words; keep slides under 45.",
                    Severity.WARNING)
        if not draft.design.alt_text:
            add("format.alt_text", "Add alt text for the image(s).", Severity.WARNING)
    return f


def lint_draft(draft: Draft, fmt: FormatTemplate, extra_banned: list[str] | None = None):
    text = "\n".join([draft.title, draft.hook, *draft.parts, draft.cta,
                      *(f"{s.heading}\n{s.body}" for s in draft.design.slides)])
    return lint_slop(text, extra_banned) + lint_format(draft, fmt)
