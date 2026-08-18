"""Tests for ZhihuConnector (Milestone 6 T3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from ai_news_agent.connectors import ZhihuConnector
from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.models import ConfidenceLevel, SourceKind

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict[str, Any]:
    path = FIXTURES / name
    assert path.is_file(), f"missing fixture {path}"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _envelope(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"Code": 0, "Message": "success", "Data": {"Items": items}}


def _recording_search_transport(
    *,
    payload: dict[str, Any] | None = None,
    payloads: list[dict[str, Any]] | None = None,
    recorded: list[httpx.Request],
    status: int = 200,
    text: str | None = None,
    error: Exception | None = None,
) -> httpx.MockTransport:
    """Route Zhihu search paths to canned responses and record every request."""

    remaining = list(payloads) if payloads is not None else None

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if error is not None:
            raise error
        if request.url.path == "/api/v1/content/zhihu_search":
            if text is not None:
                return httpx.Response(status, text=text)
            body: dict[str, Any]
            if remaining is not None:
                body = remaining.pop(0) if remaining else _envelope([])
            elif payload is not None:
                body = payload
            else:
                body = _envelope([])
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"message": "unexpected path", "path": request.url.path})

    return httpx.MockTransport(handler)


async def _collect_with_payloads(
    payloads: list[dict[str, Any]],
    request: ConnectorRequest,
) -> Any:
    recorded: list[httpx.Request] = []
    transport = _recording_search_transport(payloads=payloads, recorded=recorded)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://developer.zhihu.com",
    ) as client:
        conn = ZhihuConnector(token="test-secret", client=client)
        return await conn.collect(request)


def test_zhihu_connector_stub_name() -> None:
    conn = ZhihuConnector()
    assert conn.name() == "zhihu"


def test_expand_zhihu_queries_uses_first_topic_and_three_lenses() -> None:
    from ai_news_agent.connectors.zhihu import expand_zhihu_queries

    pairs = expand_zhihu_queries(["RAG", "agents"])
    assert pairs == [
        ("RAG 实战 踩坑", "实战 / 踩坑"),
        ("RAG 部署 成本", "部署 / 成本"),
        ("RAG 评测 对比", "评测 / 对比"),
    ]
    assert expand_zhihu_queries([]) == []
    assert expand_zhihu_queries(["  ", ""]) == []


def test_collect_lenses_makes_three_search_calls_and_maps_source_evidence() -> None:
    payload = _load_fixture("zhihu_search_sample.json")
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(payload=payload, recorded=recorded)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert len(recorded) == 3
        queries = []
        for req in recorded:
            parsed = urlparse(str(req.url))
            assert parsed.path == "/api/v1/content/zhihu_search"
            params = parse_qs(parsed.query)
            queries.append(params["Query"][0])
            assert int(params["Count"][0]) == 5
            assert req.headers.get("Authorization") == "Bearer test-secret"
            assert req.headers.get("X-Request-Timestamp")
        assert any("实战" in q for q in queries)
        assert any("部署" in q for q in queries)
        assert any("评测" in q for q in queries)

        assert out.items
        assert all(i.source is SourceKind.ZHIHU for i in out.items)
        first = out.items[0]
        assert first.stars_or_views is None
        assert set(first.source_evidence) >= {
            "relevance",
            "query_lens",
            "source_label",
            "evidence_text_length",
        }
        assert first.source_evidence["query_lens"] in {
            "实战 / 踩坑",
            "部署 / 成本",
            "评测 / 对比",
        }

    asyncio.run(main())


def test_collect_dedupe_shared_content_id_keeps_first_and_counts_raw() -> None:
    sample = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][0]
    first = {**sample, "ContentID": "dup-1", "Title": "First lens title"}
    second = {**sample, "ContentID": "dup-1", "Title": "Second lens title"}

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([first]), _envelope([second]), _envelope([])],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.raw_count == 2
        assert len(out.items) == 1
        assert out.items[0].source_id == "dup-1"
        assert out.items[0].title == "First lens title"

    asyncio.run(main())


def test_collect_dedupe_canonical_url_when_content_id_missing() -> None:
    sample = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][0]
    first = {
        **sample,
        "ContentID": "",
        "Url": "https://www.zhihu.com/question/42?utm=a#frag",
        "Title": "URL first",
    }
    second = {
        **sample,
        "ContentID": "",
        "Url": "https://WWW.ZHIHU.COM/question/42",
        "Title": "URL second",
    }

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([first]), _envelope([second]), _envelope([])],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.raw_count == 2
        assert len(out.items) == 1
        assert out.items[0].title == "URL first"

    asyncio.run(main())


def test_collect_dedupe_trims_to_max_items() -> None:
    sample = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][0]
    rows = [
        {**sample, "ContentID": f"id-{i}", "Title": f"Item {i}"}
        for i in range(3)
    ]

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([rows[0]]), _envelope([rows[1]]), _envelope([rows[2]])],
            ConnectorRequest(topics=["RAG"], max_items=2),
        )
        assert out.raw_count == 3
        assert len(out.items) == 2
        assert [item.source_id for item in out.items] == ["id-0", "id-1"]

    asyncio.run(main())


def test_collect_malformed_missing_url_emits_skipped_warning() -> None:
    sample = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][0]
    bad = {**sample, "ContentID": "bad-url", "Url": ""}
    good = {**sample, "ContentID": "ok-url"}

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([bad, good]), _envelope([]), _envelope([])],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.raw_count == 2
        assert len(out.items) == 1
        assert out.items[0].source_id == "ok-url"
        assert any(w.code == "skipped_malformed_result" for w in out.warnings)

    asyncio.run(main())


def test_collect_malformed_missing_title_emits_skipped_warning() -> None:
    sample = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][0]
    bad = {**sample, "ContentID": "bad-title", "Title": "  "}

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([bad]), _envelope([]), _envelope([])],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.items == []
        assert any(w.code == "skipped_malformed_result" for w in out.warnings)

    asyncio.run(main())


def test_collect_thin_evidence_keeps_item_with_low_confidence() -> None:
    thin = _load_fixture("zhihu_search_sample.json")["Data"]["Items"][1]

    async def main() -> None:
        out = await _collect_with_payloads(
            [_envelope([thin]), _envelope([]), _envelope([])],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert len(out.items) == 1
        assert out.items[0].content_confidence is ConfidenceLevel.LOW
        assert any(w.code == "thin_evidence" for w in out.warnings)

    asyncio.run(main())


def test_collect_timeframe_emits_unsupported_and_does_not_fetch_pages() -> None:
    payload = _load_fixture("zhihu_search_sample.json")
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(payload=payload, recorded=recorded)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(
                ConnectorRequest(
                    topics=["RAG"],
                    max_items=5,
                    timeframe="last_7_days",
                )
            )

        assert out.items
        assert any(w.code == "unsupported_timeframe" for w in out.warnings)
        for req in recorded:
            url = str(req.url)
            assert "/api/v1/content/zhihu_search" in url
            assert "www.zhihu.com" not in url
            assert "zhuanlan.zhihu.com" not in url
            assert "/question/" not in url

    asyncio.run(main())


def test_collect_auth_missing_makes_zero_gets(monkeypatch) -> None:
    monkeypatch.delenv("ZHIHU_ACCESS_SECRET", raising=False)
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            payload=_load_fixture("zhihu_search_sample.json"),
            recorded=recorded,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert recorded == []
        assert out.items == []
        assert any(w.code == "auth_missing" for w in out.warnings)

    asyncio.run(main())


def test_collect_auth_rejected_on_401() -> None:
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            payload={"Message": "unauthorized"},
            recorded=recorded,
            status=401,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="bad-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert out.items == []
        assert any(w.code == "auth_rejected" for w in out.warnings)

    asyncio.run(main())


def test_collect_quota_exhausted_on_429() -> None:
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            payload={"Message": "too many requests"},
            recorded=recorded,
            status=429,
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert out.items == []
        assert any(w.code == "quota_exhausted" for w in out.warnings)

    asyncio.run(main())


def test_collect_quota_exhausted_on_envelope_code() -> None:
    payload = {"Code": 42901, "Message": "quota exceeded", "Data": {"Items": []}}

    async def main() -> None:
        out = await _collect_with_payloads(
            [payload, payload, payload],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.items == []
        assert any(w.code == "quota_exhausted" for w in out.warnings)

    asyncio.run(main())


def test_collect_request_failure_on_network_error() -> None:
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            recorded=recorded,
            error=httpx.ConnectError("connection refused"),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert out.items == []
        assert any(w.code == "request_failed" for w in out.warnings)

    asyncio.run(main())


def test_collect_invalid_search_response_on_bad_json() -> None:
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            recorded=recorded,
            status=200,
            text="{not-json",
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))

        assert out.items == []
        assert any(w.code == "invalid_search_response" for w in out.warnings)

    asyncio.run(main())


def test_collect_invalid_search_response_on_missing_items() -> None:
    payload = {"Code": 1, "Message": "internal error", "Data": {}}

    async def main() -> None:
        out = await _collect_with_payloads(
            [payload, payload, payload],
            ConnectorRequest(topics=["RAG"], max_items=5),
        )
        assert out.items == []
        assert any(w.code == "invalid_search_response" for w in out.warnings)

    asyncio.run(main())


def test_collect_request_failure_aclose_leaves_injected_client_open() -> None:
    recorded: list[httpx.Request] = []

    async def main() -> None:
        transport = _recording_search_transport(
            recorded=recorded,
            error=httpx.ConnectError("connection refused"),
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="https://developer.zhihu.com",
        ) as client:
            conn = ZhihuConnector(token="test-secret", client=client)
            out = await conn.collect(ConnectorRequest(topics=["RAG"], max_items=5))
            await conn.aclose()
            assert not client.is_closed

        assert out.items == []
        assert any(w.code == "request_failed" for w in out.warnings)

    asyncio.run(main())
