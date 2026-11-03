"""Turn a checked post into a copy-paste-ready Markdown file with a publish checklist."""

from __future__ import annotations

from groundwork.models import Post, Severity
from groundwork.platforms.registry import FormatTemplate
from groundwork.research.store import SourceStore

PUBLISH_STEPS = {
    "x": [
        "Open x.com and start a new post.",
        "Paste part 1 (the hook) and attach the image if there is one.",
        "Click the + to add each following part to the thread, in order.",
        "Post the thread, then check every link opens.",
    ],
    "linkedin": [
        "On linkedin.com click **Start a post** and paste the post text.",
        "For a carousel: click **More** > **Add a document**, upload the PDF and give it a title.",
        "Post, then immediately add the sources block as the first comment.",
    ],
    "instagram": [
        "In the app, tap **+** > **Post** and select every slide in order.",
        "Paste the caption. Under **Advanced settings** add the alt text.",
        "Share, then check slide order on your profile.",
    ],
    "substack": [
        "In your Substack dashboard click **New post**.",
        "Paste the title, subtitle (the hook) and body. Headings starting with ## become headings.",
        "Upload the header image as the cover, add footnotes from the sources list.",
        "Preview on mobile, then schedule for the slot in schedule.ics or publish.",
    ],
}


def citation_block(post: Post, fmt: FormatTemplate, store: SourceStore) -> tuple[str, str]:
    """Return (text appended to the post, separate block to post elsewhere)."""
    ids = list(dict.fromkeys(c.source_id for c in post.draft.claims))
    srcs = [s for s in (store.get(i) for i in ids) if s]
    full = "\n".join(f"[{s.id}] {s.title}, {s.publisher}: {s.url}" for s in srcs)
    short = "Sources: " + "; ".join(f"{s.publisher or s.title} {s.url}" for s in srcs)
    match fmt.citations:
        case "last_part" | "inline":
            return short, ""
        case "caption":
            return "Sources: " + "; ".join(s.publisher or s.title for s in srcs), ""
        case "first_comment" | "reply":
            return "", full
        case "footnotes":
            return "## Sources\n\n" + "\n".join(
                f"{n}. [{s.title}]({s.url}), {s.publisher}" for n, s in enumerate(srcs, 1)), ""
        case _:  # last_slide: the renderer adds a sources slide; keep a copy here too
            return "", full


def post_markdown(post: Post, fmt: FormatTemplate, store: SourceStore) -> str:
    d = post.draft
    appended, separate = citation_block(post, fmt, store)
    lines = [f"# {d.title or post.id}", "",
             f"- Platform: {d.platform} / {d.format}",
             f"- Status: **{post.status.value}**"
             + (f" (after {post.revisions} revision(s))" if post.revisions else ""),
             f"- Scheduled: {post.scheduled_for.isoformat() if post.scheduled_for else 'not scheduled'}",
             "", "## Post text", ""]
    if d.platform == "x":
        tweets = [d.hook, *d.parts] + ([appended] if appended else [])
        for i, t in enumerate(tweets, 1):
            lines += [f"**Part {i}**", "", "```text", t, "```", ""]
    else:
        body = d.full_text() + (f"\n\n{appended}" if appended else "")
        lines += ["```text", body, "```", ""]
    if separate:
        where = "first comment" if fmt.citations == "first_comment" else "reply / source list"
        lines += [f"## Sources ({where})", "", "```text", separate, "```", ""]
    if post.image_paths:
        lines += ["## Images", ""] + [f"- `{p}`" for p in post.image_paths] + [""]
    if post.canva_guide_path:
        lines += [f"Canva steps: `{post.canva_guide_path}`", ""]
    lines += ["## Claims and evidence", "", "| Claim | Source | Quote |", "|---|---|---|"]
    for c in d.claims:
        cell = lambda s: s.replace("|", "\\|").replace("\n", " ")  # noqa: E731
        lines.append(f"| {cell(c.statement)} | {c.source_id} | \"{cell(c.quote)}\" |")
    lines.append("")
    if post.findings:
        lines += ["## Review notes", ""]
        for f in post.findings:
            icon = "ERROR" if f.severity == Severity.ERROR else "warn"
            lines.append(f"- {icon} `{f.check}`: {f.message}" + (f" ({f.excerpt!r})" if f.excerpt else ""))
        lines.append("")
    lines += ["## How to publish", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(PUBLISH_STEPS.get(d.platform, []), 1)]
    return "\n".join(lines) + "\n"
