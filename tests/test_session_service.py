"""Session service tests (Milestone 8A.1 T7)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ai_news_agent.repositories.session_store import SessionStore
from ai_news_agent.storage import DigestStore


def _init_db(db_path: Path) -> None:
    DigestStore(db_path).init_schema()


def test_services_modules_importable_with_record_types(tmp_path: Path) -> None:
    from ai_news_agent.services.session_records import (
        MessageRecord,
        SessionRecord,
        SessionRequestRecord,
        initial_session_title,
    )
    from ai_news_agent.services.session_service import SessionBusyError, SessionService

    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    session = SessionRecord(
        id="sess-1",
        title=None,
        connector_names=None,
        items_per_source=None,
        created_at=now,
        updated_at=now,
    )
    message = MessageRecord(
        id=1,
        session_id="sess-1",
        sequence=1,
        role="user",
        content="Hello",
        run_id=None,
        created_at=now,
    )
    request_record = SessionRequestRecord(
        id="req-1",
        session_id="sess-1",
        status="active",
        user_message_id=1,
        assistant_message_id=None,
        run_id=None,
        correlation_id="corr-1",
        error_code=None,
        error_message=None,
        started_at=now,
        completed_at=None,
    )

    assert session.id == "sess-1"
    assert message.role == "user"
    assert request_record.status == "active"
    assert callable(initial_session_title)
    assert issubclass(SessionBusyError, Exception)

    service = SessionService(SessionStore(tmp_path / "svc.db"))
    assert service is not None


def test_initial_session_title_first_nonblank_line_normalized() -> None:
    from ai_news_agent.services.session_records import initial_session_title

    assert initial_session_title("What is   RAG?\tand why") == "What is RAG? and why"
    assert initial_session_title("  spaced  line  ") == "spaced line"
    assert initial_session_title("first line\nsecond line") == "first line"
    assert initial_session_title("\n\n  \nreal content\nmore") == "real content"


def test_initial_session_title_blank_content_returns_none() -> None:
    from ai_news_agent.services.session_records import initial_session_title

    assert initial_session_title("") is None
    assert initial_session_title("   ") is None
    assert initial_session_title("  \n \t \n  ") is None


def test_initial_session_title_truncates_to_60_unicode_chars() -> None:
    from ai_news_agent.services.session_records import initial_session_title

    exact = "a" * 60
    assert initial_session_title(exact) == exact
    assert len(initial_session_title("b" * 70)) == 60

    cjk = "字" * 65
    truncated = initial_session_title(cjk)
    assert truncated is not None
    assert len(truncated) == 60
    assert truncated == "字" * 60


def test_create_get_list_rename_session_round_trip(tmp_path: Path) -> None:
    import uuid

    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-crud.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))

    created = service.create_session()
    assert uuid.UUID(created.id)
    assert created.title is None
    assert created.connector_names is None
    assert created.items_per_source is None
    assert created.created_at <= datetime.now(tz=UTC)
    assert created.updated_at <= datetime.now(tz=UTC)

    fetched = service.get_session(created.id)
    assert fetched == created
    assert service.get_session("missing") is None

    other = service.create_session()
    service.rename_session(created.id, "Renamed")

    listed = service.list_sessions()
    assert [s.id for s in listed] == [created.id, other.id]

    renamed = service.get_session(created.id)
    assert renamed is not None
    assert renamed.title == "Renamed"
    assert renamed.updated_at > created.updated_at


def test_get_session_decodes_stored_preferences(tmp_path: Path) -> None:
    import json

    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-decode.db"
    _init_db(db_path)
    store = SessionStore(db_path)
    service = SessionService(store)

    store.create_session(
        "sess-pref",
        title="Prefs",
        connector_names=["github", "zhihu"],
        items_per_source=7,
    )

    record = service.get_session("sess-pref")
    assert record is not None
    assert record.connector_names == ["github", "zhihu"]
    assert record.items_per_source == 7
    assert record.title == "Prefs"
    assert isinstance(record.created_at, datetime)


def test_record_user_message_sets_initial_title_once(tmp_path: Path) -> None:
    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-title-once.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))
    created = service.create_session()

    first = service.record_user_message(created.id, content="  What is   RAG? ")
    assert first.sequence == 1
    assert first.role == "user"
    assert first.session_id == created.id
    assert first.run_id is None

    titled = service.get_session(created.id)
    assert titled is not None
    assert titled.title == "What is RAG?"

    service.record_user_message(created.id, content="Second question")
    after = service.get_session(created.id)
    assert after is not None
    assert after.title == "What is RAG?"

    service.rename_session(created.id, "Custom name")
    service.record_user_message(created.id, content="Third question")
    final = service.get_session(created.id)
    assert final is not None
    assert final.title == "Custom name"


def test_record_user_message_blank_content_keeps_title_null(tmp_path: Path) -> None:
    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-blank-title.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))
    created = service.create_session()

    service.record_user_message(created.id, content="   \n  ")

    record = service.get_session(created.id)
    assert record is not None
    assert record.title is None


def test_update_preferences_round_trip_and_empty_list_rejected(tmp_path: Path) -> None:
    import pytest

    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-prefs.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))
    created = service.create_session()

    service.update_preferences(
        created.id, connector_names=["github", "zhihu"], items_per_source=5
    )
    record = service.get_session(created.id)
    assert record is not None
    assert record.connector_names == ["github", "zhihu"]
    assert record.items_per_source == 5

    service.update_preferences(created.id, connector_names=None, items_per_source=None)
    cleared = service.get_session(created.id)
    assert cleared is not None
    assert cleared.connector_names is None
    assert cleared.items_per_source is None

    with pytest.raises(ValueError, match="connector_names"):
        service.update_preferences(created.id, connector_names=[], items_per_source=3)


def test_build_request_applies_preferences_as_one_request_defaults(tmp_path: Path) -> None:
    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-build-req.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))
    created = service.create_session()
    service.update_preferences(created.id, connector_names=["github"], items_per_source=5)

    default_req = service.build_request(created.id, "Give me today's digest")
    assert default_req.connector_names == ["github"]
    assert default_req.max_items_per_source == 5

    overridden = service.build_request(created.id, "zhihu only: give me a digest")
    assert overridden.connector_names == ["zhihu"]

    stored = service.get_session(created.id)
    assert stored is not None
    assert stored.connector_names == ["github"]
    assert stored.items_per_source == 5


def test_build_request_missing_session_raises(tmp_path: Path) -> None:
    import pytest

    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-build-missing.db"
    _init_db(db_path)
    service = SessionService(SessionStore(db_path))

    with pytest.raises(KeyError):
        service.build_request("missing", "Give me today's digest")


def _save_session_bundle(db_path: Path, session_id: str) -> int:
    from datetime import UTC as _UTC

    from ai_news_agent.models import Digest

    store = DigestStore(db_path)
    digest = Digest(
        generated_at=datetime(2026, 5, 16, 12, 0, tzinfo=_UTC),
        entries=[],
        topics=["RAG"],
        timeframe=None,
    )
    return store.save_digest_bundle(
        requested_at=datetime(2026, 5, 16, 12, 0, tzinfo=_UTC),
        timeframe=None,
        topics=["RAG"],
        connector_names=["github"],
        items=[],
        warnings=[],
        ranked=[],
        digest=digest,
        session_id=session_id,
    )


def test_delete_inactive_session_cascades_and_keeps_digest(tmp_path: Path) -> None:
    import sqlite3

    from ai_news_agent.services.session_service import SessionService

    db_path = tmp_path / "svc-delete.db"
    _init_db(db_path)
    store = SessionStore(db_path)
    service = SessionService(store)
    created = service.create_session()
    service.record_user_message(created.id, content="Hello")

    run_id = _save_session_bundle(db_path, created.id)
    store.create_request(
        created.id,
        "req-1",
        user_message_id=1,
        correlation_id="corr-1",
    )
    store.mark_terminal(created.id, "req-1", status="succeeded")

    service.delete_session(created.id)

    assert service.get_session(created.id) is None
    assert store.list_messages(created.id) == []

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute(
            "SELECT session_id FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        digest_count = conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0]
    assert run_row is not None
    assert run_row["session_id"] is None
    assert digest_count == 1


def test_delete_active_session_raises_session_busy(tmp_path: Path) -> None:
    import pytest

    from ai_news_agent.services.session_service import SessionBusyError, SessionService

    db_path = tmp_path / "svc-delete-busy.db"
    _init_db(db_path)
    store = SessionStore(db_path)
    service = SessionService(store)
    created = service.create_session()
    service.record_user_message(created.id, content="Hello")
    store.create_request(
        created.id,
        "req-1",
        user_message_id=1,
        correlation_id="corr-1",
    )

    with pytest.raises(SessionBusyError):
        service.delete_session(created.id)

    assert service.get_session(created.id) is not None