"""SQLite persistence for digest runs, items, rankings, and digests (Task 4)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.history import HISTORY_CANDIDATE_CAP
from ai_news_agent.models import (
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
    utcnow,
)


SCHEMA_VERSION = "2"


@dataclass
class FollowupContext:
    """Snapshot for follow-up chat over the latest persisted digest run."""

    run_id: int | None
    digest: Digest | None
    news_items: list[NewsItem]
    ranked_items: list[RankedItem]
    warnings: list[ConnectorWarning]


class DigestStore:
    """Hybrid SQLite store: normalized columns plus JSON snapshots."""

    def __init__(self, db_path: str | Path, *, conn: sqlite3.Connection | None = None) -> None:
        self.db_path = Path(db_path)
        self._bound_conn = conn

    def _v1_backup_path(self) -> Path:
        return self.db_path.with_name(f"{self.db_path.name}.v1.bak")

    def _ensure_v1_backup(self) -> None:
        backup_path = self._v1_backup_path()
        if backup_path.exists():
            return
        source = sqlite3.connect(self.db_path)
        try:
            destination = sqlite3.connect(backup_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

    def _restore_v1_backup(self) -> None:
        backup_path = self._v1_backup_path()
        if not backup_path.exists():
            return
        source = sqlite3.connect(backup_path)
        try:
            destination = sqlite3.connect(self.db_path)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

    def _apply_v2_ddl(self, conn: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY NOT NULL,
              title TEXT,
              connector_names TEXT,
              items_per_source INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS session_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
              sequence INTEGER NOT NULL,
              role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
              content TEXT NOT NULL,
              run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
              created_at TEXT NOT NULL,
              UNIQUE (session_id, sequence)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS session_requests (
              id TEXT NOT NULL,
              session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
              status TEXT NOT NULL CHECK (
                status IN ('active', 'succeeded', 'failed', 'cancelled', 'interrupted')
              ),
              user_message_id INTEGER NOT NULL REFERENCES session_messages(id) ON DELETE RESTRICT,
              assistant_message_id INTEGER REFERENCES session_messages(id) ON DELETE RESTRICT,
              run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
              correlation_id TEXT NOT NULL,
              error_code TEXT,
              error_message TEXT,
              started_at TEXT NOT NULL,
              completed_at TEXT,
              PRIMARY KEY (session_id, id)
            )
            """,
            """
            ALTER TABLE runs ADD COLUMN session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_runs_session_id_id ON runs(session_id, id DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_session_messages_session_sequence
              ON session_messages(session_id, sequence)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_session_requests_session_started
              ON session_requests(session_id, started_at DESC)
            """,
        )
        for statement in statements:
            conn.execute(statement)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        if self._bound_conn is not None:
            yield self._bound_conn
            return

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

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                  key TEXT PRIMARY KEY NOT NULL,
                  value TEXT NOT NULL
                );
                """
            )
            cur = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'")
            row = cur.fetchone()
            stored_version = row["value"] if row is not None else None

        if stored_version == SCHEMA_VERSION:
            return

        if stored_version is not None and stored_version != "1":
            raise RuntimeError(
                f"Unsupported DB schema version {stored_version!r}; expected {SCHEMA_VERSION!r}"
            )

        if stored_version == "1":
            self._ensure_v1_backup()
            try:
                with self._conn() as conn:
                    self._apply_v2_ddl(conn)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                        (SCHEMA_VERSION,),
                    )
            except Exception:
                self._restore_v1_backup()
                raise
            return

        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY NOT NULL,
                  title TEXT,
                  connector_names TEXT,
                  items_per_source INTEGER,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  requested_at TEXT NOT NULL,
                  timeframe TEXT,
                  request_topics_json TEXT NOT NULL,
                  connector_names_json TEXT NOT NULL,
                  session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS news_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                  source TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  url TEXT NOT NULL,
                  title TEXT NOT NULL,
                  published_at TEXT,
                  collected_at TEXT NOT NULL,
                  author TEXT,
                  stars_or_views INTEGER,
                  language TEXT,
                  metadata_completeness REAL NOT NULL,
                  raw_snippet TEXT,
                  tags_json TEXT NOT NULL,
                  topic_matches_json TEXT NOT NULL,
                  content_confidence TEXT,
                  raw_payload_json TEXT NOT NULL,
                  UNIQUE (run_id, source, source_id)
                );

                CREATE TABLE IF NOT EXISTS ranked_items (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                  news_item_id INTEGER NOT NULL REFERENCES news_items(id) ON DELETE CASCADE,
                  score_total REAL NOT NULL,
                  selected INTEGER NOT NULL,
                  selection_reason TEXT NOT NULL,
                  score_breakdown_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS digests (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                  generated_at TEXT NOT NULL,
                  topics_json TEXT NOT NULL,
                  timeframe TEXT
                );

                CREATE TABLE IF NOT EXISTS digest_entries (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  digest_id INTEGER NOT NULL REFERENCES digests(id) ON DELETE CASCADE,
                  source_kind TEXT NOT NULL,
                  source_id TEXT NOT NULL,
                  title TEXT NOT NULL,
                  source_name TEXT NOT NULL,
                  source_url TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  why_it_matters TEXT NOT NULL,
                  background_knowledge TEXT NOT NULL,
                  follow_up_action TEXT NOT NULL,
                  confidence_caveat TEXT
                );

                CREATE TABLE IF NOT EXISTS connector_warnings (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                  connector TEXT NOT NULL,
                  code TEXT NOT NULL,
                  message TEXT NOT NULL,
                  detail TEXT
                );

                CREATE TABLE IF NOT EXISTS session_messages (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  sequence INTEGER NOT NULL,
                  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                  content TEXT NOT NULL,
                  run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
                  created_at TEXT NOT NULL,
                  UNIQUE (session_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS session_requests (
                  id TEXT NOT NULL,
                  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  status TEXT NOT NULL CHECK (
                    status IN ('active', 'succeeded', 'failed', 'cancelled', 'interrupted')
                  ),
                  user_message_id INTEGER NOT NULL REFERENCES session_messages(id) ON DELETE RESTRICT,
                  assistant_message_id INTEGER REFERENCES session_messages(id) ON DELETE RESTRICT,
                  run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
                  correlation_id TEXT NOT NULL,
                  error_code TEXT,
                  error_message TEXT,
                  started_at TEXT NOT NULL,
                  completed_at TEXT,
                  PRIMARY KEY (session_id, id)
                );

                CREATE INDEX IF NOT EXISTS idx_news_items_run ON news_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_ranked_run ON ranked_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_digest_run ON digests(run_id);
                CREATE INDEX IF NOT EXISTS idx_warnings_run ON connector_warnings(run_id);
                CREATE INDEX IF NOT EXISTS idx_runs_session_id_id ON runs(session_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_session_messages_session_sequence
                  ON session_messages(session_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_session_requests_session_started
                  ON session_requests(session_id, started_at DESC);
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )

    def save_run(
        self,
        *,
        requested_at: datetime | None,
        timeframe: str | None,
        topics: list[str],
        connector_names: list[str],
        session_id: str | None = None,
    ) -> int:
        ts = requested_at if requested_at is not None else utcnow()
        payload = (
            ts.isoformat(),
            timeframe,
            json.dumps(topics),
            json.dumps(connector_names),
            session_id,
        )
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (
                  requested_at, timeframe, request_topics_json, connector_names_json, session_id
                )
                VALUES (?,?,?,?,?)
                """,
                payload,
            )
            return int(cur.lastrowid)

    def save_connector_result(self, run_id: int, result: ConnectorResult) -> None:
        self.save_connector_warnings(run_id, result.warnings)
        for item in result.items:
            self._insert_news_item(run_id, item)

    def save_connector_warnings(self, run_id: int, warnings: list[ConnectorWarning]) -> None:
        with self._conn() as conn:
            for w in warnings:
                conn.execute(
                    """
                    INSERT INTO connector_warnings (run_id, connector, code, message, detail)
                    VALUES (?,?,?,?,?)
                    """,
                    (run_id, w.connector, w.code, w.message, w.detail),
                )

    def upsert_news_item(self, run_id: int, item: NewsItem) -> None:
        """Insert or replace a normalized news row for a run."""
        self._insert_news_item(run_id, item)

    def _insert_news_item(self, run_id: int, item: NewsItem) -> None:
        payload_json = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO news_items (
                  run_id, source, source_id, url, title, published_at, collected_at,
                  author, stars_or_views, language, metadata_completeness, raw_snippet,
                  tags_json, topic_matches_json, content_confidence, raw_payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id, source, source_id) DO UPDATE SET
                  url=excluded.url,
                  title=excluded.title,
                  published_at=excluded.published_at,
                  collected_at=excluded.collected_at,
                  author=excluded.author,
                  stars_or_views=excluded.stars_or_views,
                  language=excluded.language,
                  metadata_completeness=excluded.metadata_completeness,
                  raw_snippet=excluded.raw_snippet,
                  tags_json=excluded.tags_json,
                  topic_matches_json=excluded.topic_matches_json,
                  content_confidence=excluded.content_confidence,
                  raw_payload_json=excluded.raw_payload_json
                """,
                (
                    run_id,
                    item.source.value,
                    item.source_id,
                    item.url,
                    item.title,
                    item.published_at.isoformat() if item.published_at else None,
                    item.collected_at.isoformat(),
                    item.author,
                    item.stars_or_views,
                    item.language,
                    item.metadata_completeness,
                    item.raw_snippet,
                    json.dumps(item.tags),
                    json.dumps(item.topic_matches),
                    item.content_confidence.value if item.content_confidence else None,
                    payload_json,
                ),
            )

    def save_ranked_items(self, run_id: int, ranked: list[RankedItem]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM ranked_items WHERE run_id = ?", (run_id,))
            for ri in ranked:
                cur = conn.execute(
                    """
                    SELECT id FROM news_items
                    WHERE run_id = ? AND source = ? AND source_id = ?
                    """,
                    (run_id, ri.item.source.value, ri.item.source_id),
                )
                row = cur.fetchone()
                if row is None:
                    raise ValueError(
                        f"No news_item for run {run_id} source={ri.item.source!r} id={ri.item.source_id!r}"
                    )
                news_item_id = int(row["id"])
                conn.execute(
                    """
                    INSERT INTO ranked_items (
                      run_id, news_item_id, score_total, selected, selection_reason, score_breakdown_json
                    ) VALUES (?,?,?,?,?,?)
                    """,
                    (
                        run_id,
                        news_item_id,
                        ri.score_total,
                        1 if ri.selected else 0,
                        ri.selection_reason,
                        json.dumps(ri.score_breakdown),
                    ),
                )

    def save_digest(self, run_id: int, digest: Digest) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO digests (run_id, generated_at, topics_json, timeframe)
                VALUES (?,?,?,?)
                """,
                (
                    run_id,
                    digest.generated_at.isoformat(),
                    json.dumps(digest.topics),
                    digest.timeframe,
                ),
            )
            digest_id = int(cur.lastrowid)
            for entry in digest.entries:
                conn.execute(
                    """
                    INSERT INTO digest_entries (
                      digest_id, source_kind, source_id, title, source_name, source_url,
                      summary, why_it_matters, background_knowledge, follow_up_action, confidence_caveat
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        digest_id,
                        entry.source_kind.value,
                        entry.source_id,
                        entry.title,
                        entry.source_name,
                        entry.source_url,
                        entry.summary,
                        entry.why_it_matters,
                        entry.background_knowledge,
                        entry.follow_up_action.value,
                        entry.confidence_caveat,
                    ),
                )
            return digest_id

    def save_digest_bundle(
        self,
        *,
        requested_at: datetime | None,
        timeframe: str | None,
        topics: list[str],
        connector_names: list[str],
        items: list[NewsItem],
        warnings: list[ConnectorWarning],
        ranked: list[RankedItem],
        digest: Digest,
        session_id: str | None = None,
    ) -> int:
        """Persist a complete digest bundle in one SQLite transaction."""
        with self._conn() as conn:
            bound = DigestStore(self.db_path, conn=conn)
            run_id = bound.save_run(
                requested_at=requested_at,
                timeframe=timeframe,
                topics=topics,
                connector_names=connector_names,
                session_id=session_id,
            )
            bound.save_connector_result(
                run_id,
                ConnectorResult(
                    items=items,
                    warnings=warnings,
                    raw_count=len(items),
                ),
            )
            bound.save_ranked_items(run_id, ranked)
            bound.save_digest(run_id, digest)
            if session_id is not None:
                SessionStore(self.db_path, conn=conn).link_active_request_run(
                    session_id,
                    run_id,
                )
            return run_id

    def get_latest_digest(self) -> Digest | None:
        row = self._latest_digest_row()
        if row is None:
            return None
        return self._digest_from_row(row)

    def _latest_digest_row(self) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute(
                """
                SELECT d.*
                FROM digests d
                JOIN runs r ON r.id = d.run_id
                WHERE r.session_id IS NULL
                ORDER BY d.id DESC
                LIMIT 1
                """
            ).fetchone()

    def _digest_from_row(self, row: sqlite3.Row) -> Digest:
        digest_id = int(row["id"])
        with self._conn() as conn:
            erows = conn.execute(
                "SELECT * FROM digest_entries WHERE digest_id = ? ORDER BY id ASC",
                (digest_id,),
            ).fetchall()
        entries: list[DigestEntry] = []
        for er in erows:
            entries.append(
                DigestEntry(
                    source_kind=SourceKind(er["source_kind"]),
                    source_id=er["source_id"],
                    title=er["title"],
                    source_name=er["source_name"],
                    source_url=er["source_url"],
                    summary=er["summary"],
                    why_it_matters=er["why_it_matters"],
                    background_knowledge=er["background_knowledge"],
                    follow_up_action=FollowUpAction(er["follow_up_action"]),
                    confidence_caveat=er["confidence_caveat"],
                )
            )
        return Digest(
            generated_at=datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00")),
            entries=entries,
            topics=json.loads(row["topics_json"]),
            timeframe=row["timeframe"],
        )

    def get_latest_followup_context(self) -> FollowupContext:
        drow = self._latest_digest_row()
        if drow is not None:
            run_id = int(drow["run_id"])
            digest = self._digest_from_row(drow)
        else:
            digest = None
            run_id = self._latest_run_id()

        if run_id is None:
            return FollowupContext(
                run_id=None,
                digest=None,
                news_items=[],
                ranked_items=[],
                warnings=[],
            )

        news_items = self._load_news_items(run_id)
        ranked_items = self._load_ranked_items(run_id)
        warnings = self._load_warnings(run_id)
        return FollowupContext(
            run_id=run_id,
            digest=digest,
            news_items=news_items,
            ranked_items=ranked_items,
            warnings=warnings,
        )

    def _latest_run_id(self) -> int | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM runs
                WHERE session_id IS NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return int(row["id"]) if row else None

    def _load_news_items(self, run_id: int) -> list[NewsItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news_items WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        out: list[NewsItem] = []
        for r in rows:
            out.append(NewsItem.model_validate(json.loads(r["raw_payload_json"])))
        return out

    def _load_warnings(self, run_id: int) -> list[ConnectorWarning]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM connector_warnings WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        return [
            ConnectorWarning(
                connector=r["connector"],
                code=r["code"],
                message=r["message"],
                detail=r["detail"],
            )
            for r in rows
        ]

    def _load_ranked_items(self, run_id: int) -> list[RankedItem]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT r.*, n.raw_payload_json AS item_json
                FROM ranked_items r
                JOIN news_items n ON n.id = r.news_item_id
                WHERE r.run_id = ?
                ORDER BY r.id ASC
                """,
                (run_id,),
            ).fetchall()
        out: list[RankedItem] = []
        for r in rows:
            item = NewsItem.model_validate(json.loads(r["item_json"]))
            ri = RankedItem(
                item=item,
                score_total=float(r["score_total"]),
                score_breakdown=json.loads(r["score_breakdown_json"]),
                selected=bool(r["selected"]),
                selection_reason=r["selection_reason"],
            )
            out.append(ri)
        return out

    def _parse_stored_datetime(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _historical_row_to_candidate(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "title": row["title"],
            "summary": row["summary"],
            "why_it_matters": row["why_it_matters"],
            "background_knowledge": row["background_knowledge"],
            "digest_topics": json.loads(row["topics_json"]),
            "generated_at": self._parse_stored_datetime(row["generated_at"]),
            "digest_id": int(row["digest_id"]),
            "rank": int(row["display_rank"]),
            "run_id": int(row["run_id"]),
            "entry_id": int(row["id"]),
            "source_kind": SourceKind(row["source_kind"]),
            "source_id": row["source_id"],
            "source_name": row["source_name"],
            "source_url": row["source_url"],
        }

    def _utc_day_start(self, day: date) -> datetime:
        return datetime(day.year, day.month, day.day, tzinfo=UTC)

    def _utc_day_end_exclusive(self, day: date) -> datetime:
        return self._utc_day_start(day + timedelta(days=1))

    def list_historical_digest_entries(
        self,
        *,
        sources: list[str] | None = None,
        since: date | None = None,
        until: date | None = None,
        cap: int = HISTORY_CANDIDATE_CAP,
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._conn() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM digest_entries").fetchone()["c"]
            if count == 0:
                return [], False

            where_clauses: list[str] = []
            params: list[Any] = []
            if sources:
                placeholders = ",".join("?" for _ in sources)
                where_clauses.append(f"re.source_kind IN ({placeholders})")
                params.extend(sources)
            if since is not None:
                where_clauses.append("re.generated_at >= ?")
                params.append(self._utc_day_start(since).isoformat())
            if until is not None:
                where_clauses.append("re.generated_at < ?")
                params.append(self._utc_day_end_exclusive(until).isoformat())
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

            query = f"""
                WITH ranked_entries AS (
                  SELECT
                    de.*,
                    d.run_id,
                    d.generated_at,
                    d.topics_json,
                    d.id AS digest_id,
                    ROW_NUMBER() OVER (
                      PARTITION BY de.digest_id ORDER BY de.id ASC
                    ) AS display_rank
                  FROM digest_entries de
                  JOIN digests d ON d.id = de.digest_id
                )
                SELECT * FROM ranked_entries re
                {where_sql}
                ORDER BY re.generated_at DESC, re.digest_id DESC, re.display_rank ASC
                LIMIT ?
            """
            params.append(cap + 1)
            rows = conn.execute(query, params).fetchall()

        truncated = len(rows) > cap
        if truncated:
            rows = rows[:cap]
        return [self._historical_row_to_candidate(row) for row in rows], truncated

    def get_followup_context_for_digest(self, digest_id: int) -> FollowupContext | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM digests WHERE id = ?", (digest_id,)).fetchone()
        if row is None:
            return None
        run_id = int(row["run_id"])
        digest = self._digest_from_row(row)
        return FollowupContext(
            run_id=run_id,
            digest=digest,
            news_items=self._load_news_items(run_id),
            ranked_items=self._load_ranked_items(run_id),
            warnings=self._load_warnings(run_id),
        )

    def get_followup_context_for_session(self, session_id: str) -> FollowupContext:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT d.*
                FROM session_requests sr
                JOIN digests d ON d.run_id = sr.run_id
                WHERE sr.session_id = ?
                  AND sr.status = 'succeeded'
                  AND sr.run_id IS NOT NULL
                ORDER BY sr.started_at DESC, sr.id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            return FollowupContext(
                run_id=None,
                digest=None,
                news_items=[],
                ranked_items=[],
                warnings=[],
            )

        run_id = int(row["run_id"])
        digest = self._digest_from_row(row)
        return FollowupContext(
            run_id=run_id,
            digest=digest,
            news_items=self._load_news_items(run_id),
            ranked_items=self._load_ranked_items(run_id),
            warnings=self._load_warnings(run_id),
        )
