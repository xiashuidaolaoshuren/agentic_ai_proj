"""Tests for natural-language digest intent parsing."""

from __future__ import annotations

import pytest

from ai_news_agent.intent import parse_connector_names_from_message, parse_digest_intent


def test_parse_bilibili_video_url_skips_default_topics() -> None:
    req = parse_digest_intent(
        "Digest https://www.bilibili.com/video/BV1demo0001",
    )
    assert req.topics == []
    assert "https://www.bilibili.com/video/BV1demo0001" in req.bilibili_manual_urls


def test_parse_github_repo_url() -> None:
    req = parse_digest_intent(
        "Please digest https://github.com/acme/widget for me",
    )
    assert req.topics == []
    assert any("github.com/acme/widget" in u for u in req.github_manual_urls)
    assert req.github_target_channels == []


def test_parse_juya_website_url_routes_to_github_connector() -> None:
    req = parse_digest_intent("Digest https://daily.juya.uk/")
    assert req.topics == []
    assert any("daily.juya.uk" in u for u in req.github_manual_urls)


def test_parse_github_repo_url_does_not_infer_owner_channel() -> None:
    req = parse_digest_intent(
        "Digest https://github.com/langchain-ai/langgraph",
    )
    assert any("langchain-ai/langgraph" in u for u in req.github_manual_urls)
    assert req.github_target_channels == []


def test_parse_github_explicit_channel_phrase() -> None:
    req = parse_digest_intent(
        "Digest github user langchain-ai and https://github.com/langchain-ai/langgraph",
    )
    assert "langchain-ai" in req.github_target_channels
    assert any("langchain-ai/langgraph" in u for u in req.github_manual_urls)


def test_parse_today_timeframe_keeps_default_topics() -> None:
    req = parse_digest_intent("Give me today's AI digest")
    assert req.timeframe == "today"
    assert len(req.topics) > 0
    assert not req.has_explicit_selectors()


def test_parse_mixed_sources() -> None:
    msg = (
        "Digest https://github.com/a/b and bilibili channel 12345 "
        "https://www.bilibili.com/video/BV1test1234"
    )
    req = parse_digest_intent(msg)
    assert req.github_manual_urls
    assert req.bilibili_target_channels == ["12345"]
    assert req.topics == []


def test_parse_topics_prefix() -> None:
    req = parse_digest_intent("digest\nTopics: RAG, agents")
    assert req.topics == ["RAG", "agents"]


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Give me today's AI digest from github only", ["github"]),
        ("bilibili only digest today", ["bilibili"]),
        ("use github and bilibili for today's digest", ["github", "bilibili"]),
        ("Give me today's AI digest", None),
    ],
)
def test_parse_connector_names_from_message(message: str, expected: list[str] | None) -> None:
    assert parse_connector_names_from_message(message) == expected
