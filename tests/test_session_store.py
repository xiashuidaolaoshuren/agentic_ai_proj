"""Session and message repository tests (Milestone 8A.1 T3)."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_news_agent.models import Digest, DigestEntry, FollowUpAction, SourceKind
from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.storage import DigestStore


def _init_db(db_path: Path) -> None:
    DigestStore(db_path).init_schema()


def test_create_and_get_session_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    _init_db(db_path)
    store = SessionStore(db_path)

    store.create_session(
        "sess-1",
        title="My chat",
        connector_names=["github", "zhihu"],
        items_per_source=5,
    )

    row = store.get_session("sess-1")
    assert row is not None
    assert row["id"] == "sess-1"
    assert row["title"] == "My chat"
    assert json.loads(row["connector_names"]) == ["github", "zhihu"]
    assert row["items_per_source"] == 5
    assert row["created_at"] is not None
    assert row["updated_at"] is not None
    assert datetime.fromisoformat(row["created_at"]) <= datetime.now(tz=UTC)


def test_list_sessions_ordered_and_rename(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    _init_db(db_path)
    store = SessionStore(db_path)

    store.create_session("sess-old", title="Old")
    store.create_session("sess-new", title="New")

    with SessionStore(db_path)._conn() as conn:
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00+00:00", "sess-old"),
        )
        conn.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            ("2026-02-01T00:00:00+00:00", "sess-new"),
        )

    listed = store.list_sessions()
    assert [row["id"] for row in listed] == ["sess-new", "sess-old"]

    store.rename_session("sess-old", "Renamed")
    renamed = store.get_session("sess-old")
    assert renamed is not None
    assert renamed["title"] == "Renamed"
    assert renamed["updated_at"] > "2026-01-01T00:00:00+00:00"


def test_update_preferences_rejects_empty_connector_list(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    _init_db(db_path)
    store = SessionStore(db_path)
    store.create_session("sess-1")

    with pytest.raises(ValueError, match="connector_names"):
        store.update_preferences("sess-1", connector_names=[], items_per_source=3)

    store.update_preferences("sess-1", connector_names=["github"], items_per_source=7)
    row = store.get_session("sess-1")
    assert row is not None
    assert json.loads(row["connector_names"]) == ["github"]
    assert row["items_per_source"] == 7

    store.update_preferences("sess-1", connector_names=None, items_per_source=None)
    row = store.get_session("sess-1")
    assert row is not None
    assert row["connector_names"] is None
    assert row["items_per_source"] is None


def test_insert_message_assigns_sequence_and_lists_ordered(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    _init_db(db_path)
    store = SessionStore(db_path)
    store.create_session("sess-1")

    first_id = store.insert_message("sess-1", role="user", content="Hello")
    second_id = store.insert_message("sess-1", role="assistant", content="Hi there")

    messages = store.list_messages("sess-1")
    assert len(messages) == 2
    assert messages[0]["id"] == first_id
    assert messages[0]["sequence"] == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[0]["created_at"] is not None
    assert messages[1]["id"] == second_id
    assert messages[1]["sequence"] == 2
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hi there"


def test_delete_session_nulls_run_session_id_and_keeps_digests(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    _init_db(db_path)
    session_store = SessionStore(db_path)
    digest_store = DigestStore(db_path)

    session_store.create_session("sess-1", title="To delete")
    session_store.insert_message("sess-1", role="user", content="Hello")

    collected = datetime(2026, 5, 7, 10, 0, 0, tzinfo=UTC)
    run_id = digest_store.save_run(
        requested_at=collected,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE runs SET session_id = ? WHERE id = ?", ("sess-1", run_id))
        conn.commit()

    digest = Digest(
        generated_at=collected,
        topics=["RAG"],
        timeframe="today",
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="repo-1",
                title="Digest title",
                source_name="github",
                source_url="https://github.com/a/b",
                summary="summary",
                why_it_matters="why",
                background_knowledge="bg",
                follow_up_action=FollowUpAction.READ,
            )
        ],
    )
    digest_id = digest_store.save_digest(run_id, digest)

    session_store.delete_session("sess-1")

    assert session_store.get_session("sess-1") is None
    assert session_store.list_messages("sess-1") == []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute("SELECT session_id FROM runs WHERE id = ?", (run_id,)).fetchone()
        digest_row = conn.execute(
            "SELECT id FROM digests WHERE id = ?",
            (digest_id,),
        ).fetchone()

    assert run_row is not None
    assert run_row["session_id"] is None
    assert digest_row is not None
