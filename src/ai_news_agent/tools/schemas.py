"""Shared typed inputs and JSON-safe tool observations (Milestone 2 T1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ai_news_agent.models import _encode_value


class ToolObservationStatus(StrEnum):
    """Compact status discriminator for tool return envelopes."""

    OK = "ok"
    NOT_FOUND = "not_found"
    EMPTY = "empty"
    ERROR = "error"


@dataclass
class ToolObservation:
    """LLM-facing envelope for any tool return value."""

    status: ToolObservationStatus
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.status, str) and not isinstance(self.status, ToolObservationStatus):
            try:
                self.status = ToolObservationStatus(self.status)
            except ValueError as exc:
                raise ValueError(f"Invalid status: {self.status!r}") from exc
        if not self.summary.strip():
            raise ValueError("summary must not be empty")


@dataclass
class SearchQueryInput:
    """Shared connector search arguments for Milestone 2 source tools."""

    query: str
    max_results: int = 5

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if self.max_results < 1:
            raise ValueError("max_results must be at least 1")


def encode_tool_value(value: Any) -> Any:
    """Return a JSON-safe value using the same rules as domain model encoding."""
    return _encode_value(value)


def tool_observation_to_dict(observation: ToolObservation) -> dict[str, Any]:
    return encode_tool_value(observation)  # type: ignore[return-value]
