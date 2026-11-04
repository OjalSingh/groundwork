import json

import pytest
import yaml
from click.testing import CliRunner
from PIL import Image

from groundwork.cli import main
from groundwork.config import Config
from groundwork.design.render import render_slide
from groundwork.design.theme import (
    Theme,
    contrast_ratio,
    load_presets,
    resolve_theme,
    theme_warnings,
)
from groundwork.design.wizard import (
    ScriptedAsker,
    ask_for_images,
    preview_sheet,
    run_wizard,
    save_wizard_result,
)
from groundwork.llm.offline import OfflineWriter
from groundwork.models import DesignSpec, Draft, Post, Slide
from groundwork.pipeline import run


def test_every_builtin_preset_is_readable():
    presets = load_presets()
    assert {"midnight", "paper", "terracotta", "forest", "mono", "sunrise"} <= set(presets)
    for name, theme in presets.items():
        assert theme_warnings(theme) == [], name


def test_contrast_and_bad_colour():
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21, rel=1e-3)
    assert theme_warnings(Theme(background="#777777", foreground="#888888"))
    with pytest.raises(ValueError):
        Theme(accent="red")


def test_resolve_overrides_and_user_presets(tmp_path):
    (tmp_path / "brand.yaml").write_text("name: brand\nbackground: '#101010'\naccent: '#FF00AA'\n", encoding="utf-8")
    t = resolve_theme("brand", {"handle": "@me"}, tmp_path)
    assert (t.accent, t.handle, t.background) == ("#FF00AA", "@me", "#101010")
    assert resolve_theme("paper", {"accent": "#0F766E"}).accent == "#0F766E"
    with pytest.raises(KeyError):
        resolve_theme("nope")


def test_config_preset_with_overrides(tmp_path):
    f = tmp_path / "groundwork.yaml"
    f.write_text("theme_preset: forest\ntheme: {handle: '@x', accent: '#FFFFFF'}\n", encoding="utf-8")
    cfg = Config.load(f)
    assert cfg.theme.background == "#0E2A1F" and cfg.theme.accent == "#FFFFFF"
    assert cfg.theme.handle == "@x"


@pytest.mark.parametrize("name", ["midnight", "paper", "terracotta", "forest", "mono", "sunrise"])
def test_each_preset_renders_every_kind(name):
    theme = load_presets()[name]
    for kind in ("carousel", "quote_card"):
        for i in (1, 2):
            img = render_slide(Slide(heading="H", body="Body text " * 8, footnote="Source: S1"),
                               (1080, 1350), theme, i, 3, kind)
            assert img.size == (1080, 1350)


def test_inverted_cover_and_supplied_image(tmp_path):
    theme = load_presets()["terracotta"]
    cover = render_slide(Slide(heading="H"), (400, 500), theme, 1, 3, "carousel")
    inner = render_slide(Slide(heading="H"), (400, 500), theme, 2, 3, "carousel")
    assert cover.getpixel((2, 250)) != inner.getpixel((2, 250))
    pic = tmp_path / "d.png"
    Image.new("RGB", (200, 100), "#00FF00").save(pic)
    s = Slide(body="b", visual="a diagram", image=str(pic))
    img = render_slide(s, (800, 1000), load_presets()["midnight"], 2, 3, "carousel")
    assert (0, 255, 0) in {p for _, p in img.getcolors(maxcolors=10**6)}


def test_wizard_scripted_flow_and_save(tmp_path):
    ask = ScriptedAsker([
        "paper",                       # start preset
        "colours", "#FAF6EE", "#111111", "#0F766E", "#7A7167",
        "handle", "@ojal",
        "accent_style", "none",
        "colours", "#FFFFFF", "#FEFEFE", "#0F766E", "#7A7167",   # unreadable on purpose
        "done",
    ])
    theme = run_wizard(ask, tmp_path / "pv")
    assert theme.accent == "#0F766E" and theme.handle == "@ojal" and theme.accent_style == "none"
    assert any("contrast" in line for line in ask.log)
    assert (tmp_path / "pv" / "theme-preview.png").exists()
    cfg_path = tmp_path / "groundwork.yaml"
    cfg_path.write_text("timezone: Asia/Kolkata\n", encoding="utf-8")
    save_wizard_result(theme, cfg_path, "mine", tmp_path / "themes")
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert raw["timezone"] == "Asia/Kolkata" and raw["theme_preset"] == "mine"
    assert Config.load(cfg_path).theme.handle == "@ojal"


