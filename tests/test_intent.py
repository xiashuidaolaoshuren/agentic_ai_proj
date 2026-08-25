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
    assert any("daily.juya.uk" in u for u in req.juya_manual_urls)
    assert not req.github_manual_urls


def test_parse_digest_intent_rejects_legacy_juya_github_url() -> None:
    with pytest.raises(ValueError, match="daily.juya.uk"):
        parse_digest_intent("Digest https://github.com/jujuyaya/juya-ai-daily")


def test_resolve_digest_request_bare_defaults_to_juya() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Give me today's AI digest")
    assert req.connector_names == ["juya"]
    assert req.primary_source == "juya"


def test_resolve_digest_request_github_repo_url_does_not_stack_juya() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest https://github.com/acme/widget")
    assert req.connector_names == ["github"]
    assert req.primary_source == "github"
    assert "juya" not in (req.connector_names or [])


def test_resolve_digest_request_juya_website_url_routes_to_juya() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("Digest https://daily.juya.uk/")
    assert req.connector_names == ["juya"]
    assert req.primary_source == "juya"


def test_resolve_digest_request_mixed_github_bilibili_selectors_not_default() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    msg = (
        "Digest https://github.com/a/b and bilibili channel 12345 "
        "https://www.bilibili.com/video/BV1test1234"
    )
    req = resolve_digest_request(msg)
    assert req.connector_names == ["github", "bilibili"]
    assert req.primary_source == "github"


def test_resolve_digest_request_huggingface_only_replaces_juya_default() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("huggingface only")
    assert req.connector_names == ["huggingface"]
    assert req.primary_source == "huggingface"
    assert "juya" not in (req.connector_names or [])


def test_resolve_digest_request_juya_and_huggingface() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("use juya and huggingface")
    assert req.connector_names == ["juya", "huggingface"]
    assert req.primary_source == "juya"


def test_resolve_digest_request_zhihu_only() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("zhihu only")
    assert req.connector_names == ["zhihu"]
    assert req.primary_source == "zhihu"
    assert "juya" not in (req.connector_names or [])


def test_resolve_digest_request_huggingface_filtered_trending() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("trending RAG models on hugging face")
    assert req.connector_names == ["huggingface"]
    assert req.primary_source == "huggingface"
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_search == "RAG"


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
        ("juya only", ["juya"]),
        ("from juya only", ["juya"]),
        ("use juya and github", ["juya", "github"]),
        ("trending repos", ["github"]),
        ("github trending", ["github"]),
        ("huggingface only", ["huggingface"]),
        ("zhihu only", ["zhihu"]),
        ("use huggingface and zhihu", ["huggingface", "zhihu"]),
        ("use juya and huggingface", ["juya", "huggingface"]),
        ("trending models on hugging face", ["huggingface"]),
        ("huggingface trending models", ["huggingface"]),
        ("trending huggingface models", ["huggingface"]),
        ("zhihu practitioner insights", ["zhihu"]),
        ("practitioner lessons on zhihu", ["zhihu"]),
        ("zhihu trade-offs", ["zhihu"]),
    ],
)
def test_parse_connector_names_from_message(message: str, expected: list[str] | None) -> None:
    assert parse_connector_names_from_message(message) == expected


def test_parse_digest_intent_huggingface_filtered_by_topic() -> None:
    req = parse_digest_intent("trending RAG models on hugging face")
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_search == "RAG"


def test_parse_digest_intent_zhihu_practitioner_extracts_topic() -> None:
    req = parse_digest_intent("zhihu practitioner insights on RAG")
    assert req.topics == ["RAG"]


def test_parse_digest_intent_zhihu_practitioner_trailing_on_zhihu_extracts_topic() -> None:
    req = parse_digest_intent("practitioner insights on RAG on zhihu")
    assert req.topics == ["RAG"]


def test_parse_digest_intent_zhihu_practitioner_without_topic_keeps_defaults() -> None:
    from ai_news_agent.topics import DEFAULT_TOPICS

    req = parse_digest_intent("zhihu practitioner insights")
    assert list(req.topics) == list(DEFAULT_TOPICS)


def test_parse_digest_intent_zhihu_source_cue_without_real_topic_keeps_defaults() -> None:
    from ai_news_agent.topics import DEFAULT_TOPICS

    req = parse_digest_intent("practitioner insights on zhihu")
    assert list(req.topics) == list(DEFAULT_TOPICS)


def test_parse_digest_intent_huggingface_filtered_by_pipeline_tag() -> None:
    req = parse_digest_intent("huggingface models for text-generation")
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_pipeline_tag == "text-generation"


def test_resolve_digest_request_huggingface_pipeline_tag_infers_connector() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request("huggingface models for text-generation")
    assert req.connector_names == ["huggingface"]
    assert req.primary_source == "huggingface"
    assert req.huggingface_pipeline_tag == "text-generation"
    assert req.huggingface_discovery_mode == "filtered"
    assert "juya" not in (req.connector_names or [])


def test_resolve_digest_request_huggingface_pipeline_fields_override_session() -> None:
    from ai_news_agent.digest_request_builder import resolve_digest_request

    req = resolve_digest_request(
        "huggingface models for text-generation",
        session_connector_names=["github"],
    )
    assert req.connector_names == ["huggingface"]
    assert req.primary_source == "huggingface"
    assert req.huggingface_pipeline_tag == "text-generation"
    assert "github" not in (req.connector_names or [])


def test_parse_digest_intent_huggingface_global_trending_leaves_discovery_mode_none() -> None:
    req = parse_digest_intent("huggingface trending models")
    assert req.huggingface_discovery_mode is None
    assert req.huggingface_search is None
    assert req.huggingface_pipeline_tag is None


def test_digest_request_juya_manual_urls_and_primary_source() -> None:
    from ai_news_agent.request import DigestRequest

    req = DigestRequest(juya_manual_urls=["https://daily.juya.uk/"])
    assert req.has_explicit_selectors() is True
    assert req.primary_source is None

    bare = DigestRequest()
    assert bare.juya_manual_urls == []
    assert bare.primary_source is None
