"""Connection-scoped SQLite Unit of Work for cross-repository writes (8A.1 T6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import TracebackType

from ai_news_agent.repositories.digest_store import DigestStore
from ai_news_agent.repositories.session_store import SessionStore


class SqliteUnitOfWork:
    """One SQLite connection and transaction for digest plus session writes."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._digest_store: DigestStore | None = None
        self._session_store: SessionStore | None = None

    def __enter__(self) -> SqliteUnitOfWork:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        self._conn = conn
        self._digest_store = DigestStore(self.db_path, conn=conn)
        self._session_store = SessionStore(self.db_path, conn=conn)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._conn is None:
            return
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
            self._conn = None
            self._digest_store = None
            self._session_store = None

    @property
    def digest_store(self) -> DigestStore:
        if self._digest_store is None:
            raise RuntimeError("SqliteUnitOfWork is not active")
        return self._digest_store

    @property
    def session_store(self) -> SessionStore:
        if self._session_store is None:
            raise RuntimeError("SqliteUnitOfWork is not active")
        return self._session_store


__all__ = ["SqliteUnitOfWork"]
