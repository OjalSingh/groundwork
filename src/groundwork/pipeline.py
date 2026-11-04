"""Orchestration: research -> write -> verify/lint -> revise -> design -> schedule."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from groundwork.config import Config
from groundwork.design.canva import canva_guide
from groundwork.design.render import render_post, sources_slide
from groundwork.grounding import check_grounding
from groundwork.lint import lint_draft
from groundwork.llm.base import WebResearcher, Writer, WriteRequest
from groundwork.models import Post, PostStatus, Severity
from groundwork.output import post_markdown
from groundwork.platforms.registry import PlatformTemplate
from groundwork.research.collectors import (
    REGISTRY,
    RssCollector,
    UrlCollector,
    source_from_url,
)
from groundwork.research.store import SourceStore
from groundwork.schedule import schedule, to_csv, to_ics

log = logging.getLogger(__name__)


def slugify(text: str, limit: int = 60) -> str:
    """Lowercase, hyphenated, cut at a word boundary so ids don't end mid-word."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if len(slug) > limit:
        slug = slug[:limit].rsplit("-", 1)[0] if "-" in slug[:limit] else slug[:limit]
    return slug or "run"


def research(topic: str, cfg: Config, seed_urls: list[str] | None = None,
             web: WebResearcher | None = None) -> SourceStore:
    store = SourceStore()
    if seed_urls:
        for s in UrlCollector(seed_urls).collect(topic, len(seed_urls)):
            store.add(s)
    if web is not None:
        try:
            for url in web.find_urls(topic, cfg.sources_per_collector * 2):
                src = source_from_url(url, "web")
                if src:
                    store.add(src)
        except Exception as exc:  # research should degrade, not die
            log.warning("web search failed: %s", exc)
    collectors = [REGISTRY[name]() for name in cfg.collectors if name in REGISTRY]
    if cfg.rss_feeds:
        collectors.append(RssCollector(cfg.rss_feeds))
    for c in collectors:
        try:
            for s in c.collect(topic, cfg.sources_per_collector):
                store.add(s)
        except Exception as exc:
            log.warning("collector %s failed: %s", c.name, exc)
    return store


def review(post: Post, req: WriteRequest, cfg: Config) -> None:
    post.findings = check_grounding(post.draft, req.store) + lint_draft(
        post.draft, req.format, cfg.extra_banned)


def produce(req: WriteRequest, writer: Writer, cfg: Config, post_id: str) -> Post:
    draft = writer.write(req)
    post = Post(id=post_id, draft=draft)
    review(post, req, cfg)
    while post.errors and post.revisions < cfg.max_revisions:
        post.revisions += 1
        post.draft = writer.revise(req, post.draft, post.findings)
        review(post, req, cfg)
    post.status = PostStatus.NEEDS_REVIEW if post.errors else PostStatus.READY
    return post


@dataclass
class RunResult:
    run_dir: Path
    store: SourceStore
    posts: list[Post] = field(default_factory=list)


def parse_targets(targets: list[str], templates: dict[str, PlatformTemplate]):
    """'x', 'x:thread', 'instagram:carousel' -> (template, format name, format)."""
    out = []
    for t in targets:
        name, _, fmt = t.partition(":")
        if name not in templates:
            raise KeyError(f"Unknown platform {name!r}; options: {sorted(templates)}")
        tpl = templates[name]
        fmt_name, fmt_tpl = tpl.format(fmt or None)
        out.append((tpl, fmt_name, fmt_tpl))
    return out


def design_post(post: Post, fmt, store: SourceStore, cfg: Config, run_dir: Path) -> None:
    """(Re)render a post's images and Canva guide into run_dir."""
    if post.draft.design.kind == "none":
        return
    size = tuple(fmt.design.size)
    imgs = render_post(post, store, size, cfg.theme, run_dir / "designs")
    post.image_paths = [str(p.relative_to(run_dir)) for p in imgs]
    extra = [sources_slide(post, store)] if post.draft.design.kind == "carousel" else []
    guide = run_dir / "canva" / f"{post.id}.md"
    guide.write_text(canva_guide(post, size, cfg.theme, extra))
    post.canva_guide_path = str(guide.relative_to(run_dir))


