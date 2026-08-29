"""Historical digest search types, tokens, and validation (Milestone 7D T1)."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ai_news_agent.models import SourceKind
from ai_news_agent.sources import ALLOWED_SOURCES

HISTORY_CANDIDATE_CAP = 10_000

_HISTORICAL_ITEM_REF_PATTERN = re.compile(r"^d(\d+):r(\d+)$")


class HistoricalItemRef(BaseModel):
    """Stable pointer to one saved digest entry."""

    model_config = ConfigDict(extra="ignore")

    digest_id: int
    run_id: int
    entry_id: int
    rank: int


class HistorySearchQuery(BaseModel):
    """Input for historical digest search."""

    model_config = ConfigDict(extra="ignore")

    text: str | None = None
    sources: list[str] | None = None
    topics: list[str] | None = None
    since: date | None = None
    until: date | None = None
    limit: int = Field(default=10)

    @field_validator("text", mode="before")
    @classmethod
    def _normalize_blank_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value

    @field_validator("sources")
    @classmethod
    def _validate_sources(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for name in value:
            normalized = str(name).strip().lower()
            if normalized not in ALLOWED_SOURCES:
                allowed = ", ".join(sorted(ALLOWED_SOURCES))
                raise ValueError(f"Unknown source {normalized!r}; allowed: {allowed}")
        return value

    @field_validator("limit")
    @classmethod
    def _validate_limit(cls, value: int) -> int:
        if value < 1 or value > 50:
            raise ValueError("limit must be between 1 and 50")
        return value

    @model_validator(mode="after")
    def _validate_query(self) -> HistorySearchQuery:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must not be after until")
        if not self._has_search_criterion():
            raise ValueError("at least one search criterion is required")
        return self

    def _has_search_criterion(self) -> bool:
        if self.text is not None:
            return True
        if self.sources:
            return True
        if self.topics:
            return True
        if self.since is not None or self.until is not None:
            return True
        return False


class HistorySearchMatch(BaseModel):
    """One ranked historical digest entry match."""

    model_config = ConfigDict(extra="ignore")

    ref: HistoricalItemRef
    generated_at: datetime
    source_kind: SourceKind
    title: str
    url: str
    excerpt: str | None = None
    score: float


class HistorySearchResult(BaseModel):
    """Historical search response envelope."""

    model_config = ConfigDict(extra="ignore")

    matches: list[HistorySearchMatch] = Field(default_factory=list)
    scanned_count: int = 0
    archive_truncated: bool = False
    caveats: list[str] = Field(default_factory=list)


def format_historical_item_ref(ref: HistoricalItemRef) -> str:
    return f"d{ref.digest_id}:r{ref.rank}"


def parse_historical_item_ref(token: str) -> HistoricalItemRef:
    match = _HISTORICAL_ITEM_REF_PATTERN.match(token.strip())
    if match is None:
        raise ValueError(f"Invalid historical item reference token: {token!r}")
    digest_id = int(match.group(1))
    rank = int(match.group(2))
    return HistoricalItemRef(digest_id=digest_id, run_id=0, entry_id=0, rank=rank)


def validate_history_search_query(**kwargs: Any) -> HistorySearchQuery:
    return HistorySearchQuery(**kwargs)


def score_historical_candidate(*, query: HistorySearchQuery, candidate: dict[str, Any]) -> float:
    raise NotImplementedError


__all__ = [
    "HISTORY_CANDIDATE_CAP",
    "HistoricalItemRef",
    "HistorySearchMatch",
    "HistorySearchQuery",
    "HistorySearchResult",
    "format_historical_item_ref",
    "parse_historical_item_ref",
    "score_historical_candidate",
    "validate_history_search_query",
]
