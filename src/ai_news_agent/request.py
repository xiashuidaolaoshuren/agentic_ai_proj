"""User-facing digest request for workflow, CLI, and UI (Task T10a).

Distinct from :class:`~ai_news_agent.connectors.base.ConnectorRequest`, which is
connector-scoped. Mapping between the two happens in the collection node (T10b).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai_news_agent.topics import DEFAULT_TOPICS


def _empty_str_list() -> list[str]:
    return []


@dataclass(frozen=True)
class DigestRequest:
    """Parameters for one digest run as received from the user or chat UI."""

    topics: list[str] | None = None
    timeframe: str | None = None
    max_items_per_source: int = 20
    top_n: int = 5
    language_hint: str | None = None
    #: Legacy Bilibili selectors (prefer bilibili_* fields).
    target_channels: list[str] = field(default_factory=_empty_str_list)
    manual_urls: list[str] = field(default_factory=_empty_str_list)
    bilibili_target_channels: list[str] = field(default_factory=_empty_str_list)
    bilibili_manual_urls: list[str] = field(default_factory=_empty_str_list)
    github_target_channels: list[str] = field(default_factory=_empty_str_list)
    github_manual_urls: list[str] = field(default_factory=_empty_str_list)
    #: Juya website (``daily.juya.uk``) target URLs; routed to the Juya connector.
    juya_manual_urls: list[str] = field(default_factory=_empty_str_list)
    connector_names: list[str] | None = None
    #: ``editorial`` selects newsletter-style rendering; ``None`` keeps the default bulletin.
    output_style: str | None = None
    #: BCP-47 language tag for summarization/rendering (e.g. ``zh-CN``).
    output_language: str | None = None
    #: Resolved primary source name (first of ``connector_names``); recorded for
    #: downstream ranking/rendering (T5). Defaults to ``None`` until resolved.
    primary_source: str | None = None
    huggingface_discovery_mode: str | None = None
    huggingface_search: str | None = None
    huggingface_pipeline_tag: str | None = None

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

    def has_explicit_selectors(self) -> bool:
        """True when URL/channel targets were provided (not topic-only)."""
        return bool(
            self.target_channels
            or self.manual_urls
            or self.bilibili_target_channels
            or self.bilibili_manual_urls
            or self.github_target_channels
            or self.github_manual_urls
            or self.juya_manual_urls
        )


def primary_source_from_names(names: list[str] | None) -> str | None:
    """Return the first connector name as primary intent, or ``None`` when unset."""
    if not names:
        return None
    return names[0]


def huggingface_fields_from_structured_sources(
    *,
    connector_names: list[str] | None,
    topics: list[str] | None,
    topics_explicit: bool,
    huggingface_discovery_mode: str | None = None,
    huggingface_search: str | None = None,
    huggingface_pipeline_tag: str | None = None,
) -> dict[str, str]:
    """Map explicit structured topics onto Hugging Face filtered discovery.

    Returns extra ``DigestRequest`` kwargs. Does nothing when Hugging Face is
    not selected, topics were omitted, topics are empty, or any Hugging Face
    discovery field is already set.
    """
    if not topics_explicit:
        return {}
    if (
        huggingface_discovery_mode is not None
        or huggingface_search is not None
        or huggingface_pipeline_tag is not None
    ):
        return {}
    if not connector_names or "huggingface" not in connector_names:
        return {}
    first = next(
        (str(topic).strip() for topic in (topics or []) if str(topic).strip()),
        None,
    )
    if first is None:
        return {}
    return {
        "huggingface_discovery_mode": "filtered",
        "huggingface_search": first,
    }
