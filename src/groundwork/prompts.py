"""Prompt construction shared by every writer backend."""

from __future__ import annotations

from groundwork.models import Finding
from groundwork.platforms.registry import FormatTemplate, PlatformTemplate
from groundwork.research.store import SourceStore

WRITER_SYSTEM = """\
You write educational social posts that a careful expert would be glad to sign.

Hard rules:
1. Every factual statement must come from the numbered sources provided. For each one,
   add a claim with the source id and a quote copied character-for-character from that
   source's text. Quotes are checked by a program; paraphrased quotes fail.
2. Never state a number, date, name or result that is not in a quote you attach.
3. If the sources do not support an interesting post, say less. Do not pad.
4. Write like a practitioner explaining to a colleague: concrete nouns, short sentences,
   one idea per paragraph. No filler openers, no hype words, no "it's not X, it's Y",
   no fake suspense ("The result?"), no engagement bait, at most one emoji.
5. Credit sources the way the format asks (see "Citations").
6. Opinions are allowed when labelled as yours and argued from the cited facts.
"""


def source_block(store: SourceStore, chars_per_source: int = 6000) -> str:
    chunks = []
    for s in store:
        chunks.append(
            f"<source id=\"{s.id}\" url=\"{s.url}\" title=\"{s.title}\" "
            f"publisher=\"{s.publisher}\">\n{s.excerpt(chars_per_source)}\n</source>"
        )
    return "\n\n".join(chunks)


def format_block(platform: PlatformTemplate, fmt_name: str, fmt: FormatTemplate) -> str:
    p, d = fmt.parts, fmt.design
    lines = [
        f"Platform: {platform.display_name} / format: {fmt_name}",
        f"What it is: {fmt.description}",
        f"Body parts: {p.min} to {p.max}, each at most {p.max_chars} characters"
        + (f", whole post at most {p.total_max_chars}" if p.total_max_chars else ""),
        f"Hook: at most {fmt.hook_max_chars} characters",
        f"Hashtags: at most {fmt.hashtags.max}",
        f"Citations: {fmt.citations}",
    ]
    if d.kind != "none":
        lines.append(f"Design: {d.kind}, {d.min_slides} to {d.max_slides} slides at "
                     f"{d.size[0]}x{d.size[1]}. Fill design.slides and design.alt_text.")
    else:
        lines.append("Design: none. Leave design.kind as 'none' and slides empty.")
    if fmt.guidance.strip():
        lines.append("Platform guidance:\n" + fmt.guidance.strip())
    return "\n".join(lines)


def write_prompt(topic: str, brief: str, voice: str, store: SourceStore,
                 platform: PlatformTemplate, fmt_name: str, fmt: FormatTemplate) -> str:
    return f"""\
<sources>
{source_block(store)}
</sources>

<format>
{format_block(platform, fmt_name, fmt)}
</format>

<voice>
{voice.strip() or "Plain, specific, a little dry. First person is fine."}
</voice>

Topic: {topic}
Brief: {brief.strip() or "Teach one useful idea about the topic, grounded in the sources."}

Write the post. Set platform="{platform.name}" and format="{fmt_name}"."""


def revise_prompt(findings: list[Finding]) -> str:
    issues = "\n".join(f"- [{f.check}] {f.message}" + (f" (near: {f.excerpt!r})" if f.excerpt
                                                       else "") for f in findings)
    return f"""\
An automated review found these problems with your draft:

{issues}

Return a corrected draft. Fix every error. For quote problems, copy the quote exactly
from the source text or drop the claim and the sentence that depends on it."""
