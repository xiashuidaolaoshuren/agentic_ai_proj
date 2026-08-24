"""Connector search tools through the SourceConnector boundary (Milestone 2 T3)."""

from __future__ import annotations

from ai_news_agent.connectors.base import ConnectorRequest, SourceConnector
from ai_news_agent.models import ConnectorWarning
from ai_news_agent.rendering import render_search_items_text
from ai_news_agent.tools.schemas import (
    HuggingFaceSearchArgs,
    SearchQueryInput,
    ToolObservation,
    ToolObservationStatus,
    ZhihuSearchArgs,
)


async def search_github_ai_news(
    *,
    connector: SourceConnector,
    search: SearchQueryInput,
    timeframe: str | None = None,
) -> ToolObservation:
    return await _search_connector(
        connector_name="github",
        connector=connector,
        search=search,
        timeframe=timeframe,
    )


async def search_bilibili_ai_news(
    *,
    connector: SourceConnector,
    search: SearchQueryInput,
    timeframe: str | None = None,
) -> ToolObservation:
    return await _search_connector(
        connector_name="bilibili",
        connector=connector,
        search=search,
        timeframe=timeframe,
    )


async def search_juya_ai_news(
    *,
    connector: SourceConnector,
    search: SearchQueryInput,
    timeframe: str | None = None,
) -> ToolObservation:
    return await _search_connector(
        connector_name="juya",
        connector=connector,
        search=search,
        timeframe=timeframe,
    )


async def search_huggingface_trending_models(
    *,
    connector: SourceConnector,
    args: HuggingFaceSearchArgs,
) -> ToolObservation:
    request = ConnectorRequest(
        topics=[],
        max_items=args.max_results,
        huggingface_discovery_mode=args.discovery_mode,
        huggingface_search=args.search,
        huggingface_pipeline_tag=args.pipeline_tag,
    )
    return await _collect_observation(
        connector_name="huggingface",
        connector=connector,
        request=request,
    )


async def search_zhihu_practitioner_insights(
    *,
    connector: SourceConnector,
    args: ZhihuSearchArgs,
) -> ToolObservation:
    request = ConnectorRequest(
        topics=list(args.topics),
        max_items=args.max_results,
    )
    return await _collect_observation(
        connector_name="zhihu",
        connector=connector,
        request=request,
    )


async def _collect_observation(
    *,
    connector_name: str,
    connector: SourceConnector,
    request: ConnectorRequest,
    extra_data: dict[str, object] | None = None,
) -> ToolObservation:
    extra = dict(extra_data or {})
    try:
        result = await connector.collect(request)
    except Exception as exc:
        return ToolObservation(
            status=ToolObservationStatus.ERROR,
            summary=f"{connector_name} connector search failed.",
            data={"connector": connector_name, **extra},
            caveats=[str(exc)],
        )

    items = list(result.items)
    if connector_name == "huggingface":
        from ai_news_agent.huggingface_families import group_huggingface_families

        items = group_huggingface_families(items, limit=request.max_items)

    warnings = list(result.warnings)
    item_count = len(items)
    data: dict[str, object] = {
        "connector": connector_name,
        "item_count": item_count,
        "raw_count": result.raw_count,
        "items": [item.model_dump(mode="json") for item in items],
        "warnings": [warning.model_dump(mode="json") for warning in warnings],
        **extra,
    }
    if items:
        data["formatted_text"] = render_search_items_text(items)
    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=(
            f"Found {item_count} {connector_name} result{'s' if item_count != 1 else ''}."
        ),
        data=data,
        caveats=_warning_caveats(warnings),
    )


async def _search_connector(
    *,
    connector_name: str,
    connector: SourceConnector,
    search: SearchQueryInput,
    timeframe: str | None,
) -> ToolObservation:
    query = search.query.strip()
    request = ConnectorRequest(
        topics=[query],
        max_items=search.max_results,
        timeframe=timeframe,
    )
    try:
        result = await connector.collect(request)
    except Exception as exc:
        return ToolObservation(
            status=ToolObservationStatus.ERROR,
            summary=f"{connector_name} connector search failed.",
            data={"connector": connector_name, "query": query},
            caveats=[str(exc)],
        )

    warnings = list(result.warnings)
    item_count = len(result.items)
    data: dict[str, object] = {
        "connector": connector_name,
        "query": query,
        "item_count": item_count,
        "raw_count": result.raw_count,
        "items": [item.model_dump(mode="json") for item in result.items],
        "warnings": [warning.model_dump(mode="json") for warning in warnings],
    }
    if result.items:
        data["formatted_text"] = render_search_items_text(result.items)
    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=(
            f"Found {item_count} {connector_name} result{'s' if item_count != 1 else ''} "
            f"for {query!r}."
        ),
        data=data,
        caveats=_warning_caveats(warnings),
    )


def _warning_caveats(warnings: list[ConnectorWarning]) -> list[str]:
    return [f"{warning.connector}:{warning.code} — {warning.message}" for warning in warnings]
