"""Tests for Markdown/plain-text digest rendering (Milestone 1 Task 9)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.models import ConnectorWarning, Digest, DigestEntry, FollowUpAction, SourceKind


def _fixture_dt() -> datetime:
    return datetime(2026, 5, 13, 8, 30, 0, tzinfo=UTC)


def _sample_entry(*, with_caveat: bool) -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="repo/ai-tool",
        title='Neural nets _primer_',
        source_name="GitHub",
        source_url="https://github.com/repo/ai-tool",
        summary="A *short* summary.",
        why_it_matters="It matters [to us].",
        background_knowledge="Foundational RL.",
        follow_up_action=FollowUpAction.READ,
        confidence_caveat="Limited metadata." if with_caveat else None,
    )


def _github_entry(*, title: str = "Trending agent toolkit") -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="gh-1",
        title=title,
        source_name="GitHub",
        source_url="https://github.com/o/repo",
        summary="GH summary.",
        why_it_matters="Why GH.",
        background_knowledge="BG GH.",
        follow_up_action=FollowUpAction.READ,
    )


def _bilibili_entry(*, title: str = "New model overview") -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.BILIBILI,
        source_id="BV1",
        title=title,
        source_name="Bilibili",
        source_url="https://www.bilibili.com/video/BV1",
        summary="Bili summary.",
        why_it_matters="Why Bili.",
        background_knowledge="BG Bili.",
        follow_up_action=FollowUpAction.WATCH,
    )


def _juya_entry(*, title: str = "Juya bulletin") -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.JUYA,
        source_id="issue-2026-05-13",
        title=title,
        source_name="Juya",
        source_url="https://daily.juya.uk/2026/05/13",
        summary="Juya summary.",
        why_it_matters="Why Juya.",
        background_knowledge="BG Juya.",
        follow_up_action=FollowUpAction.READ,
    )


def _huggingface_entry(*, title: str = "Trending model") -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.HUGGINGFACE,
        source_id="hf-1",
        title=title,
        source_name="Hugging Face",
        source_url="https://huggingface.co/models/hf-1",
        summary="HF summary.",
        why_it_matters="Why HF.",
        background_knowledge="BG HF.",
        follow_up_action=FollowUpAction.TRY,
    )


def _zhihu_entry(*, title: str = "Practitioner insight") -> DigestEntry:
    return DigestEntry(
        source_kind=SourceKind.ZHIHU,
        source_id="zh-1",
        title=title,
        source_name="Zhihu",
        source_url="https://www.zhihu.com/question/1",
        summary="Zhihu summary.",
        why_it_matters="Why Zhihu.",
        background_knowledge="BG Zhihu.",
        follow_up_action=FollowUpAction.READ,
    )


def test_render_digest_markdown_mixed_sources_use_global_display_ranks() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_juya_entry(), _github_entry(), _huggingface_entry(title="HF model")],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_markdown(digest)
    assert "### 1. Juya bulletin" in out
    assert "### 2. Trending agent toolkit" in out
    assert "### 3. HF model" in out
    assert "### 1. HF model" not in out


def test_render_digest_text_mixed_sources_use_global_display_ranks() -> None:
    from ai_news_agent.rendering import render_digest_text

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_juya_entry(), _github_entry(), _huggingface_entry(title="HF model")],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_text(digest)
    assert "1. Juya bulletin" in out
    assert "2. Trending agent toolkit" in out
    assert "3. HF model" in out


def test_render_search_items_text_prefixes_display_ranks() -> None:
    from datetime import UTC, datetime

    from ai_news_agent.models import ConfidenceLevel, NewsItem
    from ai_news_agent.rendering import render_search_items_text

    items = [
        NewsItem(
            source=SourceKind.GITHUB,
            source_id="repo-1",
            url="https://github.com/o/repo-1",
            title="First repo",
            collected_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
            content_confidence=ConfidenceLevel.HIGH,
        ),
        NewsItem(
            source=SourceKind.GITHUB,
            source_id="repo-2",
            url="https://github.com/o/repo-2",
            title="Second repo",
            collected_at=datetime(2026, 5, 7, 10, 0, tzinfo=UTC),
            content_confidence=ConfidenceLevel.HIGH,
        ),
    ]
    out = render_search_items_text(items)
    assert out.startswith("1. First repo")
    assert "2. Second repo" in out


def test_render_digest_markdown_mixed_sources_use_section_headers() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_github_entry(), _bilibili_entry()],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_markdown(digest)
    assert "\n## GitHub\n" in out
    assert "\n## Bilibili\n" in out
    assert out.index("\n## GitHub\n") < out.index("\n## Bilibili\n")
    assert "### 1. Trending agent toolkit" in out
    assert "### 2. New model overview" in out


def test_render_digest_markdown_single_source_has_no_section_wrapper() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=False)],
        topics=["LLM"],
        timeframe="last_7_days",
    )
    out = render_digest_markdown(digest)
    assert "## GitHub" not in out
    assert "## 1. Neural nets \\_primer\\_" in out


def test_render_digest_markdown_mixed_huggingface_and_zhihu_section_labels() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_huggingface_entry(), _zhihu_entry()],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_markdown(digest)
    assert "\n## Hugging Face\n" in out
    assert "\n## Zhihu\n" in out
    assert out.index("\n## Hugging Face\n") < out.index("\n## Zhihu\n")


def test_render_digest_markdown_single_huggingface_has_no_section_wrapper() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_huggingface_entry()],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_markdown(digest)
    assert "## Hugging Face" not in out
    assert "## 1. Trending model" in out


def test_render_digest_editorial_juya_header_when_source_kind_juya() -> None:
    from ai_news_agent.rendering import render_digest_editorial_text

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_juya_entry()],
        topics=["AI"],
        timeframe="today",
    )
    out = render_digest_editorial_text(digest)
    assert out.startswith("橘鸦AI早报")


def test_render_digest_markdown_includes_header_metadata_and_entry_sections() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=False)],
        topics=["LLM", "Agents"],
        timeframe="last_7_days",
    )
    out = render_digest_markdown(digest)
    assert "# AI News Digest" in out
    assert f"**Generated:** {digest.generated_at.isoformat()}" in out
    assert "**Timeframe:** last_7_days" in out
    assert "**Topics:** LLM, Agents" in out
    assert "## 1. Neural nets \\_primer\\_" in out
    assert "**Source:** GitHub (`github`)" in out
    assert "**Link:** <https://github.com/repo/ai-tool>" in out
    assert "A \\*short\\* summary." in out
    assert "It matters \\[to us\\]." in out
    assert "**Background:** Foundational RL." in out
    assert "**Follow-up:** read" in out
    assert "**Confidence:**" not in out


def test_render_digest_markdown_includes_confidence_caveat_when_set() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=True)],
        topics=[],
        timeframe=None,
    )
    out = render_digest_markdown(digest)
    assert "**Confidence:** Limited metadata." in out


def test_render_digest_markdown_empty_entries() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[],
        topics=["x"],
        timeframe="today",
    )
    out = render_digest_markdown(digest)
    assert "*No entries in this digest.*" in out


def test_render_digest_text_matches_core_content_no_markdown_syntax() -> None:
    from ai_news_agent.rendering import render_digest_markdown, render_digest_text

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=True)],
        topics=["LLM"],
        timeframe="last_7_days",
    )
    md = render_digest_markdown(digest)
    text = render_digest_text(digest)

    assert "#" not in text
    assert "\\" not in text
    assert "AI News Digest" in text
    assert digest.generated_at.isoformat() in text
    assert "Timeframe: last_7_days" in text
    assert "Topics: LLM" in text
    assert "Neural nets _primer_" in text
    assert "GitHub" in text and "github" in text
    assert "https://github.com/repo/ai-tool" in text
    assert "A *short* summary." in text
    assert "It matters [to us]." in text
    assert "Follow-up: read" in text
    assert "Confidence: Limited metadata." in text

    assert "##" in md
    assert "\\" in md


def test_render_digest_text_empty_entries() -> None:
    from ai_news_agent.rendering import render_digest_text

    digest = Digest(generated_at=_fixture_dt(), entries=[], topics=[], timeframe=None)
    text = render_digest_text(digest)
    assert "No entries in this digest." in text


def test_format_connector_warnings_notice_empty_warning_banner() -> None:
    from ai_news_agent.rendering import format_connector_warnings_notice

    assert format_connector_warnings_notice([], []) == ""


def test_render_digest_text_warning_banner_unchanged_without_warnings() -> None:
    from ai_news_agent.rendering import render_digest_text

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=False)],
        topics=["LLM"],
        timeframe="last_7_days",
    )
    baseline = render_digest_text(digest)
    with_notice = render_digest_text(digest, warnings=[])
    assert with_notice == baseline
    assert "BILIBILI_SESSDATA" not in with_notice


def test_render_digest_text_includes_anti_bot_warning_banner() -> None:
    from ai_news_agent.rendering import render_digest_text

    warning = ConnectorWarning(
        connector="bilibili",
        code="anti_bot_blocked",
        message=(
            "Bilibili keyword search blocked (anti-bot). "
            "Set BILIBILI_SESSDATA, BILIBILI_BILI_JCT, and BILIBILI_BUVID3 "
            "in .env, or use video URLs/channels."
        ),
    )
    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=False)],
        topics=["AI"],
        timeframe="last_7_days",
    )
    out = render_digest_text(digest, warnings=[warning])
    assert out.startswith("⚠")
    assert "BILIBILI_SESSDATA" in out
    assert "AI News Digest" in out
    assert out.index("BILIBILI_SESSDATA") < out.index("AI News Digest")


def test_render_digest_markdown_skips_optional_header_lines_when_absent() -> None:
    from ai_news_agent.rendering import render_digest_markdown

    digest = Digest(
        generated_at=_fixture_dt(),
        entries=[_sample_entry(with_caveat=False)],
        topics=[],
        timeframe=None,
    )
    out = render_digest_markdown(digest)
    assert "**Timeframe:**" not in out
    assert "**Topics:**" not in out
