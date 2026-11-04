"""Core data types shared by every stage of the pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class Source(BaseModel):
    """A document we actually fetched. Claims may only cite these."""

    id: str = Field(description="Short stable id such as S1, assigned by the SourceStore.")
    url: str
    title: str
    publisher: str = ""
    published: str | None = None
    retrieved_at: datetime
    collector: str = Field(description="Which collector found it: hn, arxiv, wikipedia, rss, web.")
    text: str = Field(description="Extracted plain text used for grounding checks.")

    def excerpt(self, limit: int = 4000) -> str:
        return self.text[:limit]


class Claim(BaseModel):
    """A factual statement in a post, tied to a verbatim quote from one source."""

    statement: str = Field(description="The claim as it appears (or is paraphrased) in the post.")
    source_id: str = Field(description="Id of the Source that supports it, e.g. S2.")
    quote: str = Field(description="A verbatim span copied from that source's text.")


class Slide(BaseModel):
    """One visual unit: a carousel slide, a quote card, a header image."""

    heading: str = ""
    body: str = ""
    footnote: str = Field(default="", description="Source credit shown on the slide.")
    visual: str = Field(
        default="",
        description="A diagram, photo or icon this slide needs that text rendering cannot "
        "produce, described concretely (e.g. 'three boxes: client -> load balancer -> two "
        "app servers'). Leave empty for text-only slides.",
    )
    image: str = Field(
        default="",
        description="Path to an image you supplied for this slide's visual. Set by "
        "`groundwork attach`, never by the writer.",
    )


class DesignSpec(BaseModel):
    kind: str = Field(description="carousel | quote_card | header | none")
    slides: list[Slide] = Field(default_factory=list)
    alt_text: str = ""


class Draft(BaseModel):
    """What the writer returns for one platform format."""

    platform: str
    format: str
    title: str = ""
    hook: str = Field(description="The opening line. Must be specific, not clickbait.")
    parts: list[str] = Field(
        description="Ordered body pieces. One item for a single post, one per tweet for a "
        "thread, one per section for a long-form article."
    )
    cta: str = ""
    hashtags: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    design: DesignSpec = Field(default_factory=lambda: DesignSpec(kind="none"))

    def full_text(self) -> str:
        pieces = [self.hook, *self.parts]
        if self.cta:
            pieces.append(self.cta)
        if self.hashtags:
            pieces.append(" ".join(f"#{h.lstrip('#')}" for h in self.hashtags))
        return "\n\n".join(p for p in pieces if p)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Finding(BaseModel):
    check: str
    severity: Severity
    message: str
    excerpt: str = ""


class PostStatus(str, Enum):
    READY = "ready"
    NEEDS_REVIEW = "needs_review"


class Post(BaseModel):
    """A draft plus everything the checks said about it."""

    id: str
    draft: Draft
    findings: list[Finding] = Field(default_factory=list)
    revisions: int = 0
    status: PostStatus = PostStatus.NEEDS_REVIEW
    scheduled_for: datetime | None = None
    image_paths: list[str] = Field(default_factory=list)
    canva_guide_path: str | None = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.ERROR]
