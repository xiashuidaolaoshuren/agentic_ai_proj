"""Typed domain models for the AI News Research Agent (Milestone 1)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


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


@dataclass
class NewsItem:
    """Normalized item returned by source connectors."""

    source: SourceKind
    source_id: str
    url: str
    title: str
    published_at: datetime | None = None
    collected_at: datetime = field(default_factory=utcnow)
    author: str | None = None
    stars_or_views: int | None = None
    language: str | None = None
    metadata_completeness: float = 0.0
    raw_snippet: str | None = None
    tags: list[str] = field(default_factory=list)
    topic_matches: list[str] = field(default_factory=list)
    content_confidence: ConfidenceLevel | None = None


@dataclass
class RankedItem:
    """Scored candidate with inspectable ranking evidence."""

    item: NewsItem
    score_total: float
    score_breakdown: dict[str, float] = field(default_factory=dict)
    selected: bool = False
    selection_reason: str = ""


@dataclass
class DigestEntry:
    """One digest row after summarization (UI-agnostic)."""

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


@dataclass
class Digest:
    """Full digest output for a run."""

    generated_at: datetime
    entries: list[DigestEntry]
    topics: list[str] = field(default_factory=list)
    timeframe: str | None = None


@dataclass
class ConnectorWarning:
    """Non-fatal connector issue (pipeline may continue)."""

    connector: str
    code: str
    message: str
    detail: str | None = None


def _encode_value(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, StrEnum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _encode_value(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_encode_value(v) for v in obj]
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _encode_value(getattr(obj, f.name)) for f in fields(obj)}
    raise TypeError(f"Unsupported type for JSON-like encoding: {type(obj)!r}")


def _decode_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Expected datetime or str, got {type(value)!r}")


def news_item_to_dict(item: NewsItem) -> dict[str, Any]:
    return _encode_value(item)  # type: ignore[return-value]


def news_item_from_dict(data: dict[str, Any]) -> NewsItem:
    try:
        src = SourceKind(data["source"])
    except ValueError as exc:
        raise ValueError(f"Invalid source: {data.get('source')!r}") from exc
    cc_raw = data.get("content_confidence")
    cc: ConfidenceLevel | None
    if cc_raw is None:
        cc = None
    else:
        try:
            cc = ConfidenceLevel(cc_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid content_confidence: {cc_raw!r}") from exc
    return NewsItem(
        source=src,
        source_id=str(data["source_id"]),
        url=str(data["url"]),
        title=str(data["title"]),
        published_at=_decode_datetime(data.get("published_at")),
        collected_at=_decode_datetime(data["collected_at"]) or utcnow(),
        author=data.get("author"),
        stars_or_views=data.get("stars_or_views"),
        language=data.get("language"),
        metadata_completeness=float(data.get("metadata_completeness", 0.0)),
        raw_snippet=data.get("raw_snippet"),
        tags=list(data.get("tags") or []),
        topic_matches=list(data.get("topic_matches") or []),
        content_confidence=cc,
    )


def ranked_item_to_dict(ranked: RankedItem) -> dict[str, Any]:
    return _encode_value(ranked)  # type: ignore[return-value]


def ranked_item_from_dict(data: dict[str, Any]) -> RankedItem:
    bd_raw = data.get("score_breakdown") or {}
    if not isinstance(bd_raw, dict):
        raise TypeError("score_breakdown must be a dict")
    score_breakdown = {str(k): float(v) for k, v in bd_raw.items()}
    return RankedItem(
        item=news_item_from_dict(data["item"]),
        score_total=float(data["score_total"]),
        score_breakdown=score_breakdown,
        selected=bool(data.get("selected", False)),
        selection_reason=str(data.get("selection_reason", "")),
    )


def digest_entry_from_dict(data: dict[str, Any]) -> DigestEntry:
    try:
        follow = FollowUpAction(data["follow_up_action"])
    except ValueError as exc:
        raise ValueError(f"Invalid follow_up_action: {data.get('follow_up_action')!r}") from exc
    try:
        sk = SourceKind(data["source_kind"])
    except ValueError as exc:
        raise ValueError(f"Invalid source_kind: {data.get('source_kind')!r}") from exc
    return DigestEntry(
        source_kind=sk,
        source_id=str(data["source_id"]),
        title=str(data["title"]),
        source_name=str(data["source_name"]),
        source_url=str(data["source_url"]),
        summary=str(data["summary"]),
        why_it_matters=str(data["why_it_matters"]),
        background_knowledge=str(data["background_knowledge"]),
        follow_up_action=follow,
        confidence_caveat=data.get("confidence_caveat"),
    )


def digest_entry_to_dict(entry: DigestEntry) -> dict[str, Any]:
    return _encode_value(entry)  # type: ignore[return-value]


def digest_to_dict(digest: Digest) -> dict[str, Any]:
    return _encode_value(digest)  # type: ignore[return-value]


def digest_from_dict(data: dict[str, Any]) -> Digest:
    entries_raw = data.get("entries") or []
    if not isinstance(entries_raw, list):
        raise TypeError("entries must be a list")
    entries = [digest_entry_from_dict(e) for e in entries_raw]
    return Digest(
        generated_at=_decode_datetime(data["generated_at"]) or utcnow(),
        entries=entries,
        topics=list(data.get("topics") or []),
        timeframe=data.get("timeframe"),
    )


def connector_warning_to_dict(w: ConnectorWarning) -> dict[str, Any]:
    return asdict(w)


def connector_warning_from_dict(data: dict[str, Any]) -> ConnectorWarning:
    return ConnectorWarning(
        connector=str(data["connector"]),
        code=str(data["code"]),
        message=str(data["message"]),
        detail=data.get("detail"),
    )
