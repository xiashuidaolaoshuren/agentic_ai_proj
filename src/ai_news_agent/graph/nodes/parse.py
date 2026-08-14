"""Request parsing node for digest workflow (T10b)."""

from __future__ import annotations

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.graph.state import DigestGraphState
from ai_news_agent.graph.state import WorkflowError


def _merged_bilibili_channels(req) -> list[str]:  # noqa: ANN001
    seen: set[str] = set()
    out: list[str] = []
    for ch in list(req.bilibili_target_channels) + list(req.target_channels):
        s = str(ch).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _merged_bilibili_urls(req) -> list[str]:  # noqa: ANN001
    seen: set[str] = set()
    out: list[str] = []
    for url in list(req.bilibili_manual_urls) + list(req.manual_urls):
        s = str(url).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


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
            target_channels=_merged_bilibili_channels(req),
            manual_urls=_merged_bilibili_urls(req),
            bilibili_target_channels=_merged_bilibili_channels(req),
            bilibili_manual_urls=_merged_bilibili_urls(req),
            github_target_channels=list(req.github_target_channels),
            github_manual_urls=list(req.github_manual_urls),
            juya_manual_urls=list(req.juya_manual_urls),
        )
    }
