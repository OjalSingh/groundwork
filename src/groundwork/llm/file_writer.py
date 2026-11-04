"""Bring your own drafts: a Writer that reads drafts from a JSON file.

Use it when you (or another tool) wrote the posts and you want them verified, linted,
designed and scheduled like any other. The file maps "platform:format" to a draft, or
to a list of drafts: the first is the initial write, later ones are returned one per
revision request, which is how you replay a revise loop.
"""

from __future__ import annotations

import json
from pathlib import Path

from groundwork.llm.base import WriteRequest
from groundwork.models import Draft, Finding


class FileWriter:
    def __init__(self, path: Path):
        raw = json.loads(Path(path).read_text())
        self.queues: dict[str, list[Draft]] = {
            key: [Draft.model_validate(d) for d in (v if isinstance(v, list) else [v])]
            for key, v in raw.items()
        }
        self.served: dict[str, int] = {}

    def _next(self, req: WriteRequest, advance: bool) -> Draft:
        key = f"{req.platform.name}:{req.format_name}"
        if key not in self.queues:
            raise KeyError(f"No draft for {key!r} in the drafts file; it has {sorted(self.queues)}")
        queue = self.queues[key]
        i = self.served.get(key, -1) + (1 if advance else 0)
        i = min(max(i, 0), len(queue) - 1)  # past the end: keep returning the last version
        self.served[key] = i
        return queue[i].model_copy(deep=True)

    def write(self, req: WriteRequest) -> Draft:
        self.served.pop(f"{req.platform.name}:{req.format_name}", None)
        return self._next(req, advance=False)

    def revise(self, req: WriteRequest, draft: Draft, findings: list[Finding]) -> Draft:
        return self._next(req, advance=True)
