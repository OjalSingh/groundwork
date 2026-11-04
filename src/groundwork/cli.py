from __future__ import annotations

import json
import logging
from pathlib import Path

import click

from groundwork.config import Config
from groundwork.design.theme import load_presets, resolve_theme, theme_warnings
from groundwork.lint import lint_slop
from groundwork.platforms.registry import load_templates
from groundwork.research.store import SourceStore


def _themes_dir(cfg: Config) -> Path | None:
    return Path(cfg.themes_dir) if cfg.themes_dir else None


def _switch_theme(cfg: Config, name: str):
    """Change preset but keep who you are: handle and logo carry over."""
    keep = {"handle": cfg.theme.handle or None, "logo": cfg.theme.logo}
    return resolve_theme(name, keep, _themes_dir(cfg))


def _parse_sets(pairs) -> dict:
    out = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise click.BadParameter(f"expected key=value, got {pair!r}")
        out[key.strip()] = {"true": True, "false": False}.get(value.strip().lower(), value.strip())
    return out


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
@click.option("--drafts", "drafts_file", type=click.Path(exists=True, path_type=Path),
              help="Use drafts you wrote (JSON keyed by platform:format) instead of calling Claude.")
@click.option("--theme", "theme_name", help="Theme preset for this run (see `groundwork theme list`).")
@click.option("--ask", is_flag=True,
              help="Ask design questions: pick a theme, then supply images for slides that need them.")
@click.option("-o", "--out", type=click.Path(path_type=Path), default=Path("runs"))
@click.pass_obj
def run_cmd(cfg: Config, topic, targets, brief, urls, sources_file, offline, drafts_file,
            theme_name, ask, out):
    """Research TOPIC, write posts for each platform, check, design and schedule them."""
    from groundwork.design.wizard import ClickAsker, ask_for_images, run_wizard
    from groundwork.pipeline import research, run

    templates = _templates(cfg)
    asker = ClickAsker()
    before_design = None
    if theme_name:
        cfg.theme = _switch_theme(cfg, theme_name)
    if ask:
        click.echo("Design questions (press Enter to keep the default).")
        cfg.theme = run_wizard(asker, out / "preview", start=cfg.theme,
                               themes_dir=_themes_dir(cfg))
        before_design = lambda post: ask_for_images(post, asker)  # noqa: E731
    if sources_file:
        store = SourceStore.load(sources_file)
    else:
        web = None
        if cfg.use_web_search and not offline:
            from groundwork.llm.anthropic_llm import ClaudeWebResearcher
            web = ClaudeWebResearcher(cfg.model)
        store = research(topic, cfg, list(urls), web)
    if drafts_file:
        from groundwork.llm.file_writer import FileWriter
        writer = FileWriter(drafts_file)
    elif offline:
        from groundwork.llm.offline import OfflineWriter
        writer = OfflineWriter()
    else:
        from groundwork.llm.anthropic_llm import ClaudeWriter
        writer = ClaudeWriter(cfg.model, cfg.effort)
    result = run(topic, list(targets), cfg, templates, writer, store, out, brief,
                 before_design=before_design)
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


@main.group()
def theme():
    """Themes: list presets, preview, tweak, save your own."""


@theme.command("list")
@click.pass_obj
def theme_list(cfg: Config):
    from groundwork.design.wizard import describe_presets
    click.echo(describe_presets(load_presets(_themes_dir(cfg))))


@theme.command("preview")
@click.argument("name")
@click.option("--set", "sets", multiple=True, help="Override a field, e.g. --set accent=#FF5500.")
@click.option("-o", "--out", type=click.Path(path_type=Path), default=Path("theme-preview.png"))
@click.pass_obj
def theme_preview(cfg: Config, name, sets, out):
    """Render three sample slides in preset NAME (with optional tweaks)."""
    from groundwork.design.wizard import preview_sheet
    t = resolve_theme(name, _parse_sets(sets), _themes_dir(cfg))
    click.echo(f"Wrote {preview_sheet(t, out)}")
    for w in theme_warnings(t):
        click.echo(f"Heads up: {w}")


