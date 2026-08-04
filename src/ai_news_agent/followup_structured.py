"""Deterministic structured follow-up over the latest persisted digest."""

from __future__ import annotations

import re

from ai_news_agent.juya_followup import (
    format_juya_issue_deep_dive,
    is_juya_news_item,
    match_news_item_for_digest_entry,
)
from ai_news_agent.models import DigestEntry, RankedItem
from ai_news_agent.storage import DigestStore, FollowupContext

NO_SAVED_DIGEST = (
    "No saved digest yet. Ask for a digest first "
    '(for example: "Give me today\'s AI digest").'
)

OPENCLAW_GUIDANCE_FALLBACK = (
    "That follow-up is not supported in OpenClaw structured mode. "
    "Try: show sources, item 1 / #2 / the second one / the first news, which item should I study first, "
    "or show caveats. For open-ended Q&A, use the Gradio UI."
)

_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "6th": 6,
    "seventh": 7,
    "7th": 7,
    "eighth": 8,
    "8th": 8,
    "ninth": 9,
    "9th": 9,
    "tenth": 10,
    "10th": 10,
}

_ORDINAL_ALT = "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True))

_RANK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*(\d+)\b"),
    re.compile(r"\brank\s+(\d+)\b", re.I),
    re.compile(r"\bitem\s+(\d+)\b", re.I),
    re.compile(r"\bnumber\s+(\d+)\b", re.I),
    re.compile(
        rf"\b({_ORDINAL_ALT})\s+(?:item|issue|entry|story|one)\b",
        re.I,
    ),
    re.compile(rf"\bthe\s+({_ORDINAL_ALT})\s+one\b", re.I),
    re.compile(
        rf"\bfollow\s*[- ]?up\b.*?\b({_ORDINAL_ALT})\b",
        re.I,
    ),
    re.compile(r"\bfollow\s*[- ]?up\b.*?\bitem\s+(\d+)\b", re.I),
    re.compile(r"\bfollow\s*[- ]?up\b.*?\b#?\s*(\d+)\b", re.I),
    re.compile(rf"\b({_ORDINAL_ALT})\s+issue\b", re.I),
    re.compile(rf"\bdigest\b.*?\bthe\s+({_ORDINAL_ALT})\s+news\b", re.I),
    re.compile(rf"\bthe\s+({_ORDINAL_ALT})\s+news\b", re.I),
    re.compile(rf"\b({_ORDINAL_ALT})\s+juya\s+news\b", re.I),
)


def parse_rank_from_message(message: str) -> int | None:
    """Extract a 1-based digest rank from a follow-up message, if present."""
    text = message.strip()
    if not text:
        return None

    for pattern in _RANK_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        token = match.group(1).lower()
        if token.isdigit():
            rank = int(token)
            return rank if rank >= 1 else None
        rank = _ORDINAL_WORDS.get(token)
        if rank is not None:
            return rank
    return None


def answer_structured_followup(message: str, ctx: FollowupContext) -> str | None:
    """Return a formatted reply when the message matches a structured intent."""
    low = message.strip().lower()

    if _mentions_sources(low):
        return format_sources(ctx)

    if _mentions_ranking(low):
        return format_ranking_pick(ctx)

    rank = parse_rank_from_message(message)
    if rank is not None:
        return format_rank_item(ctx, rank)

    if _mentions_caveats(low):
        return format_caveats(ctx)

    return None


def is_structured_followup(message: str) -> bool:
    """Return True when the message matches a structured follow-up intent."""
    low = message.strip().lower()
    if not low:
        return False

    if _mentions_sources(low):
        return True

    if _mentions_ranking(low):
        return True

    if parse_rank_from_message(message) is not None:
        return True

    if _mentions_caveats(low):
        return True

    return False


