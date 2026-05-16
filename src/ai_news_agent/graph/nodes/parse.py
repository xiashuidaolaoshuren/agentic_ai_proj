"""Request parsing node for digest workflow (T10b)."""

from __future__ import annotations

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.graph.state import DigestGraphState
from ai_news_agent.graph.state import WorkflowError


def parse_request_node(state: DigestGraphState) -> dict[str, object]:
    req = state.get("request")
    if req is None:
        return {
            "errors": [WorkflowError(stage="parse", message="missing DigestRequest in state")]
        }
    return {
        "connector_request": ConnectorRequest(
            topics=list(req.topics or []),
            timeframe=req.timeframe,
            max_items=req.max_items_per_source,
            language_hint=req.language_hint,
            target_channels=list(req.target_channels),
            manual_urls=list(req.manual_urls),
        )
    }
