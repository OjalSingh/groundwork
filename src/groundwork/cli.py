from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from groundwork.config import Config
from groundwork.lint import lint_slop
from groundwork.platforms.registry import load_templates
from groundwork.research.store import SourceStore


def _templates(cfg: Config):
    return load_templates(Path(cfg.templates_dir) if cfg.templates_dir else None)


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None,
              help="Path to groundwork.yaml (defaults to ./groundwork.yaml if present).")
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def main(ctx, config_path, verbose):
    """Research-first content pipeline for Substack, LinkedIn, Instagram and X."""
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    ctx.obj = Config.load(config_path)


@main.command()
@click.pass_obj
def platforms(cfg: Config):
    """List platforms and formats from the loaded templates."""
    for name, tpl in sorted(_templates(cfg).items()):
        click.echo(f"{name}: " + ", ".join(tpl.formats))


@main.command("research")
@click.argument("topic")
@click.option("--url", "urls", multiple=True, help="Seed URL to include (repeatable).")
@click.option("--offline", is_flag=True, help="Skip Claude web search.")
@click.option("-o", "--out", type=click.Path(path_type=Path), default=Path("sources.json"))
@click.pass_obj
def research_cmd(cfg: Config, topic, urls, offline, out):
    """Collect and save sources for TOPIC without writing posts."""
    from groundwork.pipeline import research

    web = None
    if cfg.use_web_search and not offline:
        from groundwork.llm.anthropic_llm import ClaudeWebResearcher
        web = ClaudeWebResearcher(cfg.model)
    store = research(topic, cfg, list(urls), web)
    store.save(out)
    click.echo(store.bibliography())
    click.echo(f"\n{len(store)} sources saved to {out}")


@main.command("run")
@click.argument("topic")
@click.option("-p", "--platform", "targets", multiple=True, required=True,
              help="platform or platform:format, e.g. x:thread (repeatable).")
@click.option("--brief", default="", help="What angle or takeaway you want.")
@click.option("--url", "urls", multiple=True, help="Seed URL to include (repeatable).")
@click.option("--sources", "sources_file", type=click.Path(exists=True, path_type=Path),
              help="Reuse a sources.json from `groundwork research` instead of researching.")
@click.option("--offline", is_flag=True,
              help="No API calls: skip web search and use the extractive offline writer.")
@click.option("-o", "--out", type=click.Path(path_type=Path), default=Path("runs"))
@click.pass_obj
def run_cmd(cfg: Config, topic, targets, brief, urls, sources_file, offline, out):
    """Research TOPIC, write posts for each platform, check, design and schedule them."""
    from groundwork.pipeline import research, run

    templates = _templates(cfg)
    if sources_file:
        store = SourceStore.load(sources_file)
    else:
        web = None
        if cfg.use_web_search and not offline:
            from groundwork.llm.anthropic_llm import ClaudeWebResearcher
            web = ClaudeWebResearcher(cfg.model)
        store = research(topic, cfg, list(urls), web)
    if offline:
        from groundwork.llm.offline import OfflineWriter
        writer = OfflineWriter()
    else:
        from groundwork.llm.anthropic_llm import ClaudeWriter
        writer = ClaudeWriter(cfg.model, cfg.effort)
    result = run(topic, list(targets), cfg, templates, writer, store, out, brief)
    click.echo((result.run_dir / "report.md").read_text())
    click.echo(f"Output: {result.run_dir}")


@main.command()
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.pass_obj
def lint(cfg: Config, path: Path):
    """Run the slop linter over any text file. Exits 1 on errors."""
    findings = lint_slop(path.read_text(), cfg.extra_banned)
    for f in findings:
        click.echo(f"{f.severity.value:7} {f.check:28} {f.message}  {f.excerpt!r}")
    raise SystemExit(1 if any(f.severity.value == "error" for f in findings) else 0)


@main.command("check")
@click.argument("post_json", type=click.Path(exists=True, path_type=Path))
@click.argument("sources_json", type=click.Path(exists=True, path_type=Path))
@click.pass_obj
def check_cmd(cfg: Config, post_json: Path, sources_json: Path):
    """Re-run grounding and lint checks on an edited post JSON."""
    from groundwork.grounding import check_grounding
    from groundwork.lint import lint_draft
    from groundwork.models import Post

    post = Post.model_validate(json.loads(post_json.read_text()))
    store = SourceStore.load(sources_json)
    _, fmt = _templates(cfg)[post.draft.platform].format(post.draft.format)
    findings = check_grounding(post.draft, store) + lint_draft(post.draft, fmt, cfg.extra_banned)
    for f in findings:
        click.echo(f"{f.severity.value:7} {f.check:28} {f.message}")
    raise SystemExit(1 if any(f.severity.value == "error" for f in findings) else 0)


if __name__ == "__main__":
    main()
