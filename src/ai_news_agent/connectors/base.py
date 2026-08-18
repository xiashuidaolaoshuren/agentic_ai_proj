"""Connector protocol and shared request/result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ai_news_agent.models import ConnectorWarning, NewsItem


@dataclass
class ConnectorRequest:
    """Parameters passed into a connector for one collection pass."""

    topics: list[str]
    timeframe: str | None = None
    max_items: int = 20
    language_hint: str | None = None
    #: Legacy Bilibili fields (prefer bilibili_*); kept for backward compatibility.
    target_channels: list[str] = field(default_factory=list)
    manual_urls: list[str] = field(default_factory=list)
    #: Bilibili MID (numeric) or uploader handle (resolved via user search).
    bilibili_target_channels: list[str] = field(default_factory=list)
    #: Bilibili video page URLs or BV ids.
    bilibili_manual_urls: list[str] = field(default_factory=list)
    #: GitHub owner/org login for recent repos list.
    github_target_channels: list[str] = field(default_factory=list)
    #: GitHub repository page URLs (``owner/repo``).
    github_manual_urls: list[str] = field(default_factory=list)
    #: Juya website (``daily.juya.uk``) target URLs; routed to the Juya connector.
    juya_manual_urls: list[str] = field(default_factory=list)
    #: Hugging Face discovery mode: ``global`` (default when None) or ``filtered``.
    huggingface_discovery_mode: str | None = None
    #: Topic/search term for Hugging Face filtered trending.
    huggingface_search: str | None = None
    #: Pipeline-task filter for Hugging Face filtered trending.
    huggingface_pipeline_tag: str | None = None


@dataclass
class ConnectorResult:
    """Normalized connector output plus diagnostics."""

    items: list[NewsItem] = field(default_factory=list)
    warnings: list[ConnectorWarning] = field(default_factory=list)
    raw_count: int = 0


@runtime_checkable
class SourceConnector(Protocol):
    """Async source connector: implementations live in per-source modules (T5/T6)."""

    def name(self) -> str:
        """Stable connector identifier for logging and storage."""

    async def collect(self, request: ConnectorRequest) -> ConnectorResult:
        """Fetch and normalize items for the given request."""
