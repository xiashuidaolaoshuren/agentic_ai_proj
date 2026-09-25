"""Session use cases: CRUD, preferences, titles, and delete rules (8A.1 T7)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime

from ai_news_agent.digest_request_builder import resolve_digest_request
from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.request import DigestRequest
from ai_news_agent.services.session_records import (
    MessageRecord,
    SessionRecord,
    initial_session_title,
)


class SessionBusyError(Exception):
    """A session-scoped operation was rejected because a request is active."""


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session_record(row: sqlite3.Row) -> SessionRecord:
    raw_names = row["connector_names"]
    return SessionRecord(
        id=row["id"],
        title=row["title"],
        connector_names=json.loads(raw_names) if raw_names is not None else None,
        items_per_source=row["items_per_source"],
        created_at=_parse_ts(row["created_at"]),
        updated_at=_parse_ts(row["updated_at"]),
    )


def _message_record(row: sqlite3.Row) -> MessageRecord:
    return MessageRecord(
        id=int(row["id"]),
        session_id=row["session_id"],
        sequence=int(row["sequence"]),
        role=row["role"],
        content=row["content"],
        run_id=row["run_id"],
        created_at=_parse_ts(row["created_at"]),
    )


class SessionService:
    """Session lifecycle use cases over :class:`SessionStore`."""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def create_session(self) -> SessionRecord:
        session_id = str(uuid.uuid4())
        self._store.create_session(session_id)
        row = self._store.get_session(session_id)
        assert row is not None
        return _session_record(row)

    def get_session(self, session_id: str) -> SessionRecord | None:
        row = self._store.get_session(session_id)
        return _session_record(row) if row is not None else None

    def list_sessions(self) -> list[SessionRecord]:
        return [_session_record(row) for row in self._store.list_sessions()]

    def rename_session(self, session_id: str, title: str) -> None:
        self._store.rename_session(session_id, title)

    def update_preferences(
        self,
        session_id: str,
        *,
        connector_names: list[str] | None,
        items_per_source: int | None,
    ) -> None:
        self._store.update_preferences(
            session_id,
            connector_names=connector_names,
            items_per_source=items_per_source,
        )

    def record_user_message(self, session_id: str, *, content: str) -> MessageRecord:
        self._store.insert_message(session_id, role="user", content=content)
        row = self._store.get_session(session_id)
        if row is not None and row["title"] is None:
            title = initial_session_title(content)
            if title is not None:
                self._store.rename_session(session_id, title)
        messages = self._store.list_messages(session_id)
        return _message_record(messages[-1])

    def build_request(self, session_id: str, message: str) -> DigestRequest:
        """Compose a request where session preferences act only as defaults.

        Explicit message selectors win for this one request; the stored
        preference is never mutated.
        """
        row = self._store.get_session(session_id)
        if row is None:
            raise KeyError(f"session not found: {session_id}")
        raw_names = row["connector_names"]
        stored_names = json.loads(raw_names) if raw_names is not None else None
        req = resolve_digest_request(message, session_connector_names=stored_names)
        items_per_source = row["items_per_source"]
        if items_per_source is not None:
            req = replace(req, max_items_per_source=int(items_per_source))
        return req

    def delete_session(self, session_id: str) -> None:
        """Delete an inactive session; reject deletion while a request is active."""
        active = [
            row
            for row in self._store.list_requests(session_id)
            if row["status"] == "active"
        ]
        if active:
            raise SessionBusyError(f"session {session_id} has an active request")
        self._store.delete_session(session_id)


__all__ = ["SessionBusyError", "SessionService"]