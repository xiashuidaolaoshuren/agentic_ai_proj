"""Tests for Juya website markdown enrichment and editorial digest output."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from ai_news_agent.adapters.openclaw import (
    normalize_output_language_hint,
    normalize_output_style_hint,
    resolve_openclaw_digest_request,
)
from ai_news_agent.app.digest_service import build_digest_request_payload
from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.connectors.github_juya import (
    clean_issue_markdown,
    enrich_juya_items_with_markdown,
    markdown_url_for_issue,
    parse_juya_rss_rows,
)
from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    SourceKind,
)
from ai_news_agent.rendering import render_digest_editorial_text, select_digest_renderers
from ai_news_agent.request import DigestRequest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
JUYA_URL = "https://github.com/jujuyaya/juya-ai-daily"


def _atom_fixture() -> str:
    return (FIXTURES / "juya_rss_atom_sample.xml").read_text(encoding="utf-8")


def _markdown_fixture() -> str:
    return (FIXTURES / "juya_backup_2026-06-16_sample.md").read_text(encoding="utf-8")


def _website_rss_fixture() -> str:
    return (FIXTURES / "juya_website_rss_sample.xml").read_text(encoding="utf-8")


def test_markdown_url_for_issue_matches_date() -> None:
    assert markdown_url_for_issue("2026-06-16", "https://daily.juya.uk/issues/2026-06-16/") == (
        "https://daily.juya.uk/markdown/2026-06-16.md"
    )


def test_clean_issue_markdown_strips_headings() -> None:
    cleaned = clean_issue_markdown(_markdown_fixture())
    assert "SpaceX" in cleaned
    assert "#" not in cleaned


def test_enrich_juya_items_with_markdown_grows_snippet() -> None:
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    rows = parse_juya_rss_rows(_atom_fixture(), max_items=5, collected_at=now)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markdown/2026-06-16.md":
            return httpx.Response(200, text=_markdown_fixture())
        return httpx.Response(404)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            enriched, warnings = await enrich_juya_items_with_markdown(client, rows)

        assert len(enriched) == 1
        assert "SpaceX" in (enriched[0].raw_snippet or "")
        assert len(enriched[0].raw_snippet or "") > 50
        assert enriched[0].content_confidence is ConfidenceLevel.HIGH
        assert "juya-markdown" in enriched[0].tags
        assert not any(w.code == "juya_markdown_unavailable" for w in warnings)

    asyncio.run(main())


def test_enrich_juya_items_falls_back_to_content_encoded() -> None:
    now = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
    rows = parse_juya_rss_rows(_website_rss_fixture(), max_items=1, collected_at=now)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            enriched, warnings = await enrich_juya_items_with_markdown(client, rows)

        assert len(enriched) == 1
        assert "DeepSeek" in (enriched[0].raw_snippet or "")
        assert "juya-rss-content" in enriched[0].tags
        assert not any(w.code == "juya_markdown_unavailable" for w in warnings)

    asyncio.run(main())


def test_enrich_juya_items_warns_when_markdown_and_encoded_missing() -> None:
    rss_text = (FIXTURES / "juya_rss_sample.xml").read_text(encoding="utf-8")
    now = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
    rows = parse_juya_rss_rows(rss_text, max_items=1, collected_at=now)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async def main() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            enriched, warnings = await enrich_juya_items_with_markdown(client, rows)

        assert "GLM-5.2" in (enriched[0].raw_snippet or "")
        assert any(w.code == "juya_markdown_unavailable" for w in warnings)

    asyncio.run(main())


def test_collect_juya_repo_enriches_from_website_markdown() -> None:
    rss_text = _atom_fixture()
    markdown = {"/markdown/2026-06-16.md": _markdown_fixture()}

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        path = request.url.path
        if host == "daily.juya.uk":
            if path == "/rss.xml":
                return httpx.Response(200, text=rss_text)
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
            out = await GitHubConnector(token=None, client=client).collect(
                ConnectorRequest(
                    topics=[],
                    github_manual_urls=[JUYA_URL],
                    max_items=5,
                ),
            )
        assert len(out.items) == 1
        assert "SpaceX" in (out.items[0].raw_snippet or "")

    asyncio.run(main())


def test_normalize_output_style_and_language_hints() -> None:
    assert normalize_output_style_hint("newsletter") == "editorial"
    assert normalize_output_style_hint(None) is None
    assert normalize_output_language_hint("zh-CN") == "zh-CN"
    assert normalize_output_language_hint("chinese") == "zh-CN"


def test_build_digest_request_payload_includes_style_fields() -> None:
    payload = build_digest_request_payload(
        message="Digest https://github.com/jujuyaya/juya-ai-daily",
        output_style_hint="editorial",
        output_language_hint="zh-CN",
    )
    assert payload["message"].startswith("Digest")
    assert payload["output_style"] == "editorial"
    assert payload["output_language"] == "zh-CN"


def test_resolve_openclaw_digest_request_applies_style_hints() -> None:
    req = resolve_openclaw_digest_request(
        message="Digest https://github.com/jujuyaya/juya-ai-daily",
        output_style_hint="editorial",
        output_language_hint="zh-CN",
    )
    assert req.output_style == "editorial"
    assert req.output_language == "zh-CN"


def test_render_digest_editorial_text_is_compact_index() -> None:
    digest = Digest(
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=UTC),
        entries=[
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="juya-rss-1",
                title="2026-06-18",
                source_name="GitHub",
                source_url="https://daily.juya.uk/issue-7/",
                summary="OpenAI 计划任务；Grok Video 1.5",
                why_it_matters="模型发布",
                background_knowledge="",
                follow_up_action=FollowUpAction.READ,
            ),
            DigestEntry(
                source_kind=SourceKind.GITHUB,
                source_id="juya-rss-2",
                title="2026-06-17",
                source_name="GitHub",
                source_url="https://daily.juya.uk/issue-6/",
                summary="SpaceX 收购 Cursor",
                why_it_matters="行业动态",
                background_knowledge="",
                follow_up_action=FollowUpAction.READ,
            ),
        ],
        topics=[],
        timeframe="today",
    )
    out = render_digest_editorial_text(digest, output_language="zh-CN")
    assert "1." in out
    assert "2." in out
    assert "\n模型发布\n" not in out
    assert "https://daily.juya.uk/issue-7/" in out
    assert "第一条" in out or "follow up" in out.lower()


def test_select_digest_renderers_defaults_to_bulletin() -> None:
    from ai_news_agent.rendering import render_digest_markdown, render_digest_text

    md_fn, txt_fn = select_digest_renderers(None)
    assert md_fn is render_digest_markdown
    assert txt_fn is render_digest_text


def test_select_digest_renderers_editorial_mode() -> None:
    from ai_news_agent.rendering import render_digest_editorial_markdown, render_digest_editorial_text

    md_fn, txt_fn = select_digest_renderers("editorial")
    assert md_fn is render_digest_editorial_markdown
    assert txt_fn is render_digest_editorial_text


def test_digest_request_output_style_defaults_none() -> None:
    req = DigestRequest()
    assert req.output_style is None
    assert req.output_language is None