@theme.command("save")
@click.argument("name")
@click.option("--from", "base", default=None, help="Preset to start from.")
@click.option("--set", "sets", multiple=True, help="Override a field, e.g. --set accent=#FF5500.")
@click.option("--use/--no-use", default=True, help="Also make it the active theme.")
@click.option("--config", "cfg_path", type=click.Path(path_type=Path), default=Path("groundwork.yaml"))
@click.option("--dir", "tdir", type=click.Path(path_type=Path), default=Path("themes"))
@click.pass_obj
def theme_save(cfg: Config, name, base, sets, use, cfg_path, tdir):
    """Save a custom preset NAME to themes/ (non-interactive)."""
    from groundwork.design.theme import save_theme
    from groundwork.design.wizard import save_wizard_result
    t = resolve_theme(base or cfg.theme.name, _parse_sets(sets), _themes_dir(cfg) or tdir)
    if use:
        for p in save_wizard_result(t, cfg_path, name, tdir):
            click.echo(f"Wrote {p}")
    else:
        save_theme(t.model_copy(update={"name": name}), tdir / f"{name}.yaml")
        click.echo(f"Wrote {tdir / (name + '.yaml')}")


@main.command()
@click.option("--config", "cfg_path", type=click.Path(path_type=Path), default=Path("groundwork.yaml"))
@click.option("--dir", "tdir", type=click.Path(path_type=Path), default=Path("themes"))
@click.pass_obj
def design(cfg: Config, cfg_path, tdir):
    """Answer design questions, preview as you go, and save your theme."""
    from groundwork.design.wizard import ClickAsker, run_wizard, save_wizard_result
    ask = ClickAsker()
    result = run_wizard(ask, Path(".groundwork-preview"), themes_dir=_themes_dir(cfg) or tdir)
    save_as = ask.text("Save as a named preset? (blank to just update groundwork.yaml)", "")
    for p in save_wizard_result(result, cfg_path, save_as or None, tdir):
        click.echo(f"Wrote {p}")


@main.command()
@click.argument("post_json", type=click.Path(exists=True, path_type=Path))
@click.option("--slide", "slide_no", type=int, required=True, help="Slide number (1-based).")
@click.option("--image", type=click.Path(exists=True, path_type=Path), required=True)
def attach(post_json: Path, slide_no: int, image: Path):
    """Attach your own image (diagram, icon, photo) to a slide, then run `render`."""
    from groundwork.models import Post
    post = Post.model_validate(json.loads(post_json.read_text()))
    slides = post.draft.design.slides
    if not 1 <= slide_no <= len(slides):
        raise click.BadParameter(f"slide must be 1 to {len(slides)}")
    slides[slide_no - 1].image = str(image.resolve())
    post_json.write_text(post.model_dump_json(indent=2))
    click.echo(f"Attached to slide {slide_no}. Now run: groundwork render {post_json} sources.json")


@main.command("render")
@click.argument("post_json", type=click.Path(exists=True, path_type=Path))
@click.argument("sources_json", type=click.Path(exists=True, path_type=Path))
@click.option("--theme", "theme_name", help="Re-render in a different theme preset.")
@click.pass_obj
def render_cmd(cfg: Config, post_json: Path, sources_json: Path, theme_name):
    """Re-render a post's images and Canva guide (after editing text, theme or images)."""
    from groundwork.models import Post
    from groundwork.pipeline import design_post
    if theme_name:
        cfg.theme = _switch_theme(cfg, theme_name)
    post = Post.model_validate(json.loads(post_json.read_text()))
    run_dir = post_json.parent.parent
    _, fmt = _templates(cfg)[post.draft.platform].format(post.draft.format)
    design_post(post, fmt, SourceStore.load(sources_json), cfg, run_dir)
    post_json.write_text(post.model_dump_json(indent=2))
    click.echo(f"Rendered {len(post.image_paths)} file(s) into {run_dir / 'designs'}")


if __name__ == "__main__":
    main()