def handle_openclaw_structured_followup(
    *,
    message: str,
    store: DigestStore,
) -> dict[str, object]:
    """Resolve an OpenClaw follow-up message against the latest digest context."""
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return {
            "text": NO_SAVED_DIGEST,
            "run_id": None,
            "path": "no_digest",
        }

    structured = answer_structured_followup(message, ctx)
    if structured is not None:
        return {
            "text": structured,
            "run_id": ctx.run_id,
            "path": "structured",
        }

    return {
        "text": OPENCLAW_GUIDANCE_FALLBACK,
        "run_id": ctx.run_id,
        "path": "guidance",
    }


def _mentions_sources(low: str) -> bool:
    keys = ("show sources", "list sources", "original links", "source links", "urls")
    return any(k in low for k in keys)


def _mentions_ranking(low: str) -> bool:
    keys = ("study first", "where should i start", "top pick", "best item", "priority")
    return any(k in low for k in keys)


def _mentions_caveats(low: str) -> bool:
    keys = ("caveat", "warnings", "confidence", "limitations", "issues")
    return any(k in low for k in keys)


def format_sources(ctx: FollowupContext) -> str:
    if not ctx.digest or not ctx.digest.entries:
        return "No digest entries are available to list sources for."
    lines: list[str] = ["Sources from the latest digest:"]
    for i, e in enumerate(ctx.digest.entries, start=1):
        lines.append(f"{i}. {e.title} — {e.source_url}")
    return "\n".join(lines)


def format_ranking_pick(ctx: FollowupContext) -> str:
    ranked = ctx.ranked_items
    if not ranked:
        return "No ranking data is available for the latest digest run."

    selected = [r for r in ranked if r.selected]
    pool: list[RankedItem] = selected if selected else ranked
    best = max(pool, key=lambda r: r.score_total)

    why = best.selection_reason or "highest score_total among candidates"
    return (
        f"Suggested starting point: {best.item.title}\n"
        f"- URL: {best.item.url}\n"
        f"- Score: {best.score_total:.3f}\n"
        f"- Reason: {why}"
    )


def format_rank_item(ctx: FollowupContext, rank: int) -> str:
    if ctx.digest is None or not ctx.digest.entries:
        return "No digest entries are available for rank-targeted follow-up."

    entries = ctx.digest.entries
    if rank < 1 or rank > len(entries):
        return f"No digest item at rank {rank}."

    entry = entries[rank - 1]
    news_item = match_news_item_for_digest_entry(entry, ctx.news_items)
    if news_item is not None and is_juya_news_item(news_item):
        return format_juya_issue_deep_dive(entry, news_item, rank=rank)
    return _format_digest_entry_detail(entry, rank=rank)


def _format_digest_entry_detail(entry: DigestEntry, *, rank: int) -> str:
    lines = [
        f"Digest item {rank}: {entry.title}",
        f"- URL: {entry.source_url}",
        f"- Summary: {entry.summary}",
        f"- Why it matters: {entry.why_it_matters}",
    ]
    if entry.confidence_caveat:
        lines.append(f"- Confidence caveat: {entry.confidence_caveat}")
    return "\n".join(lines)


def format_caveats(ctx: FollowupContext) -> str:
    lines: list[str] = []

    if ctx.warnings:
        lines.append("Connector warnings:")
        for w in ctx.warnings:
            lines.append(f"- [{w.connector}] {w.code}: {w.message}")

    caveats: list[str] = []
    if ctx.digest:
        for e in ctx.digest.entries:
            if e.confidence_caveat:
                caveats.append(f"- {e.title}: {e.confidence_caveat}")

    if caveats:
        if lines:
            lines.append("")
        lines.append("Per-entry confidence notes:")
        lines.extend(caveats)

    if not lines:
        return "No warnings or confidence caveats were recorded for the latest digest."

    return "\n".join(lines)


__all__ = [
    "NO_SAVED_DIGEST",
    "OPENCLAW_GUIDANCE_FALLBACK",
    "answer_structured_followup",
    "format_caveats",
    "format_rank_item",
    "format_ranking_pick",
    "format_sources",
    "handle_openclaw_structured_followup",
    "is_structured_followup",
    "parse_rank_from_message",
]
