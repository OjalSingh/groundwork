# Getting started with groundwork

## How it works, in one pass

You give it a topic and the platforms you want. It then does six things in order.

1. **Research.** It collects sources: Wikipedia, arXiv, Hacker News links, RSS feeds you list,
   any URLs you pass with `--url`, and (with an API key) Claude web search. Claude only
   *finds* URLs. The pages are downloaded by groundwork, and the full text is saved. Pages
   with too little text are dropped. If nothing usable is found, it stops instead of writing
   unsourced posts.
2. **Write.** Claude gets the numbered sources plus the platform rules (character limits,
   number of parts, how to cite) and your voice notes. It returns a structured draft. Every
   factual claim must come with a word-for-word quote and a source id.
3. **Check.** Plain code, not a model, then checks the draft:
   - each quote really appears in the cited source text
   - every number in the post appears inside a verified quote
   - the slop linter (filler phrases, "studies show", engagement bait, hype words)
   - the platform limits (length, hashtags, slide counts, alt text)
4. **Revise.** Failures go back to Claude with the exact reasons, up to twice. A post that
   still fails is marked `needs_review` and is never scheduled.
5. **Design.** Slides are rendered as PNGs (and a PDF for LinkedIn carousels) in your theme.
   Each design also gets a step-by-step Canva guide. If a slide needs a diagram or photo, it
   lands in `needs_input.md` and you can attach your own image.
6. **Schedule.** Ready posts get the next free slot in each platform's posting windows. You
   get `schedule.ics` (import into Google Calendar) and a CSV, plus a copy-paste file per post
   with the publish steps.

What it does not do: it does not post for you. You publish by hand from the generated files.

## Test it on your PC

You need Python 3.10 or newer and git.

```bash
git clone https://github.com/OjalSingh/groundwork
cd groundwork
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,claude]"
pytest -q                          # 57 tests, a few seconds, no network
```

**Test 1: no API key, no internet needed.** This proves the plumbing and shows the output.

```bash
groundwork platforms
groundwork theme list
groundwork theme preview paper                # opens-able PNG: theme-preview.png
python -m pytest tests/test_pipeline.py -q    # full offline runs, including the revise loop
```

**Test 2: the demo, replayed on your machine.** The demo inputs are in the project files
(`groundwork/demo-consistent-hashing/inputs/`): copy `sources.json` and `drafts.json`, then:

```bash
groundwork run "consistent hashing in load balancers" \
  -p instagram:carousel -p x:thread -p linkedin:post \
  --sources sources.json --drafts drafts.json -o runs
```

Open `runs/<date>-.../report.md`, then one of the files in `posts/`, the PNGs in `designs/`
and `canva/*.md`. Try breaking a quote in `drafts.json` and re-running to see it get caught.

**Test 3: the real thing, with Claude.**

```bash
export ANTHROPIC_API_KEY=sk-ant-...           # Windows PowerShell: $env:ANTHROPIC_API_KEY="..."
cp groundwork.example.yaml groundwork.yaml    # then edit voice, timezone, handle
groundwork run "how DNS caching works" -p x:thread -p linkedin:post --ask -v
```

Pick a topic you know well so you can judge the output. Expect this to cost tens of cents per
run; check your usage page after the first one. I have not been able to run this step myself
(no key in my environment), so treat the first live run as the real test and send me whatever
breaks.

## Make it useful for you

The pipeline is only as good as three inputs you control.

1. **Your voice notes** (`voice:` in `groundwork.yaml`). Paste two or three of your own posts
   you like and describe what you avoid. This does more for quality than any code change.
2. **Your sources.** The best posts come from primary material: official docs, engineering
   blogs, papers, postmortems. Pass them with `--url` and list your favourite blogs under
   `rss_feeds`. Generic web search gives generic posts.
3. **Your review.** Treat output as a strong first draft. Read the "Claims and evidence" table
   in each post file: it shows every claim next to its quote. The checks guarantee the quote
   exists, not that the claim is wise, so keep the final judgement yourself.

A weekly routine that works at personal scale:

- Sunday: pick 3 topics, run `groundwork research` on each, delete weak sources from
  `sources.json`, then `groundwork run ... --sources sources.json`.
- Review `report.md`, fix anything marked `needs_review` (edit the post JSON and run
  `groundwork check`), supply any missing images.
- Import `schedule.ics` into your calendar. At each reminder, open that post's `.md` file and
  paste it into the platform. Each file ends with the exact publish steps.

## Next steps

Do these in order. The first two decide whether the rest is worth building.

1. **Run the offline tests and the demo replay on your PC** (15 minutes). Tell me anything
   that fails on your OS. Fonts are the likeliest issue on Windows or Mac.
2. **Do one live run on a topic you know**, then judge it honestly: are the quotes well
   chosen, does it sound like you, is anything stiff? Send me the post and what bothered you.
3. **Send me the exact per-platform requirements** you promised. They become template edits
   (limits, structure, tone, posting times). This is the highest-value input I'm missing.
4. **Write your voice notes and theme** (`groundwork design`, then `voice:` in the config).
5. **I can then build the parts that make it a habit.** In my order of value:
   - a topic backlog and `groundwork week` to produce a whole week's posts in one command
   - a judge pass that asks "does this quote actually support this claim", beyond the current
     word-overlap warning
   - PDF reading so papers can be sources
   - direct publishing to X and LinkedIn (Instagram needs a Business account; Substack has no
     posting API, so it stays copy-paste)
   - a results log (what you posted, how it did) so voice and timing tune from real data
6. **Later, the knowledge product.** The pipeline's strength is sourced, structured
   breakdowns, which is also what a $10-20 system design guide needs. Once you've run a
   dozen topics, the posts, sources and slides are the raw material for it.
