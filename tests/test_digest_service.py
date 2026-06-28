"""Tests for the persistent local digest HTTP service."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from ai_news_agent.app.digest_service import DigestServiceServer, build_digest_request_payload


def test_build_digest_request_payload_maps_hints() -> None:
    payload = build_digest_request_payload(
        timeframe_hint="week",
        sources_hint="github",
        topics_hint="RAG, agents",
    )
    assert payload["timeframe"] == "last_7_days"
    assert payload["sources"] == "github"
    assert payload["topics"] == ["RAG", "agents"]


def test_build_digest_request_payload_omits_topics_when_absent() -> None:
    payload = build_digest_request_payload()
    assert payload["timeframe"] == "today"
    assert payload["sources"] == "github,bilibili"
    assert "topics" not in payload


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


def test_health_endpoint_returns_ok(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    assert resp.status == 200
    body = json.loads(resp.read().decode())
    assert body["status"] == "ok"
    assert body["fake"] is True


def test_digest_endpoint_returns_markdown_text(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=30)
    body = json.dumps(
        {
            "timeframe": "today",
            "sources": "github",
            "fake": True,
            "correlation_id": "test-corr-1",
        }
    )
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode())
    assert data["correlation_id"] == "test-corr-1"
    assert "AI News Digest" in data["text"]
    assert "Fake GitHub repo" in data["text"]
    assert isinstance(data["elapsed_s"], float)
    assert data["elapsed_s"] >= 0
    assert "stages" in data


def test_digest_endpoint_rejects_unknown_source(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    body = json.dumps({"sources": "arxiv", "fake": True})
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 400
    data = json.loads(resp.read().decode())
    assert "error" in data
