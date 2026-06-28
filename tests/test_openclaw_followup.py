"""Tests for OpenClaw structured follow-up (service, client, shared formatter)."""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path

import httpx
import pytest

from ai_news_agent.adapters.openclaw_client import (
    build_openclaw_followup_argv,
    followup_main,
    request_followup_text,
)
from ai_news_agent.app.digest_service import DigestServiceServer, build_followup_request_payload
from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.followup_structured import (
    NO_SAVED_DIGEST,
    OPENCLAW_GUIDANCE_FALLBACK,
    answer_structured_followup,
    handle_openclaw_structured_followup,
    parse_rank_from_message,
)
from ai_news_agent.models import (
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore


def _seed_digest_store(store: DigestStore) -> int:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="r1",
        url="https://example.com/r1",
        title="Repo One",
        collected_at=now,
    )
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Repo One",
                source_name="GitHub",
                source_url=item.url,
                summary="S",
                why_it_matters="W",
                background_knowledge="B",
                follow_up_action=FollowUpAction.READ,
                confidence_caveat="metadata only",
            )
        ],
        topics=["AI"],
        timeframe="today",
    )
    run_id = store.save_run(
        requested_at=now,
        timeframe="today",
        topics=["AI"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [
            RankedItem(
                item=item,
                score_total=0.9,
                selected=True,
                selection_reason="top github match",
            )
        ],
    )
    store.save_digest(run_id, digest)
    return run_id


def _seed_multi_item_digest_store(store: DigestStore) -> int:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    items = [
        NewsItem(
            source=SourceKind.GITHUB,
            source_id="r1",
            url="https://example.com/r1",
            title="Item One",
            collected_at=now,
        ),
        NewsItem(
            source=SourceKind.GITHUB,
            source_id="r2",
            url="https://example.com/r2",
            title="Item Two",
            collected_at=now,
        ),
    ]
    digest = Digest(
        generated_at=now,
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r1",
                title="Item One",
                source_name="GitHub",
                source_url=items[0].url,
                summary="Summary one",
                why_it_matters="Why one",
                background_knowledge="Bg one",
                follow_up_action=FollowUpAction.READ,
            ),
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="r2",
                title="Item Two",
                source_name="GitHub",
                source_url=items[1].url,
                summary="Summary two",
                why_it_matters="Why two",
                background_knowledge="Bg two",
                follow_up_action=FollowUpAction.READ,
                confidence_caveat="thin metadata",
            ),
        ],
        topics=["AI"],
        timeframe="today",
    )
    run_id = store.save_run(
        requested_at=now,
        timeframe="today",
        topics=["AI"],
        connector_names=["github"],
    )
    store.save_connector_result(
        run_id,
        ConnectorResult(items=items, warnings=[]),
    )
    store.save_ranked_items(
        run_id,
        [
            RankedItem(item=items[0], score_total=0.9, selected=True),
            RankedItem(item=items[1], score_total=0.7, selected=True),
        ],
    )
    store.save_digest(run_id, digest)
    return run_id


def test_parse_rank_from_message_numeric_and_ordinal() -> None:
    assert parse_rank_from_message("follow up on item 1") == 1
    assert parse_rank_from_message("tell me about #2") == 2
    assert parse_rank_from_message("rank 3 please") == 3
    assert parse_rank_from_message("the second one") == 2
    assert parse_rank_from_message("followup the first issue") == 1
    assert parse_rank_from_message("Digest the first news") == 1
    assert parse_rank_from_message("the first news") == 1


def test_parse_rank_from_message_returns_none_when_unrecognized() -> None:
    assert parse_rank_from_message("why does this matter?") is None
    assert parse_rank_from_message("show sources") is None


def test_answer_structured_followup_rank_item_first(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "multi.db")
    store.init_schema()
    _seed_multi_item_digest_store(store)
    ctx = store.get_latest_followup_context()
    reply = answer_structured_followup("follow up on item 1", ctx)
    assert reply is not None
    assert "Item One" in reply
    assert "Summary one" in reply
    assert "Why one" in reply
    assert "https://example.com/r1" in reply


def test_answer_structured_followup_rank_item_second(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "multi.db")
    store.init_schema()
    _seed_multi_item_digest_store(store)
    ctx = store.get_latest_followup_context()
    reply = answer_structured_followup("follow up on the second one", ctx)
    assert reply is not None
    assert "Item Two" in reply
    assert "thin metadata" in reply


