"""A small local web UI over the same pipeline the CLI uses.

Run `groundwork ui` and open http://127.0.0.1:8765. It binds to localhost only. All state
lives on disk under ./workspace/<topic-slug>/, so the CLI and the UI can be mixed freely:

    workspace/<slug>/topic.json      topic, brief
    workspace/<slug>/sources.json    fetched sources (same format as `groundwork research`)
    workspace/<slug>/drafts/*.json   one checked draft per platform:format
    workspace/<slug>/assets/         images you uploaded for slides
    workspace/<slug>/runs/<date>/    output of the last build (posts, designs, calendar)
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from groundwork.config import Config
from groundwork.design.theme import Theme, load_presets, resolve_theme, theme_warnings
from groundwork.grounding import check_grounding
from groundwork.lint import lint_draft
from groundwork.llm.base import WriteRequest
from groundwork.manual import StaticWriter, build_prompt, fix_message, parse_draft
from groundwork.models import Draft, Post
from groundwork.pipeline import parse_targets, produce, research, run, slugify
from groundwork.platforms.registry import load_templates
from groundwork.research.store import SourceStore, canonical_url

STATIC = Path(__file__).parent / "static"
IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".webp"}


def create_app(cfg: Config, workspace: Path, config_path: Path = Path("groundwork.yaml")) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
    workspace.mkdir(parents=True, exist_ok=True)
    themes_dir = Path(cfg.themes_dir) if cfg.themes_dir else Path("themes")

    def templates():
        return load_templates(Path(cfg.templates_dir) if cfg.templates_dir else None)

    def topic_dir(slug: str) -> Path:
        d = (workspace / secure_filename(slug)).resolve()
        if not d.is_dir() or workspace.resolve() not in d.parents:
            abort(404, f"No topic {slug!r}")
        return d

    def topic_info(d: Path) -> dict:
        return json.loads((d / "topic.json").read_text(encoding="utf-8"))

    def load_store(d: Path) -> SourceStore:
        f = d / "sources.json"
        return SourceStore.load(f) if f.exists() else SourceStore()

    def request_for(d: Path, target: str) -> WriteRequest:
        info = topic_info(d)
        ((tpl, fmt_name, fmt),) = parse_targets([target], templates())
        return WriteRequest(info["topic"], info.get("brief", ""), cfg.voice, load_store(d),
                            tpl, fmt_name, fmt)

    def draft_path(d: Path, target: str) -> Path:
        return d / "drafts" / (target.replace(":", "-") + ".json")

    def checked(d: Path, target: str, draft: Draft) -> dict:
        req = request_for(d, target)
        findings = check_grounding(draft, req.store) + lint_draft(draft, req.format,
                                                                  cfg.extra_banned)
        errors = [f for f in findings if f.severity.value == "error"]
        return {
            "target": target,
            "status": "needs_fix" if errors else "ready",
            "findings": [f.model_dump(mode="json") for f in findings],
            "fix_message": fix_message(findings) if errors else "",
            "draft": draft.model_dump(mode="json"),
        }

    def sources_json(store: SourceStore) -> list[dict]:
        return [{"id": s.id, "title": s.title, "publisher": s.publisher, "url": s.url,
                 "chars": len(s.text), "collector": s.collector} for s in store]

    # ---------------------------------------------------------------- pages and files

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(STATIC, name)

    @app.get("/files/<slug>/<path:rel>")
    def topic_file(slug, rel):
        d = topic_dir(slug)
        target = (d / rel).resolve()
        if d not in target.parents or not target.is_file():
            abort(404)
        return send_file(target)

    # ---------------------------------------------------------------- meta

    @app.get("/api/meta")
    def meta():
        tpls = templates()
        return jsonify({
            "platforms": {name: list(t.formats) for name, t in sorted(tpls.items())},
            "presets": {n: t.model_dump(mode="json") for n, t in load_presets(themes_dir).items()},
            "theme": cfg.theme.model_dump(mode="json"),
            "has_api_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "collectors": cfg.collectors,
            "timezone": cfg.timezone,
        })

    # ---------------------------------------------------------------- topics and sources

    @app.get("/api/topics")
    def list_topics():
        out = []
        for d in sorted(workspace.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if (d / "topic.json").exists():
                info = topic_info(d)
                drafts = sorted(p.stem for p in (d / "drafts").glob("*.json")) \
                    if (d / "drafts").exists() else []
                out.append({"slug": d.name, **info, "sources": len(load_store(d)),
                            "drafts": drafts})
        return jsonify(out)

    @app.post("/api/topics")
    def create_topic():
        body = request.get_json(force=True)
        topic = (body.get("topic") or "").strip()
        if not topic:
            abort(400, "Give the topic a name.")
        urls = [u.strip() for u in body.get("urls", []) if u.strip()]
        use_collectors = bool(body.get("use_collectors", True))
        use_web = bool(body.get("use_web_search")) and bool(os.environ.get("ANTHROPIC_API_KEY"))
        run_cfg = cfg.model_copy(update={"collectors": cfg.collectors if use_collectors else [],
                                         "rss_feeds": cfg.rss_feeds if use_collectors else []})
        web = None
        if use_web:
            from groundwork.llm.anthropic_llm import ClaudeWebResearcher
            web = ClaudeWebResearcher(cfg.model)
        store = research(topic, run_cfg, urls, web)
        d = workspace / slugify(topic)
        (d / "drafts").mkdir(parents=True, exist_ok=True)
        (d / "topic.json").write_text(json.dumps({
            "topic": topic, "brief": body.get("brief", ""),
            "created": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
        existing = load_store(d)
        for s in store:  # adding to a topic keeps earlier sources
            existing.add(s)
        existing.save(d / "sources.json")
        return jsonify({"slug": d.name, "sources": sources_json(existing),
                        "requested_urls": len(urls)})

    @app.get("/api/topics/<slug>")
    def get_topic(slug):
        d = topic_dir(slug)
        drafts = {}
        for p in sorted((d / "drafts").glob("*.json")):
            target = p.stem.replace("-", ":", 1)
            try:
                drafts[target] = checked(d, target, Draft.model_validate_json(
                    p.read_text(encoding="utf-8")))
            except KeyError:
                continue  # template for that platform was removed
        return jsonify({"slug": slug, **topic_info(d), "sources": sources_json(load_store(d)),
                        "drafts": drafts, "build": latest_build(d)})

    @app.post("/api/topics/<slug>/sources/remove")
    def remove_source(slug):
        d = topic_dir(slug)
        sid = request.get_json(force=True).get("id")
        store = load_store(d)
        keep = SourceStore()
        for s in store:
            if s.id != sid:
                keep._by_url[canonical_url(s.url)] = s  # keep ids stable so existing quotes still match
        keep.save(d / "sources.json")
        return jsonify({"sources": sources_json(keep)})

    # ---------------------------------------------------------------- writing

    @app.post("/api/topics/<slug>/prompt")
    def get_prompt(slug):
        d = topic_dir(slug)
        target = request.get_json(force=True)["target"]
        req = request_for(d, target)
        if len(req.store) == 0:
            abort(400, "Add at least one source first.")
        return jsonify({"target": target, "prompt": build_prompt(req)})

    @app.post("/api/topics/<slug>/reply")
    def submit_reply(slug):
        d = topic_dir(slug)
        body = request.get_json(force=True)
        target = body["target"]
        try:
            draft = parse_draft(body.get("text", ""))
        except ValueError as exc:
            return jsonify({"target": target, "status": "unusable", "error": str(exc),
                            "fix_message": f"Your reply was not usable: {exc}. Reply with the "
                                           "complete corrected JSON object only."})
        want_platform, _, want_format = target.partition(":")
        draft.platform, draft.format = want_platform, want_format or draft.format
        draft_path(d, target).write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return jsonify(checked(d, target, draft))

    @app.post("/api/topics/<slug>/generate")
    def generate(slug):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            abort(400, "ANTHROPIC_API_KEY is not set. Use the copy-paste mode instead.")
        from groundwork.llm.anthropic_llm import ClaudeWriter
        d = topic_dir(slug)
        target = request.get_json(force=True)["target"]
        req = request_for(d, target)
        post = produce(req, ClaudeWriter(cfg.model, cfg.effort), cfg, "ui")
        draft_path(d, target).write_text(post.draft.model_dump_json(indent=2), encoding="utf-8")
        return jsonify({**checked(d, target, post.draft), "revisions": post.revisions})

    @app.post("/api/topics/<slug>/drafts/remove")
    def remove_draft(slug):
        d = topic_dir(slug)
        p = draft_path(d, request.get_json(force=True)["target"])
        if p.exists():
            p.unlink()
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- images

    @app.post("/api/topics/<slug>/attach")
    def attach(slug):
        d = topic_dir(slug)
        target, slide = request.form["target"], int(request.form["slide"])
        upload = request.files.get("image")
        if upload is None or Path(upload.filename or "").suffix.lower() not in IMAGE_TYPES:
            abort(400, "Upload a PNG, JPG or WebP image.")
        p = draft_path(d, target)
        draft = Draft.model_validate_json(p.read_text(encoding="utf-8"))
        if not 1 <= slide <= len(draft.design.slides):
            abort(400, f"Slide must be 1 to {len(draft.design.slides)}.")
        (d / "assets").mkdir(exist_ok=True)
        name = secure_filename(f"{target.replace(':', '-')}-slide{slide}-{upload.filename}")
        dest = d / "assets" / name
        upload.save(dest)
        draft.design.slides[slide - 1].image = str(dest.resolve())
        p.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return jsonify(checked(d, target, draft))

    # ---------------------------------------------------------------- themes

    def theme_from(body: dict) -> Theme:
        base = body.get("preset") or cfg.theme.name
        overrides = {k: v for k, v in (body.get("overrides") or {}).items() if v not in ("", None)}
        return resolve_theme(base, overrides, themes_dir if themes_dir.exists() else None)

    @app.post("/api/theme/preview")
    def theme_preview():
        from groundwork.design.wizard import preview_sheet
        try:
            theme = theme_from(request.get_json(force=True))
        except (ValueError, KeyError) as exc:
            return jsonify({"error": str(exc)}), 400
        buf = workspace / ".theme-preview.png"
        preview_sheet(theme, buf)
        data = io.BytesIO(buf.read_bytes())
        resp = send_file(data, mimetype="image/png")
        resp.headers["X-Theme-Warnings"] = json.dumps(theme_warnings(theme))
        return resp

    @app.post("/api/theme/save")
    def theme_save():
        from groundwork.design.wizard import save_wizard_result
        body = request.get_json(force=True)
        try:
            theme = theme_from(body)
        except (ValueError, KeyError) as exc:
            abort(400, str(exc))
        name = secure_filename(body.get("save_as") or "") or None
        written = save_wizard_result(theme, config_path, name, themes_dir)
        cfg.theme = theme.model_copy(update={"name": name}) if name else theme
        return jsonify({"theme": cfg.theme.model_dump(mode="json"),
                        "written": [str(p) for p in written],
                        "warnings": theme_warnings(theme)})

    # ---------------------------------------------------------------- build

    def latest_build(d: Path) -> dict | None:
        runs_dir = d / "runs"
        if not runs_dir.exists():
            return None
        runs = sorted((p for p in runs_dir.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
        if not runs:
            return None
        r = runs[-1]
        posts = []
        for f in sorted((r / "posts").glob("*.json")):
            post = Post.model_validate_json(f.read_text(encoding="utf-8"))
            rel = r.relative_to(d).as_posix()
            md = (r / "posts" / f"{post.id}.md")
            guide = r / post.canva_guide_path if post.canva_guide_path else None
            posts.append({
                "id": post.id, "platform": post.draft.platform, "format": post.draft.format,
                "status": post.status.value,
                "scheduled_for": post.scheduled_for.isoformat() if post.scheduled_for else None,
                "errors": len(post.errors),
                "images": [f"/files/{d.name}/{rel}/{Path(p).as_posix()}" for p in post.image_paths
                           if p.lower().endswith(".png")],
                "pdf": next((f"/files/{d.name}/{rel}/{Path(p).as_posix()}"
                             for p in post.image_paths if p.lower().endswith(".pdf")), None),
                "markdown": md.read_text(encoding="utf-8") if md.exists() else "",
                "canva": guide.read_text(encoding="utf-8") if guide and guide.exists() else "",
            })
        rel = r.relative_to(d).as_posix()
        return {"run": r.name, "posts": posts,
                "ics": f"/files/{d.name}/{rel}/schedule.ics",
                "report": (r / "report.md").read_text(encoding="utf-8")
                if (r / "report.md").exists() else ""}

    @app.post("/api/topics/<slug>/build")
    def build(slug):
        d = topic_dir(slug)
        body = request.get_json(force=True) or {}
        drafts = {}
        for p in sorted((d / "drafts").glob("*.json")):
            target = p.stem.replace("-", ":", 1)
            drafts[target] = Draft.model_validate_json(p.read_text(encoding="utf-8"))
        if not drafts:
            abort(400, "No drafts yet. Write at least one post first.")
        run_cfg = cfg.model_copy(update={"max_revisions": 0})
        if body.get("preset") or body.get("overrides"):
            run_cfg.theme = theme_from(body)
        info = topic_info(d)
        run(info["topic"], list(drafts), run_cfg, templates(), StaticWriter(drafts),
            load_store(d), d / "runs", info.get("brief", ""))
        return jsonify(latest_build(d))

    @app.errorhandler(400)
    @app.errorhandler(404)
    def json_error(err):
        return jsonify({"error": getattr(err, "description", str(err))}), err.code

    @app.errorhandler(Exception)
    def crash(err):  # show the reason in the page instead of a blank 500
        if isinstance(err, HTTPException):
            return jsonify({"error": err.description}), err.code
        app.logger.exception("request failed")
        return jsonify({"error": f"{type(err).__name__}: {err}"}), 500

    return app

