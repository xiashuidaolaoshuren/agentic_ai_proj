"""Follow-up inspection tools over persisted digest context (Milestone 2 T2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_news_agent.models import (
    ConnectorWarning,
    DigestEntry,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore, FollowupContext
from ai_news_agent.tools.schemas import ToolObservation, ToolObservationStatus

if TYPE_CHECKING:
    from ai_news_agent.connectors.bilibili import BilibiliConnector
    from ai_news_agent.connectors.huggingface import HuggingFaceConnector


def load_latest_digest(*, store: DigestStore) -> ToolObservation:
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return _empty_store_observation()
    if ctx.digest is None:
        return ToolObservation(
            status=ToolObservationStatus.NOT_FOUND,
            summary="No digest persisted for the latest run.",
            data={"run_id": ctx.run_id},
            caveats=["Run data exists but no digest was saved."],
        )

    digest = ctx.digest
    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=f"Loaded latest digest with {len(digest.entries)} entr{'y' if len(digest.entries) == 1 else 'ies'}.",
        data={
            "run_id": ctx.run_id,
            "topics": digest.topics,
            "timeframe": digest.timeframe,
            "generated_at": digest.generated_at.isoformat(),
            "entry_count": len(digest.entries),
            "digest": digest.model_dump(mode="json"),
            "warnings": [w.model_dump(mode="json") for w in ctx.warnings],
        },
        caveats=_warning_caveats(ctx.warnings),
    )


def get_digest_item(
    *,
    store: DigestStore,
    rank: int | None = None,
    source_id: str | None = None,
) -> ToolObservation:
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return _empty_store_observation()

    entry, caveats = _resolve_entry(ctx, rank=rank, source_id=source_id)
    if entry is None:
        return _not_found_observation(rank=rank, source_id=source_id, caveats=caveats)

    resolved_rank = rank if rank is not None else _entry_rank(ctx, entry)
    news_item = _find_news_item(ctx, entry)
    ranked_item = _find_ranked_item(ctx, entry)
    data: dict[str, object] = {
        "rank": resolved_rank,
        "entry": entry.model_dump(mode="json"),
    }
    if news_item is not None:
        data["news_item"] = news_item.model_dump(mode="json")
    if ranked_item is not None:
        data["ranked_item"] = ranked_item.model_dump(mode="json")

    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=f"Digest item {entry.title!r} at rank {resolved_rank}.",
        data=data,
        caveats=caveats + _entry_caveats(entry),
    )


async def get_source_trace(
    *,
    store: DigestStore,
    rank: int | None = None,
    source_id: str | None = None,
    bilibili_connector: BilibiliConnector | None = None,
    huggingface_connector: HuggingFaceConnector | None = None,
) -> ToolObservation:
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return _empty_store_observation()

    entry, caveats = _resolve_entry(ctx, rank=rank, source_id=source_id)
    if entry is None:
        return _not_found_observation(rank=rank, source_id=source_id, caveats=caveats)

    news_item = _find_news_item(ctx, entry)
    if news_item is None:
        return ToolObservation(
            status=ToolObservationStatus.NOT_FOUND,
            summary="No stored source metadata for the requested digest item.",
            data={"rank": rank, "source_id": entry.source_id},
            caveats=caveats + ["Digest entry exists but no matching news item was persisted."],
        )

    enrich_caveats: list[str] = []
    if (
        entry.source_kind is SourceKind.BILIBILI
        and bilibili_connector is not None
    ):
        topics = list(ctx.digest.topics) if ctx.digest is not None else []
        news_item, enrich_ws = await bilibili_connector.enrich_news_item(
            news_item,
            topics,
        )
        enrich_caveats = _warning_caveats(enrich_ws)
        if enrich_caveats:
            enrich_caveats.append(
                "Ranking confidence adjustments (e.g. confidence_adj in score breakdown) "
                "reflect digest-time metadata only; follow-up enrichment does not re-rank items."
            )
        if ctx.run_id is not None:
            store.upsert_news_item(ctx.run_id, news_item)

    if (
        entry.source_kind is SourceKind.HUGGINGFACE
        and huggingface_connector is not None
    ):
        news_item, enrich_ws = await huggingface_connector.enrich_news_item(news_item)
        enrich_caveats = _warning_caveats(enrich_ws)
        if enrich_caveats:
            enrich_caveats.append(
                "Ranking confidence adjustments (e.g. confidence_adj in score breakdown) "
                "reflect digest-time metadata only; follow-up enrichment does not re-rank items."
            )
        if ctx.run_id is not None:
            store.upsert_news_item(ctx.run_id, news_item)

    warnings = _matching_warnings(ctx, entry.source_kind)
    resolved_rank = rank if rank is not None else _entry_rank(ctx, entry)
    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=f"Source trace for {entry.title!r}.",
        data={
            "rank": resolved_rank,
            "entry": entry.model_dump(mode="json"),
            "news_item": news_item.model_dump(mode="json"),
            "warnings": [w.model_dump(mode="json") for w in warnings],
        },
        caveats=caveats + _entry_caveats(entry) + _warning_caveats(warnings) + enrich_caveats,
    )


def get_ranking_explanation(
    *,
    store: DigestStore,
    rank: int | None = None,
    source_id: str | None = None,
) -> ToolObservation:
    ctx = store.get_latest_followup_context()
    if ctx.run_id is None and ctx.digest is None:
        return _empty_store_observation()

    if rank is None and source_id is None:
        return ToolObservation(
            status=ToolObservationStatus.NOT_FOUND,
            summary="No ranking data available for the requested item.",
            caveats=["Provide rank or source_id to identify a ranked item."],
        )

    caveats: list[str] = []
    ranked: RankedItem | None = None
    entry: DigestEntry | None = None

    if rank is not None:
        entry, caveats = _resolve_entry(ctx, rank=rank, source_id=None)
        if entry is None:
            return _not_found_observation(
                rank=rank,
                source_id=source_id,
                caveats=caveats,
                summary="No ranking data available for the requested item.",
            )
        ranked = _find_ranked_item(ctx, entry)
    else:
        assert source_id is not None
        ranked = _find_ranked_by_source_id(ctx, source_id)
        entry = _find_entry_by_source_id(ctx, source_id)

    if ranked is None:
        data: dict[str, object] = {}
        if rank is not None:
            data["rank"] = rank
        if source_id is not None:
            data["source_id"] = source_id
        elif entry is not None:
            data["source_id"] = entry.source_id
        return ToolObservation(
            status=ToolObservationStatus.NOT_FOUND,
            summary="No ranking data available for the requested item.",
            data=data,
            caveats=caveats,
        )

    reason = ranked.selection_reason or "highest score_total among candidates"
    data = {
        "source_id": ranked.item.source_id,
        "score_total": ranked.score_total,
        "score_breakdown": ranked.score_breakdown,
        "selected": ranked.selected,
        "selection_reason": reason,
    }
    if rank is not None:
        data["rank"] = rank

    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=f"Ranking explanation for {ranked.item.title!r}.",
        data=data,
        caveats=caveats + (_entry_caveats(entry) if entry is not None else []),
    )


def _empty_store_observation() -> ToolObservation:
    return ToolObservation(
        status=ToolObservationStatus.EMPTY,
        summary="No saved digest yet. Generate a digest before follow-up inspection.",
    )


def _not_found_observation(
    *,
    rank: int | None,
    source_id: str | None,
    caveats: list[str],
    summary: str | None = None,
) -> ToolObservation:
    data: dict[str, object] = {}
    if rank is not None:
        data["rank"] = rank
    if source_id is not None:
        data["source_id"] = source_id
    return ToolObservation(
        status=ToolObservationStatus.NOT_FOUND,
        summary=summary or _not_found_summary(rank=rank, source_id=source_id),
        data=data,
        caveats=caveats,
    )


def _not_found_summary(*, rank: int | None, source_id: str | None) -> str:
    if rank is not None:
        return f"No digest item at rank {rank}."
    if source_id is not None:
        return f"No digest item with source_id {source_id!r}."
    return "No matching digest item found."


def _warning_caveats(warnings: list[ConnectorWarning]) -> list[str]:
    caveats: list[str] = []
    for warning in warnings:
        caveats.append(_format_warning_caveat(warning))
    return caveats


def _format_warning_caveat(warning: ConnectorWarning) -> str:
    ranking_note = (
        "Digest ranking confidence scores are from collection time and are not "
        "updated by follow-up enrichment."
    )
    if warning.code == "auth_required_missing":
        return (
            "Bilibili subtitle/AI summary unavailable: login cookies were not loaded "
            f"from the environment. {warning.message} {ranking_note}"
        )
    if warning.code in ("auth_required_rejected", "auth_required"):
        return (
            "Bilibili subtitle/AI summary unavailable: login cookies were loaded but "
            f"Bilibili rejected the session (expired or invalid). {warning.message} "
            f"{ranking_note}"
        )
    if warning.code == "anti_bot_blocked":
        return (
            "Bilibili anti-bot/WAF challenge blocked this request. "
            f"{warning.message} "
            "This can occur even when login cookies are configured."
        )
    if warning.code == "proxy_connection_failed":
        return (
            "Bilibili request failed because the configured HTTP proxy is unreachable. "
            f"{warning.message}"
        )
    if warning.code == "subtitle_unavailable":
        return (
            "Bilibili transcript unavailable: the video has no published subtitle/CC "
            f"tracks at source (not a proxy, WAF, or login issue). {warning.message} "
            f"{ranking_note}"
        )
    if warning.code == "subtitle_fetch_failed":
        return (
            "Bilibili transcript unavailable: subtitle tracks were listed but download "
            f"or parsing failed. {warning.message} {ranking_note}"
        )
    if warning.code == "model_card_unavailable":
        return (
            "Hugging Face model card README unavailable: follow-up shows digest-time "
            f"evidence only. {warning.message} {ranking_note}"
        )
    if warning.code == "cookies_not_loaded":
        return f"{warning.connector}:{warning.code} — {warning.message}"
    return f"{warning.connector}:{warning.code} — {warning.message}"


def _resolve_entry(
    ctx: FollowupContext,
    *,
    rank: int | None,
    source_id: str | None,
) -> tuple[DigestEntry | None, list[str]]:
    caveats: list[str] = []
    if rank is None and source_id is None:
        return None, ["Provide rank or source_id to identify a digest item."]

    if ctx.digest is None:
        return None, ["No digest persisted for the latest run."]

    entries = ctx.digest.entries
    if rank is not None:
        if rank < 1:
            return None, ["Rank must be at least 1."]
        if rank > len(entries):
            return None, [f"No digest item at rank {rank}.", "Try a lower rank."]
        return entries[rank - 1], caveats

    assert source_id is not None
    matches = [entry for entry in entries if entry.source_id == source_id]
    if not matches:
        return None, [f"No digest item with source_id {source_id!r}."]
    if len(matches) > 1:
        caveats.append(
            f"Multiple digest entries share source_id {source_id!r}; returning the first match."
        )
    return matches[0], caveats


def _entry_rank(ctx: FollowupContext, entry: DigestEntry) -> int:
    if ctx.digest is None:
        raise ValueError("Cannot resolve rank without a digest")
    for index, candidate in enumerate(ctx.digest.entries, start=1):
        if candidate.source_kind == entry.source_kind and candidate.source_id == entry.source_id:
            return index
    raise ValueError("Digest entry not found in latest digest")


def _find_entry_by_source_id(ctx: FollowupContext, source_id: str) -> DigestEntry | None:
    if ctx.digest is None:
        return None
    for entry in ctx.digest.entries:
        if entry.source_id == source_id:
            return entry
    return None


def _find_news_item(ctx: FollowupContext, entry: DigestEntry) -> NewsItem | None:
    for item in ctx.news_items:
        if item.source == entry.source_kind and item.source_id == entry.source_id:
            return item
    return None


def _find_ranked_item(ctx: FollowupContext, entry: DigestEntry) -> RankedItem | None:
    for ranked in ctx.ranked_items:
        if ranked.item.source == entry.source_kind and ranked.item.source_id == entry.source_id:
            return ranked
    return None


def _find_ranked_by_source_id(ctx: FollowupContext, source_id: str) -> RankedItem | None:
    matches = [ranked for ranked in ctx.ranked_items if ranked.item.source_id == source_id]
    if not matches:
        return None
    return matches[0]


def _entry_caveats(entry: DigestEntry) -> list[str]:
    if entry.confidence_caveat:
        return [entry.confidence_caveat]
    return []


def _matching_warnings(ctx: FollowupContext, source: SourceKind) -> list[ConnectorWarning]:
    return [warning for warning in ctx.warnings if warning.connector == source.value]