def test_answer_structured_followup_rank_out_of_range(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    _seed_digest_store(store)
    ctx = store.get_latest_followup_context()
    reply = answer_structured_followup("item 5", ctx)
    assert reply is not None
    assert "No digest item at rank 5" in reply


def test_handle_openclaw_structured_followup_rank_item(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "multi.db")
    store.init_schema()
    _seed_multi_item_digest_store(store)
    outcome = handle_openclaw_structured_followup(
        message="followup the first issue",
        store=store,
    )
    assert outcome["path"] == "structured"
    assert "Item One" in str(outcome["text"])


def test_handle_openclaw_structured_followup_guidance_fallback(tmp_path: Path) -> None:
    payload = build_followup_request_payload(message="  show sources  ")
    assert payload == {"message": "show sources"}


def test_handle_openclaw_structured_followup_no_digest(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "empty.db")
    store.init_schema()
    outcome = handle_openclaw_structured_followup(message="show sources", store=store)
    assert outcome["path"] == "no_digest"
    assert outcome["text"] == NO_SAVED_DIGEST
    assert outcome["run_id"] is None


def test_handle_openclaw_structured_followup_sources(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    run_id = _seed_digest_store(store)
    outcome = handle_openclaw_structured_followup(message="show sources", store=store)
    assert outcome["path"] == "structured"
    assert outcome["run_id"] == run_id
    assert "https://example.com/r1" in str(outcome["text"])


def test_handle_openclaw_structured_followup_ranking(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    _seed_digest_store(store)
    outcome = handle_openclaw_structured_followup(
        message="which item should I study first",
        store=store,
    )
    assert outcome["path"] == "structured"
    assert "Repo One" in str(outcome["text"])
    assert "top github match" in str(outcome["text"])


def test_handle_openclaw_structured_followup_caveats(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    _seed_digest_store(store)
    outcome = handle_openclaw_structured_followup(message="show caveats", store=store)
    assert outcome["path"] == "structured"
    assert "metadata only" in str(outcome["text"])


def test_handle_openclaw_structured_followup_guidance_fallback(tmp_path: Path) -> None:
    store = DigestStore(tmp_path / "ctx.db")
    store.init_schema()
    _seed_digest_store(store)
    outcome = handle_openclaw_structured_followup(
        message="why does the top story matter for my team?",
        store=store,
    )
    assert outcome["path"] == "guidance"
    assert outcome["text"] == OPENCLAW_GUIDANCE_FALLBACK


def test_build_followup_request_payload() -> None:
    assert build_openclaw_followup_argv(message="show sources") == [
        "openclaw-followup",
        "--message",
        "show sources",
    ]


@pytest.fixture
def service_server(tmp_path: Path) -> DigestServiceServer:
    server = DigestServiceServer(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "svc.db",
        fake=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while server.port is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.port is not None
    yield server
    server.shutdown()


def test_followup_endpoint_requires_message(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    conn.request(
        "POST",
        "/followup",
        body=json.dumps({}),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 400
    data = json.loads(resp.read().decode())
    assert "message" in data["error"]


def test_followup_endpoint_no_digest(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    conn.request(
        "POST",
        "/followup",
        body=json.dumps({"message": "show sources", "correlation_id": "f1"}),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode())
    assert data["correlation_id"] == "f1"
    assert data["path"] == "no_digest"
    assert "No saved digest" in data["text"]


def test_followup_endpoint_after_digest(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=30)

    digest_body = json.dumps(
        {
            "timeframe": "today",
            "sources": "github",
            "fake": True,
            "correlation_id": "digest-1",
        }
    )
    conn.request(
        "POST",
        "/digest",
        body=digest_body,
        headers={"Content-Type": "application/json"},
    )
    digest_resp = conn.getresponse()
    assert digest_resp.status == 200
    digest_resp.read()

    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    conn.request(
        "POST",
        "/followup",
        body=json.dumps({"message": "show sources", "correlation_id": "follow-1"}),
        headers={"Content-Type": "application/json"},
    )
    follow_resp = conn.getresponse()
    assert follow_resp.status == 200
    data = json.loads(follow_resp.read().decode())
    assert data["correlation_id"] == "follow-1"
    assert data["path"] == "structured"
    assert "Fake GitHub repo" in data["text"]
    assert data["run_id"] is not None


def test_request_followup_text_client(service_server: DigestServiceServer) -> None:
    url = f"http://127.0.0.1:{service_server.port}"

    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"{url}/digest",
            json={
                "timeframe": "today",
                "sources": "github",
                "fake": True,
            },
        )

    text = request_followup_text(url, message="show sources", correlation_id="client-1")
    assert "Fake GitHub repo" in text


def test_followup_endpoint_rank_item_after_digest(service_server: DigestServiceServer) -> None:
    url_host = "127.0.0.1"
    port = service_server.port

    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"http://{url_host}:{port}/digest",
            json={
                "timeframe": "today",
                "sources": "github",
                "fake": True,
            },
        )
        resp = client.post(
            f"http://{url_host}:{port}/followup",
            json={"message": "follow up on item 1", "correlation_id": "rank-1"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "structured"
    assert data["correlation_id"] == "rank-1"
    assert "Digest item 1:" in data["text"]


def test_followup_main_cli(service_server: DigestServiceServer) -> None:
    import io

    url = f"http://127.0.0.1:{service_server.port}"

    with httpx.Client(timeout=30.0) as client:
        client.post(
            f"{url}/digest",
            json={
                "timeframe": "today",
                "sources": "github",
                "fake": True,
            },
        )

    out = io.StringIO()
    code = followup_main(
        ["--message", "show sources", "--service-url", url],
        stdout=out,
    )
    assert code == 0
    assert "Fake GitHub repo" in out.getvalue()
