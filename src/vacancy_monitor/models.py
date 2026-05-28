from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Post:
    source: str
    post_id: str
    url: str
    text: str
    published_at: str | None = None


@dataclass(frozen=True)
class MatchResult:
    accepted: bool
    score: int
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
