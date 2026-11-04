import pytest

from groundwork.pipeline import parse_targets
from groundwork.platforms.registry import load_templates


def test_builtin_platforms(templates):
    assert set(templates) == {"x", "linkedin", "instagram", "substack"}


def test_override_dir(tmp_path):
    (tmp_path / "x.yaml").write_text("""
name: x
display_name: X (custom)
formats:
  hot_take: {description: d, parts: {min: 1, max: 1, max_chars: 200}}
""", encoding="utf-8")
    (tmp_path / "threads.yaml").write_text("""
name: threads
display_name: Threads
formats:
  post: {description: d, parts: {min: 1, max: 1, max_chars: 500}}
""", encoding="utf-8")
    t = load_templates(tmp_path)
    assert list(t["x"].formats) == ["hot_take"]
    assert "threads" in t


def test_bad_day_rejected(tmp_path):
    (tmp_path / "bad.yaml").write_text("""
name: bad
display_name: Bad
formats: {post: {description: d, parts: {max_chars: 10}}}
posting_windows: [{days: [funday], times: ["09:00"]}]
""", encoding="utf-8")
    with pytest.raises(ValueError):
        load_templates(tmp_path)


def test_parse_targets(templates):
    (tpl, name, _), = parse_targets(["instagram:quote"], templates)
    assert (tpl.name, name) == ("instagram", "quote")
    assert parse_targets(["x"], templates)[0][1] == "thread"
    with pytest.raises(KeyError):
        parse_targets(["myspace"], templates)
