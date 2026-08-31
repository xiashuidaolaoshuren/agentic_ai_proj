"""Gradio/CLI history command grammar and search chrome (Milestone 7D T6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from ai_news_agent.history import (
    HistorySearchQuery,
    HistorySearchResult,
    format_historical_item_ref,
    parse_historical_item_ref,
    validate_history_search_query,
)
from ai_news_agent.sources import parse_sources_csv

HISTORY_NOT_FOUND = "not found"

_SEARCH_CLAUSE_RE = re.compile(r"\b(for|from|on|since|until)\b", re.IGNORECASE)


@dataclass(frozen=True)
class HistoryChatCommand:
    action: Literal["search", "open"]
    query: HistorySearchQuery | None = None
    token: str | None = None
    error: str | None = None


def parse_history_chat_message(message: str) -> HistoryChatCommand | None:
    stripped = message.strip()
    lowered = stripped.casefold()

    if lowered == "open history" or lowered.startswith("open history "):
        remainder = stripped[len("open history") :].strip()
        try:
            parse_historical_item_ref(remainder)
        except ValueError:
            return HistoryChatCommand(action="open", error=HISTORY_NOT_FOUND)
        return HistoryChatCommand(action="open", token=remainder)

    if lowered == "search history" or lowered.startswith("search history "):
        remainder = stripped[len("search history") :].strip()
        try:
            query = _parse_search_clauses(remainder)
        except ValueError as exc:
            return HistoryChatCommand(action="search", error=str(exc))
        return HistoryChatCommand(action="search", query=query)

    return None


def format_history_search_text(result: HistorySearchResult) -> str:
    lines: list[str] = []
    for match in result.matches:
        lines.append(format_historical_item_ref(match.ref))
        lines.append(_utc_date(match.generated_at))
        lines.append(match.source_kind.value)
        lines.append(match.title)
        lines.append(match.url)
        if match.excerpt is not None:
            lines.append(match.excerpt)
    lines.extend(result.caveats)
    return "\n".join(lines)


def _utc_date(generated_at: datetime) -> str:
    aware = generated_at if generated_at.tzinfo is not None else generated_at.replace(tzinfo=UTC)
    return aware.astimezone(UTC).date().isoformat()


def _parse_search_clauses(remainder: str) -> HistorySearchQuery:
    matches = list(_SEARCH_CLAUSE_RE.finditer(remainder))
    kwargs: dict[str, Any] = {}
    for index, match in enumerate(matches):
        keyword = match.group(1).casefold()
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(remainder)
        value = remainder[value_start:value_end].strip()
        if keyword == "for":
            kwargs["text"] = value or None
        elif keyword == "from":
            sources = parse_sources_csv(value) if value else []
            kwargs["sources"] = sources or None
        elif keyword == "on":
            topics = [part.strip() for part in value.split(",") if part.strip()]
            kwargs["topics"] = topics or None
        elif keyword == "since":
            kwargs["since"] = _parse_iso_date(value)
        elif keyword == "until":
            kwargs["until"] = _parse_iso_date(value)
    return validate_history_search_query(**kwargs)


def _parse_iso_date(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()
