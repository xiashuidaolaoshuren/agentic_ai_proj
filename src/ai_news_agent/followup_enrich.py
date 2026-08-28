"""Live Hugging Face enrichment helpers for structured rank follow-up."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_news_agent.juya_followup import match_news_item_for_digest_entry
from ai_news_agent.models import SourceKind
from ai_news_agent.storage import DigestStore, FollowupContext

if TYPE_CHECKING:
    from ai_news_agent.connectors.huggingface import HuggingFaceConnector


async def enrich_huggingface_for_rank(
    ctx: FollowupContext,
    store: DigestStore,
    rank: int,
    *,
    huggingface_connector: HuggingFaceConnector | None,
) -> tuple[FollowupContext, bool]:
    """Refresh context after optional live model-card fetch; return enrich-failed flag."""
    if ctx.digest is None or rank < 1 or rank > len(ctx.digest.entries):
        return ctx, False
    entry = ctx.digest.entries[rank - 1]
    if entry.source_kind is not SourceKind.HUGGINGFACE:
        return ctx, False
    news_item = match_news_item_for_digest_entry(entry, ctx.news_items)
    if news_item is None or huggingface_connector is None:
        return ctx, False

    enriched, warnings = await huggingface_connector.enrich_news_item(news_item)
    failed = bool(warnings)
    if enriched is not news_item and ctx.run_id is not None:
        store.upsert_news_item(ctx.run_id, enriched)
        ctx = store.get_latest_followup_context()
    return ctx, failed


__all__ = ["enrich_huggingface_for_rank"]
