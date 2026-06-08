"""SQLite persistence for digest runs, items, rankings, and digests (Task 4)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.models import (
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
    news_item_from_dict,
    news_item_to_dict,
    utcnow,
)


SCHEMA_VERSION = "1"


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
            if row is not None and row["value"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"Unsupported DB schema version {row['value']!r}; expected {SCHEMA_VERSION!r}"
                )

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  requested_at TEXT NOT NULL,
                  timeframe TEXT,
                  request_topics_json TEXT NOT NULL,
                  connector_names_json TEXT NOT NULL
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

                CREATE INDEX IF NOT EXISTS idx_news_items_run ON news_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_ranked_run ON ranked_items(run_id);
                CREATE INDEX IF NOT EXISTS idx_digest_run ON digests(run_id);
                CREATE INDEX IF NOT EXISTS idx_warnings_run ON connector_warnings(run_id);
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
    ) -> int:
        ts = requested_at if requested_at is not None else utcnow()
        payload = (
            ts.isoformat(),
            timeframe,
            json.dumps(topics),
            json.dumps(connector_names),
        )
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO runs (requested_at, timeframe, request_topics_json, connector_names_json)
                VALUES (?,?,?,?)
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
        d = news_item_to_dict(item)
        payload_json = json.dumps(d, ensure_ascii=False)
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

    def get_latest_digest(self) -> Digest | None:
        row = self._latest_digest_row()
        if row is None:
            return None
        return self._digest_from_row(row)

    def _latest_digest_row(self) -> sqlite3.Row | None:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM digests ORDER BY id DESC LIMIT 1").fetchone()

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
            row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            return int(row["id"]) if row else None

    def _load_news_items(self, run_id: int) -> list[NewsItem]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM news_items WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            ).fetchall()
        out: list[NewsItem] = []
        for r in rows:
            out.append(news_item_from_dict(json.loads(r["raw_payload_json"])))
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
            item = news_item_from_dict(json.loads(r["item_json"]))
            ri = RankedItem(
                item=item,
                score_total=float(r["score_total"]),
                score_breakdown=json.loads(r["score_breakdown_json"]),
                selected=bool(r["selected"]),
                selection_reason=r["selection_reason"],
            )
            out.append(ri)
        return out
