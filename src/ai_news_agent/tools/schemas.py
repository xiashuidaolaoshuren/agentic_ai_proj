"""Shared typed inputs and JSON-safe tool observations (Milestone 2 T1)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolObservationStatus(StrEnum):
    """Compact status discriminator for tool return envelopes."""

    OK = "ok"
    NOT_FOUND = "not_found"
    EMPTY = "empty"
    ERROR = "error"


class ToolObservation(BaseModel):
    """LLM-facing envelope for any tool return value."""

    model_config = ConfigDict(extra="ignore")

    status: ToolObservationStatus
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _summary_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be empty")
        return value


class SearchQueryInput(BaseModel):
    """Shared connector search arguments for Milestone 2 source tools."""

    model_config = ConfigDict(extra="ignore")

    query: str
    max_results: int = Field(default=5, ge=1)

    @field_validator("query")
    @classmethod
    def _query_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be empty")
        return value


class RankOrSourceArgs(BaseModel):
    """LLM-facing args for rank/source_id follow-up tools."""

    model_config = ConfigDict(extra="ignore")

    rank: int | None = Field(default=None, ge=1)
    source_id: str | None = None


class SearchArgs(BaseModel):
    """LLM-facing args for connector search tools."""

    model_config = ConfigDict(extra="ignore")

    query: str
    max_results: int = Field(default=5, ge=1)
    timeframe: str | None = None


def encode_tool_value(value: Any) -> Any:
    """Return a JSON-safe value using Pydantic JSON-mode dumps where applicable."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: encode_tool_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_tool_value(v) for v in value]
    raise TypeError(f"Unsupported type for JSON-like encoding: {type(value)!r}")


def tool_observation_to_dict(observation: ToolObservation) -> dict[str, Any]:
    return observation.model_dump(mode="json")
