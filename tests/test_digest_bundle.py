"""Atomic digest bundle and Unit of Work tests (Milestone 8A.1 T6)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_agent.models import (
    ConnectorWarning,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.storage import DigestStore


def _init_db(db_path: Path) -> None:
    DigestStore(db_path).init_schema()


def _bundle_table_counts(db_path: Path) -> dict[str, int]:
    tables = (
        "runs",
        "news_items",
        "connector_warnings",
        "ranked_items",
        "digests",
        "digest_entries",
    )
    with sqlite3.connect(db_path) as conn:
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _sample_bundle(now: datetime | None = None) -> dict[str, object]:
    ts = now if now is not None else datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo",
        collected_at=ts,
    )
    warning = ConnectorWarning(connector="github", code="rate", message="slow")
    ranked = [
        RankedItem(
            item=item,
            score_total=2.5,
            score_breakdown={"k": 1.0},
            selected=True,
            selection_reason="top",
        )
    ]
    digest = Digest(
        generated_at=ts,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=["RAG"],
        timeframe="last_7_days",
    )
    return {
        "requested_at": ts,
        "timeframe": "last_7_days",
        "topics": ["RAG"],
        "connector_names": ["github"],
        "items": [item],
        "warnings": [warning],
        "ranked": ranked,
        "digest": digest,
    }


def test_sqlite_unit_of_work_importable_and_instantiable(tmp_path: Path) -> None:
    from ai_news_agent.repositories.unit_of_work import SqliteUnitOfWork

    uow = SqliteUnitOfWork(tmp_path / "uow.db")
    assert uow is not None


def test_unit_of_work_commit_persists_digest_and_session_writes(tmp_path: Path) -> None:
    from ai_news_agent.repositories.unit_of_work import SqliteUnitOfWork

    db_path = tmp_path / "uow-commit.db"
    _init_db(db_path)

    with SqliteUnitOfWork(db_path) as uow:
        uow.session_store.create_session("sess-1", title="Chat")
        uow.session_store.insert_message("sess-1", role="user", content="Hello")

    session_store = SessionStore(db_path)
    row = session_store.get_session("sess-1")
    assert row is not None
    assert row["title"] == "Chat"
    messages = session_store.list_messages("sess-1")
    assert len(messages) == 1
    assert messages[0]["content"] == "Hello"


def test_unit_of_work_rollback_discards_digest_and_session_writes(tmp_path: Path) -> None:
    from ai_news_agent.repositories.unit_of_work import SqliteUnitOfWork

    db_path = tmp_path / "uow-rollback.db"
    _init_db(db_path)

    try:
        with SqliteUnitOfWork(db_path) as uow:
            uow.session_store.create_session("sess-1", title="Chat")
            raise RuntimeError("abort")
    except RuntimeError:
        pass

    session_store = SessionStore(db_path)
    assert session_store.get_session("sess-1") is None

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 0


def test_save_digest_bundle_persists_complete_bundle(tmp_path: Path) -> None:
    db_path = tmp_path / "bundle-happy.db"
    _init_db(db_path)
    store = DigestStore(db_path)
    bundle = _sample_bundle()

    run_id = store.save_digest_bundle(**bundle)

    assert run_id == 1
    ctx = store.get_latest_followup_context()
    assert ctx.run_id == 1
    assert ctx.digest == bundle["digest"]
    assert ctx.ranked_items == bundle["ranked"]
    assert ctx.news_items == bundle["items"]
    assert ctx.warnings == bundle["warnings"]


def test_save_digest_bundle_rolls_back_on_mid_bundle_failure(tmp_path: Path) -> None:
    db_path = tmp_path / "bundle-rollback.db"
    _init_db(db_path)
    store = DigestStore(db_path)
    bundle = _sample_bundle()
    ghost_item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="ghost",
        url="https://example.com/ghost",
        title="Ghost",
        collected_at=bundle["requested_at"],  # type: ignore[arg-type]
    )
    bundle["ranked"] = [
        RankedItem(
            item=ghost_item,
            score_total=1.0,
            score_breakdown={"k": 1.0},
            selected=True,
            selection_reason="ghost",
        )
    ]

    with pytest.raises(ValueError, match="No news_item"):
        store.save_digest_bundle(**bundle)

    assert _bundle_table_counts(db_path) == dict.fromkeys(
        (
            "runs",
            "news_items",
            "connector_warnings",
            "ranked_items",
            "digests",
            "digest_entries",
        ),
        0,
    )


def test_save_digest_bundle_links_session_run_and_active_request(tmp_path: Path) -> None:
    db_path = tmp_path / "bundle-session.db"
    _init_db(db_path)
    digest_store = DigestStore(db_path)
    session_store = SessionStore(db_path)

    session_store.create_session("sess-1", title="Chat")
    user_message_id = session_store.insert_message("sess-1", role="user", content="Digest please")
    session_store.create_request(
        "sess-1",
        "req-1",
        user_message_id=user_message_id,
        correlation_id="corr-1",
    )

    bundle = _sample_bundle()
    run_id = digest_store.save_digest_bundle(**bundle, session_id="sess-1")

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute("SELECT session_id FROM runs WHERE id = ?", (run_id,)).fetchone()
        request_row = conn.execute(
            """
            SELECT run_id FROM session_requests
            WHERE session_id = ? AND id = ?
            """,
            ("sess-1", "req-1"),
        ).fetchone()

    assert run_row is not None
    assert run_row["session_id"] == "sess-1"
    assert request_row is not None
    assert request_row["run_id"] == run_id
