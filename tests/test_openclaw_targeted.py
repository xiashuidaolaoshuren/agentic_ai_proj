"""Tests for OpenClaw targeted digest routing (BV/URL/channel selectors)."""

from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from ai_news_agent.adapters.openclaw import (
    resolve_openclaw_digest_request,
    validate_source_selector_consistency,
)
from ai_news_agent.adapters.openclaw_client import request_digest_markdown
from ai_news_agent.app.digest_service import DigestServiceServer, build_digest_request_payload
from ai_news_agent.request import DigestRequest


def test_resolve_openclaw_digest_request_parses_bilibili_bv_from_message() -> None:
    req = resolve_openclaw_digest_request(
        message="Digest bilibili video BV1gRJs63EYX",
    )
    assert "https://www.bilibili.com/video/BV1gRJs63EYX" in req.bilibili_manual_urls
    assert req.topics == []
    assert req.connector_names == ["bilibili"]


def test_resolve_openclaw_digest_request_parses_github_repo_url() -> None:
    req = resolve_openclaw_digest_request(
        message="Digest https://github.com/langchain-ai/langgraph",
    )
    assert any("langchain-ai/langgraph" in u for u in req.github_manual_urls)
    assert req.connector_names == ["github"]


def test_resolve_openclaw_digest_request_parses_juya_daily_repo_url() -> None:
    req = resolve_openclaw_digest_request(
        message="Digest https://github.com/jujuyaya/juya-ai-daily",
    )
    assert any("jujuyaya/juya-ai-daily" in u for u in req.github_manual_urls)
    assert req.connector_names == ["github"]


def test_resolve_openclaw_digest_request_parses_juya_website_url() -> None:
    req = resolve_openclaw_digest_request(
        message="Digest https://daily.juya.uk/",
    )
    assert any("daily.juya.uk" in u for u in req.github_manual_urls)
    assert req.connector_names == ["github"]


def test_juya_targeted_openclaw_path_yields_rss_entries_beyond_repo_metadata() -> None:
    """OpenClaw resolve + GitHub connector should surface daily website RSS entries."""
    import asyncio
    from pathlib import Path

    import httpx

    from ai_news_agent.connectors.base import ConnectorRequest
    from ai_news_agent.connectors.github import GitHubConnector
    from ai_news_agent.graph.nodes.parse import parse_request_node
    from ai_news_agent.graph.state import DigestGraphState

    fixture = (
        Path(__file__).resolve().parent / "fixtures" / "juya_rss_sample.xml"
    ).read_text(encoding="utf-8")
    markdown = {
        "/markdown/2026-06-16.md": "# 2026-06-16\n\nGLM-5.2 release and ZCode 3.0 updates.",
        "/markdown/2026-06-15.md": "# 2026-06-15\n\nPrior day AI news roundup.",
    }

    req = resolve_openclaw_digest_request(
        message="Digest https://github.com/jujuyaya/juya-ai-daily",
    )
    parsed = parse_request_node(DigestGraphState(request=req))
    connector_req: ConnectorRequest = parsed["connector_request"]  # type: ignore[index]

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        path = request.url.path
        if host == "daily.juya.uk":
            if path == "/rss.xml":
                return httpx.Response(200, text=fixture)
            if path in markdown:
                return httpx.Response(200, text=markdown[path])
            return httpx.Response(404)
        return httpx.Response(404, json={"message": "not found"})

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://api.github.com",
        ) as client:
            out = await GitHubConnector(token=None, client=client).collect(connector_req)

        assert len(out.items) >= 1
        assert out.items[0].title == "2026-06-16"
        assert "daily.juya.uk" in out.items[0].url
        assert out.items[0].title != "jujuyaya/juya-ai-daily"

    asyncio.run(main())


def test_validate_source_selector_consistency_rejects_github_only_with_bilibili_url() -> None:
    req = DigestRequest(
        topics=[],
        connector_names=["github"],
        bilibili_manual_urls=["https://www.bilibili.com/video/BV1demo0001"],
    )
    with pytest.raises(ValueError, match="Bilibili"):
        validate_source_selector_consistency(req)


def test_validate_source_selector_consistency_rejects_bilibili_only_with_github_url() -> None:
    req = DigestRequest(
        topics=[],
        connector_names=["bilibili"],
        github_manual_urls=["https://github.com/acme/widget"],
    )
    with pytest.raises(ValueError, match="GitHub"):
        validate_source_selector_consistency(req)


def test_build_digest_request_payload_includes_message() -> None:
    payload = build_digest_request_payload(
        message="Digest bilibili video BV1gRJs63EYX",
    )
    assert payload["message"] == "Digest bilibili video BV1gRJs63EYX"
    assert "sources" not in payload or payload.get("sources") is None


@pytest.fixture
def service_server(tmp_path: Path) -> DigestServiceServer:
    server = DigestServiceServer(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "targeted.db",
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


def test_digest_endpoint_accepts_targeted_bilibili_message(
    service_server: DigestServiceServer,
) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=30)
    body = json.dumps(
        {
            "message": "Digest bilibili video BV1demo0001",
            "fake": True,
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
    assert "AI News Digest" in data["text"]


def test_request_digest_markdown_with_message(service_server: DigestServiceServer) -> None:
    url = f"http://127.0.0.1:{service_server.port}"
    text = request_digest_markdown(
        url,
        message="Digest https://github.com/acme/widget",
        fake=True,
    )
    assert "AI News Digest" in text
