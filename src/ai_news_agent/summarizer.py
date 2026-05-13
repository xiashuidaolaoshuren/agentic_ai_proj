"""Summarize ranked items into a :class:`Digest` (Milestone 1 Task 8)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
    utcnow,
)


def summarize_ranked_items(
    ranked_items: list[RankedItem],
    *,
    generated_at: datetime | None = None,
    topics: list[str] | None = None,
    timeframe: str | None = None,
    model: Any | None = None,
) -> Digest:
    """Build a digest from selected ranked rows using ``model.generate_entry_fields``."""
    ts = generated_at if generated_at is not None else utcnow()
    topics_list = list(topics) if topics is not None else []

    selected = [r for r in ranked_items if r.selected]
    if not selected:
        return Digest(
            generated_at=ts,
            entries=[],
            topics=topics_list,
            timeframe=timeframe,
        )

    if model is None:
        raise ValueError("model is required when there are selected ranked_items to summarize")

    entries: list[DigestEntry] = []
    global_topics_payload = topics_list

    for r in selected:
        ctx = _context_payload(r, global_topics_payload, timeframe)
        raw = model.generate_entry_fields(ctx)
        entries.append(_build_digest_entry(r.item, raw))

    return Digest(generated_at=ts, entries=entries, topics=topics_list, timeframe=timeframe)


def _context_payload(
    ranked: RankedItem,
    topics: list[str],
    timeframe: str | None,
) -> dict[str, Any]:
    it = ranked.item
    return {
        "digest_topics": topics,
        "digest_timeframe": timeframe,
        "rank_score_total": ranked.score_total,
        "rank_selection_reason": ranked.selection_reason,
        "score_breakdown": dict(ranked.score_breakdown),
        "source_kind": it.source.value,
        "source_id": it.source_id,
        "title": it.title,
        "url": it.url,
        "author": it.author or "",
        "language_hint": it.language or "",
        "published_at_iso": it.published_at.isoformat() if it.published_at else "",
        "collected_at_iso": it.collected_at.isoformat() if it.collected_at else "",
        "metadata_completeness": it.metadata_completeness,
        "stars_or_views": it.stars_or_views,
        "raw_snippet": it.raw_snippet or "",
        "topic_matches": list(it.topic_matches),
        "content_confidence": it.content_confidence.value if it.content_confidence else "",
        "tags": list(it.tags),
    }


def _source_display_name(item: NewsItem) -> str:
    if item.author:
        return str(item.author)
    if item.source is SourceKind.GITHUB:
        return "GitHub"
    if item.source is SourceKind.BILIBILI:
        return "Bilibili"
    return str(item.source.value)


def _normalize_follow_action(raw: str | None) -> FollowUpAction:
    if raw is None or not str(raw).strip():
        return FollowUpAction.READ
    key = str(raw).strip().lower().replace("-", "_")
    lut: dict[str, FollowUpAction] = {
        "read": FollowUpAction.READ,
        "watch": FollowUpAction.WATCH,
        "try": FollowUpAction.TRY,
        "build": FollowUpAction.BUILD,
    }
    return lut.get(key, FollowUpAction.READ)


def _normalize_text_field(val: Any, fallback: str) -> str:
    if val is None:
        return fallback
    s = str(val).strip()
    return s if s else fallback


def _build_digest_entry(item: NewsItem, raw: dict[str, Any]) -> DigestEntry:
    fu = _normalize_follow_action(raw.get("follow_up_action"))
    caveat: str | None = None

    if fu is FollowUpAction.READ and raw.get("follow_up_action") not in (None, "", "read", "READ"):
        caveat = (
            _append_caveat(
                caveat,
                f'Unrecognized follow_up_action={raw.get("follow_up_action")!r}; defaulted to read.',
            )
        )

    if item.content_confidence is ConfidenceLevel.LOW:
        caveat = _append_caveat(
            caveat,
            "Source metadata is limited or low-confidence; summaries may omit unavailable details.",
        )

    snippet = item.raw_snippet
    if snippet is None or not str(snippet).strip():
        caveat = _append_caveat(caveat, "No excerpt/snippet available; summary is metadata-only.")

    return DigestEntry(
        source_kind=item.source,
        source_id=item.source_id,
        title=item.title,
        source_name=_source_display_name(item),
        source_url=item.url,
        summary=_normalize_text_field(raw.get("summary"), item.title),
        why_it_matters=_normalize_text_field(raw.get("why_it_matters"), ""),
        background_knowledge=_normalize_text_field(raw.get("background_knowledge"), ""),
        follow_up_action=fu,
        confidence_caveat=caveat,
    )


def _append_caveat(existing: str | None, phrase: str) -> str:
    if not phrase:
        return existing or ""
    if existing:
        return f"{existing} {phrase}"
    return phrase
