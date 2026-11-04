# groundwork

A research-first content pipeline for **Substack, LinkedIn, Instagram and X**. Give it a
topic. It collects real sources, has Claude draft a post for each platform, and then
**checks every factual claim against the fetched source text** before anything gets
scheduled. Designed posts come out as rendered PNG/PDF slides plus a step-by-step Canva
recipe. Ready posts land in a calendar file you can import.

The goal is posts a careful expert would sign, not volume.

```
topic ──► research ──► write ──► ground + lint ──► revise (≤2) ──► design ──► schedule
           │             │            │                               │           │
   Wikipedia, arXiv,  Claude,     quotes must be      failures go     PNG/PDF   .ics + .csv
   HN, RSS, seed URLs structured  verbatim; numbers   back to the     + Canva   per-platform
   + Claude web search output     must be quoted;     writer with     steps     windows
                                  slop rules          exact reasons
```

## Why it doesn't produce AI slop

1. **Only cite what we fetched.** Sources are numbered `S1, S2, ...` and their text is
   stored. The writer must attach a *verbatim quote* to every claim.
2. **Quotes are checked by code, not by a model.** `grounding.py` normalises whitespace
   and curly quotes, then requires the quote to occur in the cited source (with a small
   tolerance for a dropped comma, and support for `...` elisions). Paraphrase fails.
3. **Numbers must be backed.** Any figure in the post (`80%`, `120ms`, `2024`) that is
   not inside a verified quote is an error. Thread counters and small counts are ignored.
4. **A slop linter** (`lint.py`) flags filler ("in today's fast-paced world", "delve"),
   unnamed authority ("studies show"), engagement bait ("Agree?"), "it's not X, it's Y",
   fake suspense ("The result?"), em-dash and emoji overuse. Projects can add banned words.
5. **Failures are fed back.** The writer gets the exact findings and up to two revisions.
   A post that still fails is marked `needs_review` and is **not scheduled**.
6. **No sources, no posts.** If research finds nothing usable, the run stops.

## Quick start

```bash
pip install -e '.[claude]'          # or '.[dev]' to run tests
export ANTHROPIC_API_KEY=...         # or `ant auth login`

groundwork platforms
groundwork run "consistent hashing" \
  -p x:thread -p linkedin:carousel -p instagram:carousel -p substack:article \
  --brief "Why mod-N sharding breaks when you add a node, and what rings fix" \
  --url https://en.wikipedia.org/wiki/Consistent_hashing
```

No key? `--offline` skips web search and uses an extractive writer that builds posts out
of source sentences. It is for testing the pipeline, not for publishing.

Two-step flow if you want to vet sources first:

```bash
groundwork research "consistent hashing" -o sources.json   # read the bibliography
groundwork run "consistent hashing" -p x --sources sources.json
```

After hand-editing a post's JSON, re-check it:

```bash
groundwork check runs/<run>/posts/<post>.json runs/<run>/sources.json
groundwork lint my-draft.txt
```

## What a run produces

```
runs/2026-11-03-consistent-hashing/
  report.md            status, errors/warnings, revisions, slot per post
  sources.json         every fetched source with its text
  bibliography.md
  posts/<id>.md        copy-paste text, sources block, claims-and-evidence table,
                       review notes, and how-to-publish steps for that platform
  posts/<id>.json      the structured draft (edit, then `groundwork check`)
  designs/<id>-NN.png  rendered slides; LinkedIn carousels also get <id>.pdf
  canva/<id>.md        step-by-step Canva rebuild: canvas size, colours, fonts,
                       positions, per-page text, visuals to add, export settings
  schedule.ics         import into Google Calendar / Outlook / Apple Calendar
  schedule.csv
```

When a slide needs something text rendering can't do (a diagram, an icon, a photo), the
writer fills `visual` with a concrete description. The PNG gets a labelled placeholder
and the Canva guide spells out how to build it.

## Design: themes, questions and your own images

Six presets ship in `src/groundwork/design/presets/`: `midnight`, `paper`, `terracotta`,
`forest`, `mono`, `sunrise`. A theme is colours, fonts (the names Canva should use),
alignment, accent shape (bar, underline, block, none), an optional inverted cover slide,
slide counter, handle and logo.

```bash
groundwork theme list
groundwork theme preview paper --set accent=#0F766E        # 3 sample slides -> theme-preview.png
groundwork theme save brand --from paper --set handle=@me   # writes themes/brand.yaml, makes it active
groundwork design                                           # interactive: pick, preview, tweak, save
groundwork run "topic" -p instagram:carousel --theme forest # one-off theme
groundwork run "topic" -p instagram:carousel --ask          # asks design questions, then asks for
                                                            # an image for any slide that needs one
```

The wizard checks readability as you go (text, muted text, accent and inverted-cover
contrast) and warns before you save an unreadable theme. Your own presets are YAML files in
`themes_dir`, same format as the built-ins.

When a slide needs a diagram, icon or photo the writer describes it. The run writes
`needs_input.md`; supply your own file and re-render:

```bash
groundwork attach runs/<run>/posts/<post>.json --slide 3 --image ring-diagram.png
groundwork render runs/<run>/posts/<post>.json runs/<run>/sources.json [--theme paper]
```

## Bring your own drafts

Wrote the posts yourself, or want another tool to? `--drafts drafts.json` (keyed by
`platform:format`) skips the model and runs your text through the same grounding, slop
checks, design and scheduling.

## Platform templates are data

Each platform is a YAML file in `src/groundwork/platforms/templates/`: formats, part
counts, character limits, hashtag caps, how to cite (last tweet, first comment, last
slide, footnotes), design size and slide counts, writing guidance, and posting windows.
Put your own YAML in a `templates_dir` to override a platform completely or add a new
one (Threads, Bluesky, YouTube community posts) without touching code.

Default posting windows are placeholders. Replace them with times from your own
analytics.

## Configuration

Copy `groundwork.example.yaml` to `groundwork.yaml`. It sets voice, timezone, which
collectors and RSS feeds to use, extra banned words, model and effort, revision count,
and the visual theme (colours, fonts, handle).

## Design notes

- **Claude finds URLs; our code fetches them.** The web-search collector only harvests
  URLs from Claude's search results. Grounding always runs against the page text we
  downloaded, never against a model's summary.
- **Structured output.** The writer returns a validated `Draft` (Pydantic) through
  `messages.parse`, so claims, slides and alt text are fields, not prose to scrape.
- **Revisions are append-only.** The revise turn resends the previous assistant turn
  unchanged and adds the findings, which keeps the prompt cache warm.
- **Refusal fallback** is enabled server-side (`fallbacks: "default"`).

## Development

```bash
pip install -e '.[dev]'
ruff check . && pytest -q
```

Tests cover grounding (verbatim, paraphrase, elision, unbacked numbers), the slop
linter, template loading and overrides, scheduling (windows, daily caps, time zones,
ICS escaping), collectors (HTML extraction, arXiv/RSS/Atom parsing, mocked Wikipedia),
and full offline runs including the revise-until-grounded loop.

## Roadmap

- Direct publishing for X (API v2) and LinkedIn (Posts API), behind a `--publish` flag.
  Instagram needs a Business account and the Graph API; Substack has no public posting
  API, so it stays copy-paste.
- An LLM judge pass for "does this quote actually support this claim" on top of the
  lexical overlap warning.
- PDF text extraction for papers (PDF links are skipped today).
- Per-platform style presets once the content requirements are final.

MIT licensed.
