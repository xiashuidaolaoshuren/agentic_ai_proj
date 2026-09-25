"""Typed session records and initial title rules (Milestone 8A.1 T7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SessionRecord:
    """Typed view of a persisted chat session."""

    id: str
    title: str | None
    connector_names: list[str] | None
    items_per_source: int | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    """Typed view of an ordered session message."""

    id: int
    session_id: str
    sequence: int
    role: str
    content: str
    run_id: int | None
    created_at: datetime


@dataclass(frozen=True)
class SessionRequestRecord:
    """Typed view of a durable session request."""

    id: str
    session_id: str
    status: str
    user_message_id: int
    assistant_message_id: int | None
    run_id: int | None
    correlation_id: str
    error_code: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


_TITLE_MAX_CHARS = 60


def initial_session_title(content: str) -> str | None:
    """Derive the one-time initial session title from a user message.

    Uses the first nonblank line, collapses whitespace runs to single spaces,
    and truncates to 60 Unicode characters. Blank content yields ``None`` so
    the title stays NULL ("New conversation" is display-only).
    """
    for line in content.splitlines():
        normalized = " ".join(line.split())
        if normalized:
            return normalized[:_TITLE_MAX_CHARS]
    return None


__all__ = [
    "MessageRecord",
    "SessionRecord",
    "SessionRequestRecord",
    "initial_session_title",
]