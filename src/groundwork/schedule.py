"""Assign ready posts to posting windows and export them as a calendar."""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from groundwork.models import Post, PostStatus
from groundwork.platforms.registry import DAYS, PlatformTemplate


def _slots(tpl: PlatformTemplate, start: datetime, tz: ZoneInfo, horizon_days: int = 60):
    for offset in range(horizon_days):
        day = (start.astimezone(tz).date() + timedelta(days=offset))
        dname = DAYS[day.weekday()]
        times = sorted({t for w in tpl.posting_windows if dname in w.days for t in w.times})
        for t in times:
            hh, mm = map(int, t.split(":"))
            slot = datetime.combine(day, time(hh, mm), tzinfo=tz)
            if slot > start:
                yield slot


def schedule(posts: list[Post], templates: dict[str, PlatformTemplate], tz_name: str,
             start: datetime | None = None, taken: list[datetime] | None = None) -> list[Post]:
    """Give each READY post the next free slot on its platform. Others stay unscheduled."""
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"Unknown timezone {tz_name!r}. Use a name like 'Asia/Kolkata' or 'UTC' "
            "(on Windows, `pip install tzdata` provides the database).") from exc
    start = start or datetime.now(timezone.utc)
    per_day: dict[tuple[str, date], int] = defaultdict(int)
    used = set(taken or [])
    for post in posts:
        if post.status != PostStatus.READY:
            continue
        tpl = templates[post.draft.platform]
        for slot in _slots(tpl, start, tz):
            key = (tpl.name, slot.date())
            if slot in used or per_day[key] >= tpl.max_posts_per_day:
                continue
            post.scheduled_for = slot
            used.add(slot)
            per_day[key] += 1
            break
    return posts


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def to_ics(posts: list[Post], run_dir: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//groundwork//content calendar//EN"]
    for p in posts:
        if not p.scheduled_for:
            continue
        begin = p.scheduled_for.astimezone(timezone.utc)
        end = begin + timedelta(minutes=15)
        desc = f"{p.draft.hook}\n\nPost file: {run_dir / 'posts' / (p.id + '.md')}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{p.id}-{begin:%Y%m%dT%H%M}@groundwork",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{begin:%Y%m%dT%H%M%SZ}",
            f"DTEND:{end:%Y%m%dT%H%M%SZ}",
            f"SUMMARY:{_ics_escape(f'Post to {p.draft.platform}: {p.draft.title or p.id}')}",
            f"DESCRIPTION:{_ics_escape(desc)}",
            "BEGIN:VALARM", "TRIGGER:-PT10M", "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape('Publish ' + p.id)}", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def to_csv(posts: list[Post], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["post_id", "platform", "format", "status", "scheduled_for", "hook", "images"])
        for p in posts:
            w.writerow([p.id, p.draft.platform, p.draft.format, p.status.value,
                        p.scheduled_for.isoformat() if p.scheduled_for else "",
                        p.draft.hook, ";".join(p.image_paths)])
