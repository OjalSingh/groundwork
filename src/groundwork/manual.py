"""Copy-paste mode: use any chatbot as the writer, keep every check.

`groundwork prompt` produces a self-contained prompt (sources, rules, platform format and
the JSON shape to answer in). You paste it into any chat, paste the reply into a file, and
`groundwork import` runs it through the same grounding, slop, format, design and
scheduling steps as an API-written draft. If a check fails you get a follow-up message to
paste back into the same chat.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from groundwork.llm.base import WriteRequest
from groundwork.models import Draft, Finding
from groundwork.prompts import WRITER_SYSTEM, revise_prompt, write_prompt

JSON_RULES = """\
Reply with ONE JSON object and nothing else (no commentary before or after, a single
```json code block is fine). It must match this JSON Schema exactly:

{schema}

Rules for the JSON:
- "claims[].quote" must be copied character-for-character from the source text.
- "claims[].source_id" is the id attribute of the source, such as "S1".
- "design.slides[].footnote" credits a source, e.g. "Source: S1".
- "parts" holds one string per tweet / section / paragraph as the format requires.
"""


def build_prompt(req: WriteRequest) -> str:
    schema = json.dumps(Draft.model_json_schema(), indent=1)
    task = write_prompt(req.topic, req.brief, req.voice, req.store, req.platform,
                        req.format_name, req.format)
    return f"{WRITER_SYSTEM}\n\n{task}\n\n{JSON_RULES.format(schema=schema)}"


def fix_message(findings: list[Finding]) -> str:
    return revise_prompt(findings) + "\n\nReply with the complete corrected JSON object only."


def extract_json(text: str) -> dict:
    """Pull the JSON object out of a chat reply: fenced block, or first { to last }."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    last_error = "no JSON object found in the reply"
    for cand in candidates:
        try:
            data = json.loads(cand)
        except json.JSONDecodeError as exc:
            last_error = f"the JSON is invalid ({exc.msg} at line {exc.lineno})"
            continue
        if isinstance(data, dict):
            return data
    raise ValueError(last_error)


def parse_draft(text: str) -> Draft:
    data = extract_json(text)
    try:
        return Draft.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:6])
        raise ValueError(f"the JSON does not match the schema ({problems})") from exc


class StaticWriter:
    """Hands back drafts that already exist; the pipeline treats them like any other writer."""

    def __init__(self, drafts: dict[str, Draft]):
        self.drafts = drafts

    def write(self, req: WriteRequest) -> Draft:
        return self.drafts[f"{req.platform.name}:{req.format_name}"].model_copy(deep=True)

    def revise(self, req: WriteRequest, draft: Draft, findings: list[Finding]) -> Draft:
        return draft
