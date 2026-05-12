"""Source connector package."""

from ai_news_agent.connectors.base import (
    ConnectorRequest,
    ConnectorResult,
    SourceConnector,
)
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.connectors.bilibili import BilibiliConnector

__all__ = [
    "BilibiliConnector",
    "ConnectorRequest",
    "ConnectorResult",
    "GitHubConnector",
    "SourceConnector",
]
