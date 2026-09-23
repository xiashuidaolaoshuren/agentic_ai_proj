"""SQLite repository for sessions and ordered messages (Milestone 8A.1 T3)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ai_news_agent.models import utcnow


class SessionStore:
    """Session and message SQL only."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _encode_connector_names(self, connector_names: list[str] | None) -> str | None:
        if connector_names is None:
            return None
        if not connector_names:
            raise ValueError("connector_names must be non-empty when provided")
        return json.dumps(connector_names)

    def create_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        connector_names: list[str] | None = None,
        items_per_source: int | None = None,
    ) -> None:
        now = utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                  id, title, connector_names, items_per_source, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    title,
                    self._encode_connector_names(connector_names),
                    items_per_source,
                    now,
                    now,
                ),
            )

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()

    def list_sessions(self) -> list[sqlite3.Row]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return list(rows)

    def rename_session(self, session_id: str, title: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET title = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, utcnow().isoformat(), session_id),
            )

    def update_preferences(
        self,
        session_id: str,
        *,
        connector_names: list[str] | None,
        items_per_source: int | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE sessions
                SET connector_names = ?, items_per_source = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    self._encode_connector_names(connector_names),
                    items_per_source,
                    utcnow().isoformat(),
                    session_id,
                ),
            )

    def insert_message(self, session_id: str, *, role: str, content: str) -> int:
        now = utcnow().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS max_sequence
                FROM session_messages
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            sequence = int(row["max_sequence"]) + 1
            cur = conn.execute(
                """
                INSERT INTO session_messages (
                  session_id, sequence, role, content, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, sequence, role, content, now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            return int(cur.lastrowid)

    def list_messages(self, session_id: str) -> list[sqlite3.Row]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM session_messages
                WHERE session_id = ?
                ORDER BY sequence ASC
                """,
                (session_id,),
            ).fetchall()
        return list(rows)

    def delete_session(self, session_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
