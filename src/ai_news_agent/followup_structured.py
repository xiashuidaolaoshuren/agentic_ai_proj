"""Deterministic structured follow-up over the latest persisted digest."""

from __future__ import annotations

from ai_news_agent.models import RankedItem
from ai_news_agent.storage import DigestStore, FollowupContext

NO_SAVED_DIGEST = (
    "No saved digest yet. Ask for a digest first "
    '(for example: "Give me today\'s AI digest").'
)

OPENCLAW_GUIDANCE_FALLBACK = (
    "That follow-up is not supported in OpenClaw structured mode. "
    "Try: show sources, which item should I study first, or show caveats. "
    "For open-ended Q&A, use the Gradio UI."
)


def answer_structured_followup(message: str, ctx: FollowupContext) -> str | None:
    """Return a formatted reply when the message matches a structured intent."""
    low = message.strip().lower()

    if _mentions_sources(low):
        return _format_sources(ctx)

    if _mentions_ranking(low):
        return _format_ranking_pick(ctx)

    if _mentions_caveats(low):
        return _format_caveats(ctx)

    return None


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


def _format_sources(ctx: FollowupContext) -> str:
    if not ctx.digest or not ctx.digest.entries:
        return "No digest entries are available to list sources for."
    lines: list[str] = ["Sources from the latest digest:"]
    for i, e in enumerate(ctx.digest.entries, start=1):
        lines.append(f"{i}. {e.title} — {e.source_url}")
    return "\n".join(lines)


def _format_ranking_pick(ctx: FollowupContext) -> str:
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


def _format_caveats(ctx: FollowupContext) -> str:
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
    "handle_openclaw_structured_followup",
]
