from groundwork.lint import lint_draft, lint_slop, x_length
from groundwork.models import DesignSpec, Draft, Slide


def checks(findings):
    return {f.check for f in findings}


def test_filler_and_bait_are_errors():
    text = "In today's fast-paced world, let's dive in. Agree?"
    found = checks(lint_slop(text))
    assert {"slop.filler_phrase", "slop.engagement_bait"} <= found


def test_unsourced_authority():
    assert "slop.unsourced_authority" in checks(lint_slop("Studies show caching is good."))


def test_clean_text_passes():
    assert lint_slop("Adding a fifth server to four remaps most keys. Rings avoid that.") == []


def test_not_x_but_y_and_suspense_are_warnings():
    f = lint_slop("It's not a cache problem, it's a hashing problem. The result? Outages.")
    assert {"slop.not_x_but_y", "slop.fake_suspense"} <= checks(f)
    assert all(x.severity.value == "warning" for x in f)


def test_custom_banned_words():
    assert "slop.custom" in checks(lint_slop("A bespoke approach", ["bespoke"]))


def test_x_length_counts_urls_as_23():
    assert x_length("see https://example.com/a/very/long/path/that/goes/on") == 4 + 23


def test_format_limits(templates):
    fmt = templates["x"].formats["thread"]
    d = Draft(platform="x", format="thread", hook="h", parts=["a" * 300], hashtags=["a", "b"])
    found = checks(lint_draft(d, fmt))
    assert {"format.part_count", "format.part_too_long", "format.hashtags"} <= found


def test_carousel_needs_slides(templates):
    fmt = templates["instagram"].formats["carousel"]
    d = Draft(platform="instagram", format="carousel", hook="h", parts=["caption"],
              design=DesignSpec(kind="carousel", slides=[]))
    errs = [f for f in lint_draft(d, fmt) if f.check == "format.slide_count"]
    assert errs and errs[0].severity.value == "error"
    d.design.slides = [Slide(body="ok")] * 6
    d.design.alt_text = "alt"
    assert "format.slide_count" not in checks(lint_draft(d, fmt))


def test_factual_speedups_and_honest_headings_are_not_slop():
    text = "Maglev builds tables about 10x faster. The catch: it is less stable."
    assert lint_slop(text) == []
    assert "slop.buzzword" in checks(lint_slop("Be a 10x engineer."))
    assert "slop.fake_suspense" in checks(lint_slop("We tried it. The result? Outages."))
