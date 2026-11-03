"""Claude backends: a writer (structured output) and a web researcher (web search tool).

Requires `pip install groundwork[claude]` and credentials the Anthropic SDK can find
(ANTHROPIC_API_KEY, or an `ant auth login` profile).
"""

from __future__ import annotations

import logging

from groundwork.llm.base import WriteRequest
from groundwork.models import Draft, Finding
from groundwork.prompts import WRITER_SYSTEM, revise_prompt, write_prompt

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side refusal fallback: if a request is declined, the API re-runs it on a
# fallback model chosen by refusal category.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise SystemExit("Install the Claude extra: pip install 'groundwork[claude]'") from exc
    return anthropic.Anthropic()


class ClaudeWriter:
    def __init__(self, model: str = DEFAULT_MODEL, effort: str = "high"):
        self.client = _client()
        self.model = model
        self.effort = effort

    def _parse(self, messages: list[dict]) -> Draft:
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=WRITER_SYSTEM,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            output_format=Draft,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            messages=messages,
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"Model declined the request: {resp.stop_details}")
        if resp.parsed_output is None:
            raise RuntimeError(f"No structured output (stop_reason={resp.stop_reason})")
        self._last = resp
        return resp.parsed_output

    def write(self, req: WriteRequest) -> Draft:
        prompt = write_prompt(req.topic, req.brief, req.voice, req.store, req.platform,
                              req.format_name, req.format)
        self._history = [{"role": "user", "content": prompt}]
        return self._parse(self._history)

    def revise(self, req: WriteRequest, draft: Draft, findings: list[Finding]) -> Draft:
        # Append-only history: resend the previous assistant turn unchanged.
        self._history = [
            *self._history,
            {"role": "assistant", "content": self._last.content},
            {"role": "user", "content": revise_prompt(findings)},
        ]
        return self._parse(self._history)


RESEARCH_PROMPT = """\
Find the best primary and expert sources on: {topic}

Prefer, in order: official documentation and specifications, papers, engineering blogs
from the teams that built the system, talks and postmortems, reputable journalism.
Avoid SEO listicles, content farms, and AI-generated summaries. Find up to {limit}
distinct sources. Finish with one line per source: URL then a few words on why it is
credible."""


class ClaudeWebResearcher:
    """Uses Claude's server-side web search to discover URLs.

    We only take URLs from it. The pages are fetched by our own code so grounding is
    checked against the real page text, not the model's summary of it.
    """

    def __init__(self, model: str = DEFAULT_MODEL, max_searches: int = 8):
        self.client = _client()
        self.model = model
        self.max_searches = max_searches

    def find_urls(self, topic: str, limit: int) -> list[str]:
        messages: list[dict] = [{"role": "user",
                                 "content": RESEARCH_PROMPT.format(topic=topic, limit=limit)}]
        urls: list[str] = []
        for _ in range(4):  # resume pause_turn a few times at most
            resp = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                output_config={"effort": "medium"},
                tools=[{"type": "web_search_20260209", "name": "web_search",
                        "max_uses": self.max_searches}],
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=messages,
            )
            for block in resp.content:
                if block.type == "web_search_tool_result" and isinstance(block.content, list):
                    urls += [r.url for r in block.content if getattr(r, "url", None)]
                if block.type == "text":
                    for c in getattr(block, "citations", None) or []:
                        if getattr(c, "url", None):
                            urls.insert(0, c.url)  # cited results first
            if resp.stop_reason != "pause_turn":
                break
            messages.append({"role": "assistant", "content": resp.content})
        seen, ordered = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                ordered.append(u)
        return ordered[:limit]