def needs_input_md(posts: list[Post]) -> str:
    rows = []
    for p in posts:
        for i, s in enumerate(p.draft.design.slides, 1):
            if s.visual and not s.image:
                rows.append(f"- **{p.id}, slide {i}**: {s.visual}\n"
                            f"  - Supply an image: `groundwork attach posts/{p.id}.json "
                            f"--slide {i} --image path/to/file.png`, then "
                            f"`groundwork render posts/{p.id}.json sources.json`\n"
                            f"  - Or build it in Canva: see `{p.canva_guide_path}`")
    if not rows:
        return "# Needs your input\n\nNothing: every slide is fully rendered.\n"
    return "# Needs your input\n\nThese slides need a diagram, icon or photo.\n\n" + "\n".join(rows) + "\n"


def run(topic: str, targets: list[str], cfg: Config, templates: dict[str, PlatformTemplate],
        writer: Writer, store: SourceStore, out_root: Path, brief: str = "",
        start: datetime | None = None,
        before_design: Callable[[Post], None] | None = None) -> RunResult:
    stamp = (start or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    run_dir = out_root / f"{stamp}-{slugify(topic)}"
    for sub in ("posts", "designs", "canva"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    store.save(run_dir / "sources.json")
    (run_dir / "bibliography.md").write_text("# Sources\n\n" + store.bibliography() + "\n")
    result = RunResult(run_dir=run_dir, store=store)
    if len(store) == 0:
        log.error("No usable sources; refusing to write unsourced posts.")
        (run_dir / "report.md").write_text(
            f"# Run report: {topic}\n\nNo usable sources were found, so no posts were written. "
            "Pass seed links with --url or check network access.\n")
        return result

    for tpl, fmt_name, fmt in parse_targets(targets, templates):
        req = WriteRequest(topic, brief, cfg.voice, store, tpl, fmt_name, fmt)
        post = produce(req, writer, cfg, f"{tpl.name}-{fmt_name}-{slugify(topic, 30)}")
        if before_design:
            before_design(post)  # e.g. ask the user for images
        design_post(post, fmt, store, cfg, run_dir)
        result.posts.append(post)

    schedule(result.posts, templates, cfg.timezone, start=start)
    for post in result.posts:
        _, fmt = templates[post.draft.platform].format(post.draft.format)
        (run_dir / "posts" / f"{post.id}.md").write_text(post_markdown(post, fmt, store))
        (run_dir / "posts" / f"{post.id}.json").write_text(post.model_dump_json(indent=2))
    (run_dir / "schedule.ics").write_text(to_ics(result.posts, run_dir))
    to_csv(result.posts, run_dir / "schedule.csv")
    (run_dir / "report.md").write_text(report(topic, result))
    (run_dir / "needs_input.md").write_text(needs_input_md(result.posts))
    return result


def report(topic: str, result: RunResult) -> str:
    lines = [f"# Run report: {topic}", "", f"Sources used: {len(result.store)}", "",
             "| Post | Status | Errors | Warnings | Revisions | Scheduled |",
             "|---|---|---|---|---|---|"]
    for p in result.posts:
        warns = sum(f.severity == Severity.WARNING for f in p.findings)
        when = p.scheduled_for.strftime("%a %d %b %H:%M %Z") if p.scheduled_for else "-"
        lines.append(f"| [{p.id}](posts/{p.id}.md) | {p.status.value} | {len(p.errors)} | "
                     f"{warns} | {p.revisions} | {when} |")
    lines += ["", "Posts marked needs_review failed a grounding or slop check after every "
              "revision. They are not scheduled.", ""]
    return "\n".join(lines)


def dump_json(obj) -> str:
    return json.dumps(obj, indent=2, default=str)
