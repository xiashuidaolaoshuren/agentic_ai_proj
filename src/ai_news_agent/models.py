"""Typed domain models for the AI News Research Agent (Milestone 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class SourceKind(StrEnum):
    GITHUB = "github"
    BILIBILI = "bilibili"


class FollowUpAction(StrEnum):
    READ = "read"
    WATCH = "watch"
    TRY = "try"
    BUILD = "build"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class NewsItem(BaseModel):
    """Normalized item returned by source connectors."""

    model_config = ConfigDict(extra="ignore")

    source: SourceKind
    source_id: str
    url: str
    title: str
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=utcnow)
    author: str | None = None
    stars_or_views: int | None = None
    language: str | None = None
    metadata_completeness: float = 0.0
    raw_snippet: str | None = None
    tags: list[str] = Field(default_factory=list)
    topic_matches: list[str] = Field(default_factory=list)
    content_confidence: ConfidenceLevel | None = None

    @field_validator("tags", "topic_matches", mode="before")
    @classmethod
    def _coalesce_none_list(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("collected_at", mode="before")
    @classmethod
    def _coalesce_none_collected_at(cls, value: Any) -> Any:
        if value is None:
            return utcnow()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class RankedItem(BaseModel):
    """Scored candidate with inspectable ranking evidence."""

    model_config = ConfigDict(extra="ignore")

    item: NewsItem
    score_total: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    selected: bool = False
    selection_reason: str = ""

    @field_validator("score_breakdown", mode="before")
    @classmethod
    def _coalesce_none_score_breakdown(cls, value: Any) -> Any:
        return {} if value is None else value


class DigestEntry(BaseModel):
    """One digest row after summarization (UI-agnostic)."""

    model_config = ConfigDict(extra="ignore")

    source_kind: SourceKind
    source_id: str
    title: str
    source_name: str
    source_url: str
    summary: str
    why_it_matters: str
    background_knowledge: str
    follow_up_action: FollowUpAction
    confidence_caveat: str | None = None


class Digest(BaseModel):
    """Full digest output for a run."""

    model_config = ConfigDict(extra="ignore")

    generated_at: datetime
    entries: list[DigestEntry]
    topics: list[str] = Field(default_factory=list)
    timeframe: str | None = None

    @field_validator("entries", mode="before")
    @classmethod
    def _coalesce_none_entries(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("generated_at", mode="before")
    @classmethod
    def _coalesce_none_generated_at(cls, value: Any) -> Any:
        if value is None:
            return utcnow()
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ConnectorWarning(BaseModel):
    """Non-fatal connector issue (pipeline may continue)."""

    model_config = ConfigDict(extra="ignore")

    connector: str
    code: str
    message: str
    detail: str | None = None