def test_wizard_rejects_bad_hex(tmp_path):
    ask = ScriptedAsker(["midnight", "colours", "nope", "#000000", "#111111", "#222222", "done"])
    theme = run_wizard(ask, tmp_path)
    assert theme.background == "#0F172A" and any("Not applied" in m for m in ask.log)


def test_ask_for_images(tmp_path):
    pic = tmp_path / "a.png"
    Image.new("RGB", (10, 10)).save(pic)
    post = Post(id="p", draft=Draft(platform="instagram", format="carousel", hook="h", parts=["p"],
                design=DesignSpec(kind="carousel", slides=[
                    Slide(body="a", visual="boxes"), Slide(body="b", visual="icon"),
                    Slide(body="c")])))
    ask_for_images(post, ScriptedAsker([str(pic), ""]))
    s = post.draft.design.slides
    assert s[0].image == str(pic.resolve()) and s[1].image == "" and s[2].image == ""


def test_needs_input_and_attach_render_loop(tmp_path, store, templates, cfg):
    class WithVisual(OfflineWriter):
        def write(self, req):
            d = super().write(req)
            d.design.slides[1].visual = "client -> ring -> servers"
            return d

    runs = tmp_path / "runs"
    result = run("consistent hashing", ["instagram:carousel"], cfg, templates, WithVisual(), store,
                 runs)
    needs = (result.run_dir / "needs_input.md").read_text(encoding="utf-8")
    assert "slide 2" in needs and "groundwork attach" in needs
    post_json = result.run_dir / "posts" / f"{result.posts[0].id}.json"
    store.save(result.run_dir / "sources.json")
    pic = tmp_path / "ring.png"
    Image.new("RGB", (300, 200), "#00FF00").save(pic)
    runner = CliRunner()
    r = runner.invoke(main, ["attach", str(post_json), "--slide", "2", "--image", str(pic)])
    assert r.exit_code == 0, r.output
    r = runner.invoke(main, ["render", str(post_json), str(result.run_dir / "sources.json"),
                             "--theme", "paper"])
    assert r.exit_code == 0, r.output
    saved = Post.model_validate(json.loads(post_json.read_text(encoding="utf-8")))
    assert saved.draft.design.slides[1].image == str(pic.resolve())
    first = Image.open(result.run_dir / saved.image_paths[0])
    assert first.getpixel((2, 2)) != (15, 23, 42)  # re-rendered in the paper theme


def test_theme_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert "paper" in runner.invoke(main, ["theme", "list"]).output
    r = runner.invoke(main, ["theme", "preview", "forest", "--set", "accent=#FFFFFF"])
    assert r.exit_code == 0 and (tmp_path / "theme-preview.png").exists()
    r = runner.invoke(main, ["theme", "save", "brand", "--from", "paper", "--set",
                             "accent=#0F766E", "--set", "handle=@me"])
    assert r.exit_code == 0, r.output
    cfg = Config.load(tmp_path / "groundwork.yaml")
    assert cfg.theme.name == "brand" and cfg.theme.accent == "#0F766E" and cfg.theme.handle == "@me"
    assert preview_sheet(cfg.theme, tmp_path / "x.png").exists()


def test_switching_theme_keeps_handle(tmp_path, store, templates, cfg):
    from groundwork.cli import _switch_theme
    cfg.theme.handle = "@me"
    assert _switch_theme(cfg, "paper").handle == "@me"
    assert _switch_theme(cfg, "paper").background == "#FAF6EE"
