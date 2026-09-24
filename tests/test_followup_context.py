"""Shared-interface versus session follow-up context tests (Milestone 8A.1 T5)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.models import Digest, DigestEntry, FollowUpAction, NewsItem, SourceKind
from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.storage import DigestStore


def _init_db(db_path: Path) -> None:
    DigestStore(db_path).init_schema()


def _save_digest(
    store: DigestStore,
    *,
    topics: list[str],
    session_id: str | None = None,
) -> int:
    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id=f"repo-{topics[0]}",
        url=f"https://example.com/{topics[0]}",
        title=f"Repo {topics[0]}",
        collected_at=collected,
    )
    digest = Digest(
        generated_at=collected,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id=item.source_id,
                title=item.title,
                source_name="GitHub",
                source_url=item.url,
                summary="summary",
                why_it_matters="why",
                background_knowledge="bg",
                follow_up_action=FollowUpAction.READ,
            )
        ],
        topics=topics,
        timeframe="today",
    )
    run_id = store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=topics,
        connector_names=["github"],
    )
    if session_id is not None:
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE runs SET session_id = ? WHERE id = ?", (session_id, run_id))
            conn.commit()
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(run_id, [])
    store.save_digest(run_id, digest)
    return run_id


def test_get_latest_followup_context_excludes_session_scoped_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "followup.db"
    _init_db(db_path)
    store = DigestStore(db_path)
    session_store = SessionStore(db_path)
    session_store.create_session("sess-1")

    shared_run_id = _save_digest(store, topics=["shared"])
    session_run_id = _save_digest(store, topics=["session"], session_id="sess-1")
    assert session_run_id > shared_run_id

    ctx = store.get_latest_followup_context()
    assert ctx.run_id == shared_run_id
    assert ctx.digest is not None
    assert ctx.digest.topics == ["shared"]


def test_get_followup_context_for_session_returns_latest_request_digest(tmp_path: Path) -> None:
    db_path = tmp_path / "followup.db"
    _init_db(db_path)
    store = DigestStore(db_path)
    session_store = SessionStore(db_path)
    session_store.create_session("sess-1")
    user_message_id = session_store.insert_message("sess-1", role="user", content="Hello")

    run_id = _save_digest(store, topics=["session-a"], session_id="sess-1")
    session_store.create_request(
        "sess-1",
        "req-old",
        user_message_id=user_message_id,
        correlation_id="corr-old",
        started_at="2026-01-01T00:00:00+00:00",
    )
    session_store.update_request_run_id("sess-1", "req-old", run_id)
    session_store.mark_terminal("sess-1", "req-old", status="succeeded")

    run_id_new = _save_digest(store, topics=["session-b"], session_id="sess-1")
    session_store.create_request(
        "sess-1",
        "req-new",
        user_message_id=user_message_id,
        correlation_id="corr-new",
        started_at="2026-02-01T00:00:00+00:00",
    )
    session_store.update_request_run_id("sess-1", "req-new", run_id_new)
    session_store.mark_terminal("sess-1", "req-new", status="succeeded")

    ctx = store.get_followup_context_for_session("sess-1")
    assert ctx.run_id == run_id_new
    assert ctx.digest is not None
    assert ctx.digest.topics == ["session-b"]


def test_get_followup_context_for_session_excludes_interrupted_requests(tmp_path: Path) -> None:
    db_path = tmp_path / "followup.db"
    _init_db(db_path)
    store = DigestStore(db_path)
    session_store = SessionStore(db_path)
    session_store.create_session("sess-1")
    user_message_id = session_store.insert_message("sess-1", role="user", content="Hello")

    succeeded_run_id = _save_digest(store, topics=["succeeded"], session_id="sess-1")
    session_store.create_request(
        "sess-1",
        "req-succeeded",
        user_message_id=user_message_id,
        correlation_id="corr-succeeded",
        started_at="2026-01-01T00:00:00+00:00",
    )
    session_store.update_request_run_id("sess-1", "req-succeeded", succeeded_run_id)
    session_store.mark_terminal("sess-1", "req-succeeded", status="succeeded")

    interrupted_run_id = _save_digest(store, topics=["interrupted"], session_id="sess-1")
    session_store.create_request(
        "sess-1",
        "req-interrupted",
        user_message_id=user_message_id,
        correlation_id="corr-interrupted",
        started_at="2026-02-01T00:00:00+00:00",
    )
    session_store.update_request_run_id("sess-1", "req-interrupted", interrupted_run_id)
    session_store.mark_terminal("sess-1", "req-interrupted", status="interrupted")

    ctx = store.get_followup_context_for_session("sess-1")
    assert ctx.run_id == succeeded_run_id
    assert ctx.digest is not None
    assert ctx.digest.topics == ["succeeded"]
