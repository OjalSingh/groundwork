from datetime import datetime, timezone

from PIL import Image

from groundwork.llm.offline import OfflineWriter
from groundwork.models import Claim, PostStatus
from groundwork.pipeline import run

START = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)
TARGETS = ["x:thread", "linkedin:carousel", "instagram:carousel", "instagram:quote",
           "substack:article", "linkedin:post"]


def test_offline_end_to_end(tmp_path, store, templates, cfg):
    cfg.theme.handle = "@test"
    result = run("consistent hashing", TARGETS, cfg, templates, OfflineWriter(), store,
                 tmp_path, start=START)
    d = result.run_dir
    assert len(result.posts) == len(TARGETS)
    for p in result.posts:
        assert not p.errors, (p.id, p.errors)
        assert p.status == PostStatus.READY and p.scheduled_for is not None
        assert (d / "posts" / f"{p.id}.md").exists()
    ig = next(p for p in result.posts if p.id.startswith("instagram-carousel"))
    pngs = [x for x in ig.image_paths if x.endswith(".png")]
    assert len(pngs) == len(ig.draft.design.slides) + 1  # plus the sources slide
    assert Image.open(d / pngs[0]).size == (1080, 1350)
    li = next(p for p in result.posts if p.id.startswith("linkedin-carousel"))
    assert any(x.endswith(".pdf") for x in li.image_paths)
    guide = (d / ig.canva_guide_path).read_text()
    assert "1080 x 1350 px" in guide and "Sources" in guide
    assert "BEGIN:VEVENT" in (d / "schedule.ics").read_text()
    assert "needs_review" not in (d / "report.md").read_text().split("|---|")[-1].split("Posts marked")[0]


class LyingWriter(OfflineWriter):
    """Invents a quote on the first try, then fixes it when told."""

    def __init__(self):
        self.revisions = 0

    def write(self, req):
        d = super().write(req)
        d.claims[0] = Claim(statement="made up", source_id="S1",
                            quote="Consistent hashing was invented on the moon in 1850.")
        return d

    def revise(self, req, draft, findings):
        self.revisions += 1
        assert any(f.check == "grounding.quote_not_found" for f in findings)
        return super().write(req)


def test_revision_loop_fixes_bad_quote(tmp_path, store, templates, cfg):
    w = LyingWriter()
    (post,) = run("consistent hashing", ["x:thread"], cfg, templates, w, store, tmp_path,
                  start=START).posts
    assert w.revisions == 1 and post.revisions == 1 and post.status == PostStatus.READY


class StubbornWriter(LyingWriter):
    def revise(self, req, draft, findings):
        return draft


def test_unfixable_post_is_not_scheduled(tmp_path, store, templates, cfg):
    (post,) = run("consistent hashing", ["x:thread"], cfg, templates, StubbornWriter(), store,
                  tmp_path, start=START).posts
    assert post.status == PostStatus.NEEDS_REVIEW and post.scheduled_for is None
    assert post.revisions == cfg.max_revisions


def test_no_sources_no_posts(tmp_path, templates, cfg):
    from groundwork.research.store import SourceStore
    result = run("anything", ["x"], cfg, templates, OfflineWriter(), SourceStore(), tmp_path)
    assert result.posts == [] and "No usable sources" in (result.run_dir / "report.md").read_text()


def test_slugify_cuts_at_word_boundary():
    from groundwork.pipeline import slugify
    assert slugify("Consistent hashing in load balancers", 30) == "consistent-hashing-in-load"
    assert slugify("x" * 80, 10) == "x" * 10 and slugify("!!!") == "run"
