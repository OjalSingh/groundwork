from datetime import datetime, timezone

from groundwork.models import Draft, Post, PostStatus
from groundwork.schedule import schedule, to_ics


def post(pid, platform, fmt, status=PostStatus.READY):
    return Post(id=pid, status=status,
                draft=Draft(platform=platform, format=fmt, hook="h, with; specials", parts=["p"]))


def test_slots_follow_windows_and_daily_cap(templates):
    start = datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc)  # a Monday
    posts = [post("a", "linkedin", "post"), post("b", "linkedin", "post"),
             post("c", "x", "thread"), post("d", "x", "thread", PostStatus.NEEDS_REVIEW)]
    schedule(posts, templates, "UTC", start=start)
    a, b, c, d = posts
    assert a.scheduled_for == datetime(2026, 11, 3, 8, 0, tzinfo=a.scheduled_for.tzinfo)  # Tue
    assert b.scheduled_for.date().isoformat() == "2026-11-04"  # one per day on LinkedIn
    assert c.scheduled_for.hour == 8 and c.scheduled_for.day == 2
    assert d.scheduled_for is None


def test_timezone_is_respected(templates):
    start = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    (p,) = schedule([post("a", "x", "thread")], templates, "Asia/Kolkata", start=start)
    assert p.scheduled_for.utcoffset().total_seconds() == 5.5 * 3600


def test_ics(tmp_path, templates):
    p = post("a", "x", "thread")
    schedule([p], templates, "UTC", start=datetime(2026, 11, 2, tzinfo=timezone.utc))
    ics = to_ics([p], tmp_path)
    assert ics.startswith("BEGIN:VCALENDAR") and "DTSTART:20261102T083000Z" in ics
    assert r"h\, with\; specials" in ics
