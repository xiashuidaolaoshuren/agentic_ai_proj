"""Source connector package."""

from ai_news_agent.connectors.base import (
    ConnectorRequest,
    ConnectorResult,
    SourceConnector,
)
from ai_news_agent.connectors.github import GitHubConnector

__all__ = [
    "ConnectorRequest",
    "ConnectorResult",
    "GitHubConnector",
    "SourceConnector",
]
