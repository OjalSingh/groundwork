"""The local UI's JSON API, driven through Flask's test client (no network)."""

import io
import json

import pytest
from PIL import Image

from groundwork.ui.app import create_app

GOOD = "When a server is added, only the keys between it and its predecessor have to move."


def reply(quote=GOOD):
    return "Here you go:\n```json\n" + json.dumps({
        "platform": "instagram", "format": "carousel", "title": "Rings", "hook": "Keys on a ring.",
        "parts": ["Only nearby keys move. [S1]"],
        "claims": [{"statement": "Only nearby keys move when a server is added", "source_id": "S1",
                    "quote": quote}],
        "design": {"kind": "carousel", "alt_text": "Slides.", "slides": [
            {"heading": "Rings", "body": "Only nearby keys move.", "footnote": "Source: S1"},
            {"heading": "Ring", "body": "Keys sit on a circle.", "visual": "a circle with 3 hosts"},
            {"heading": "Moves", "body": "Few keys move."}, {"heading": "Why", "body": "Caches."},
            {"heading": "End", "body": "That's it."}]},
    }) + "\n```"


@pytest.fixture
def client(tmp_path, store, cfg, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(cfg, tmp_path / "ws", tmp_path / "groundwork.yaml")
    c = app.test_client()
    # create a topic without network: no urls, no collectors, then drop in fixture sources
    r = c.post("/api/topics", json={"topic": "Consistent hashing", "urls": [], "use_collectors": False})
    assert r.status_code == 200
    store.save(tmp_path / "ws" / "consistent-hashing" / "sources.json")
    return c


def test_meta_and_pages(client):
    m = client.get("/api/meta").get_json()
    assert "instagram" in m["platforms"] and "paper" in m["presets"] and m["has_api_key"] is False
    assert b"groundwork" in client.get("/").data
    assert client.get("/static/app.js").status_code == 200


def test_free_mode_write_check_build(client, tmp_path):
    slug = "consistent-hashing"
    prompt = client.post(f"/api/topics/{slug}/prompt", json={"target": "instagram:carousel"}).get_json()
    assert '<source id="S1"' in prompt["prompt"]

    bad = client.post(f"/api/topics/{slug}/reply", json={"target": "instagram:carousel",
                                                         "text": reply("Invented sentence here, not in any source.")}).get_json()
    assert bad["status"] == "needs_fix" and "corrected JSON" in bad["fix_message"]

    junk = client.post(f"/api/topics/{slug}/reply", json={"target": "instagram:carousel", "text": "nope"}).get_json()
    assert junk["status"] == "unusable"

    good = client.post(f"/api/topics/{slug}/reply", json={"target": "instagram:carousel", "text": reply()}).get_json()
    assert good["status"] == "ready", good["findings"]

    img = io.BytesIO()
    Image.new("RGB", (60, 40), "#00FF00").save(img, "PNG")
    img.seek(0)
    r = client.post(f"/api/topics/{slug}/attach", data={"target": "instagram:carousel", "slide": "2",
                                                         "image": (img, "ring.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["draft"]["design"]["slides"][1]["image"]

    build = client.post(f"/api/topics/{slug}/build", json={"preset": "forest", "overrides": {}}).get_json()
    (post,) = build["posts"]
    assert post["status"] == "ready" and post["scheduled_for"] and len(post["images"]) == 6
    assert client.get(post["images"][0]).status_code == 200
    assert client.get(build["ics"]).status_code == 200
    topic = client.get(f"/api/topics/{slug}").get_json()
    assert topic["drafts"]["instagram:carousel"]["status"] == "ready" and topic["build"]


def test_sources_remove_keeps_ids(client):
    slug = "consistent-hashing"
    r = client.post(f"/api/topics/{slug}/sources/remove", json={"id": "S1"}).get_json()
    assert [s["id"] for s in r["sources"]] == ["S2"]


def test_theme_preview_and_save(client, tmp_path):
    r = client.post("/api/theme/preview", json={"preset": "paper", "overrides": {"accent": "#0F766E"}})
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert json.loads(r.headers["X-Theme-Warnings"]) == []
    bad = client.post("/api/theme/preview", json={"preset": "paper", "overrides": {"accent": "red"}})
    assert bad.status_code == 400
    saved = client.post("/api/theme/save", json={"preset": "paper", "overrides": {"handle": "@me"},
                                                 "save_as": "mine"}).get_json()
    assert saved["theme"]["handle"] == "@me" and (tmp_path / "themes" / "mine.yaml").exists()


def test_errors_are_json_and_paths_are_guarded(client):
    assert client.get("/api/topics/nope").get_json()["error"]
    assert client.get("/files/consistent-hashing/../../etc/passwd").status_code == 404
    r = client.post("/api/topics/consistent-hashing/generate", json={"target": "x:thread"})
    assert r.status_code == 400 and "copy-paste" in r.get_json()["error"]
