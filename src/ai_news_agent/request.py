"""User-facing digest request for workflow, CLI, and UI (Task T10a).

Distinct from :class:`~ai_news_agent.connectors.base.ConnectorRequest`, which is
connector-scoped. Mapping between the two happens in the collection node (T10b).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_news_agent.topics import DEFAULT_TOPICS


def _default_target_channels() -> list[str]:
    return []


def _default_manual_urls() -> list[str]:
    return []


@dataclass(frozen=True)
class DigestRequest:
    """Parameters for one digest run as received from the user or chat UI."""

    topics: list[str] | None = None
    timeframe: str | None = None
    max_items_per_source: int = 20
    top_n: int = 5
    language_hint: str | None = None
    target_channels: list[str] = field(default_factory=_default_target_channels)
    manual_urls: list[str] = field(default_factory=_default_manual_urls)
    connector_names: list[str] | None = None

    def __post_init__(self) -> None:
        if self.max_items_per_source < 1:
            raise ValueError("max_items_per_source must be >= 1")
        if self.top_n < 0:
            raise ValueError("top_n must be non-negative")

        if self.topics is None:
            norm_topics = list(DEFAULT_TOPICS)
        else:
            norm_topics = [str(t).strip() for t in self.topics if str(t).strip()]

        object.__setattr__(self, "topics", norm_topics)

