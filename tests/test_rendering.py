"""Tests for Markdown/plain-text digest rendering (Milestone 1 Task 9)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_news_agent.models import Digest, DigestEntry, FollowUpAction, SourceKind


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
    assert "## Neural nets \\_primer\\_" in out
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
