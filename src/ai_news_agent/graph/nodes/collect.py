"""Collection node factory for digest workflow (T10b)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from ai_news_agent.connectors.base import ConnectorResult, SourceConnector
from ai_news_agent.graph.state import DigestGraphState, WorkflowError
from ai_news_agent.sources import resolve_connector_names


def make_collect_sources_node(connectors: Sequence[SourceConnector]):
    async def collect_sources_node(state: DigestGraphState) -> dict[str, object]:
        request = state.get("connector_request")
        if request is None:
            return {
                "errors": [
                    WorkflowError(
                        stage="collect", message="missing ConnectorRequest in state"
                    )
                ]
            }

        digest_request = state.get("request")
        if digest_request is not None:
            allowed_names = resolve_connector_names(digest_request.connector_names)
        else:
            allowed_names = resolve_connector_names(None)
        allowed = set(allowed_names)
        selected = [c for c in connectors if c.name() in allowed]
        if not selected:
            return {
                "errors": [
                    WorkflowError(
                        stage="collect",
                        message="no matching connectors",
                        detail=", ".join(allowed_names),
                    )
                ]
            }

        results = await asyncio.gather(
            *[c.collect(request) for c in selected], return_exceptions=True
        )
        items = []
        warnings = []
        errors = []
        for connector, result in zip(selected, results, strict=True):
            if isinstance(result, ConnectorResult):
                items.extend(result.items)
                warnings.extend(result.warnings)
                continue
            if isinstance(result, Exception):
                errors.append(
                    WorkflowError(
                        stage="collect",
                        message=f"{connector.name()} raised {type(result).__name__}",
                        detail=str(result),
                    )
                )
        out: dict[str, object] = {}
        if items:
            out["collected_items"] = items
        if warnings:
            out["warnings"] = warnings
        if errors:
            out["errors"] = errors
        return out

    return collect_sources_node
