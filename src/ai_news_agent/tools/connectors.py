"""Connector search tools through the SourceConnector boundary (Milestone 2 T3)."""

from __future__ import annotations

from ai_news_agent.connectors.base import ConnectorRequest, SourceConnector
from ai_news_agent.models import ConnectorWarning, connector_warning_to_dict, news_item_to_dict
from ai_news_agent.tools.schemas import SearchQueryInput, ToolObservation, ToolObservationStatus


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
    return ToolObservation(
        status=ToolObservationStatus.OK,
        summary=(
            f"Found {item_count} {connector_name} result{'s' if item_count != 1 else ''} "
            f"for {query!r}."
        ),
        data={
            "connector": connector_name,
            "query": query,
            "item_count": item_count,
            "raw_count": result.raw_count,
            "items": [news_item_to_dict(item) for item in result.items],
            "warnings": [connector_warning_to_dict(warning) for warning in warnings],
        },
        caveats=_warning_caveats(warnings),
    )


def _warning_caveats(warnings: list[ConnectorWarning]) -> list[str]:
    return [f"{warning.connector}:{warning.code} — {warning.message}" for warning in warnings]
