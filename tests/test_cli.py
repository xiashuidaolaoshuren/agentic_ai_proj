"""CLI smoke tests (Task T12)."""

from __future__ import annotations

import io
from argparse import Namespace

import pytest

from datetime import UTC, datetime

from ai_news_agent.cli import (
    _pick_connector_names,
    build_arg_parser,
    build_digest_request,
    main,
)
from ai_news_agent.connectors.base import ConnectorResult
from ai_news_agent.followup_structured import NO_SAVED_DIGEST
from ai_news_agent.models import (
    ConfidenceLevel,
    Digest,
    DigestEntry,
    FollowUpAction,
    NewsItem,
    RankedItem,
    SourceKind,
)
from ai_news_agent.storage import DigestStore
from ai_news_agent import topics

_FIXTURE_DT = datetime(2026, 8, 2, 12, 0, 0, tzinfo=UTC)


def _seed_github_digest(store: DigestStore) -> int:
    item = NewsItem(
        source=SourceKind.GITHUB,
        source_id="repo-1",
        url="https://github.com/a/b",
        title="a/b",
        collected_at=_FIXTURE_DT,
        content_confidence=ConfidenceLevel.HIGH,
    )
    entry = DigestEntry(
        source_kind=SourceKind.GITHUB,
        source_id="repo-1",
        title="a/b",
        source_name="GitHub",
        source_url=item.url,
        summary="Summary about transformers",
        why_it_matters="Why",
        background_knowledge="Background",
        follow_up_action=FollowUpAction.READ,
    )
    run_id = store.save_run(
        requested_at=_FIXTURE_DT,
        timeframe="today",
        topics=["RAG"],
        connector_names=["github"],
    )
    store.save_connector_result(run_id, ConnectorResult(items=[item], warnings=[]))
    store.save_ranked_items(
        run_id,
        [RankedItem(item=item, score_total=1.0, selected=True, selection_reason="best")],
    )
    return store.save_digest(
        run_id,
        Digest(
            generated_at=_FIXTURE_DT,
            entries=[entry],
            topics=["RAG"],
            timeframe="today",
        ),
    )


def test_build_digest_request_maps_flags() -> None:
    ns = Namespace(
        timeframe="today",
        topics="RAG, agents",
        sources="github,bilibili",
        top_n=3,
        max_items=7,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.timeframe == "today"
    assert req.topics == ["RAG", "agents"]
    assert req.connector_names == ["github", "bilibili"]
    assert req.top_n == 3
    assert req.max_items_per_source == 7


def test_build_digest_request_sets_primary_source_from_sources() -> None:
    ns = Namespace(
        timeframe="today",
        topics=None,
        sources="github,juya",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.connector_names == ["github", "juya"]
    assert req.primary_source == "github"


def test_build_digest_request_default_topics_when_omitted() -> None:
    ns = Namespace(
        timeframe=None,
        topics=None,
        sources="github",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.topics == list(topics.DEFAULT_TOPICS)
    assert req.connector_names == ["github"]


def test_full_argv_parsing_round_trip(tmp_path) -> None:
    argv = [
        "digest",
        "--fake",
        "--db-path",
        str(tmp_path / "cli.db"),
        "--sources",
        "github",
        "--topics",
        "RAG",
        "--timeframe",
        "today",
    ]
    ns = build_arg_parser().parse_args(argv)
    req = build_digest_request(ns)
    assert ns.fake is True
    assert req.topics == ["RAG"]
    assert req.timeframe == "today"
    assert req.connector_names == ["github"]


def test_cli_digest_fake_exits_zero_and_prints_digest(tmp_path) -> None:
    buf = io.StringIO()
    code = main(
        [
            "digest",
            "--fake",
            "--db-path",
            str(tmp_path / "x.db"),
            "--sources",
            "github",
            "--topics",
            "RAG",
        ],
        stdout=buf,
    )
    out = buf.getvalue()
    assert code == 0
    assert "AI News Digest" in out
    assert "Fake GitHub repo" in out


def test_cli_rejects_unknown_connector_name(tmp_path) -> None:
    buf = io.StringIO()
    code = main(
        [
            "digest",
            "--fake",
            "--db-path",
            str(tmp_path / "y.db"),
            "--sources",
            "arxiv",
        ],
        stdout=buf,
    )
    assert code == 2
    assert buf.getvalue() == ""


def test_cli_run_digest_failure_returns_nonzero(monkeypatch, tmp_path, capsys) -> None:
    async def boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr("ai_news_agent.cli.run_digest", boom)
    buf = io.StringIO()
    code = main(
        [
            "digest",
            "--fake",
            "--db-path",
            str(tmp_path / "z.db"),
            "--sources",
            "github",
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 1
    assert buf.getvalue() == ""
    assert "boom" in err


def test_build_digest_request_unknown_sources_raises() -> None:
    ns = Namespace(
        timeframe=None,
        topics="RAG",
        sources="github,unknown",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    with pytest.raises(ValueError, match="Unknown source"):
        build_digest_request(ns)


def test_e2e_live_requires_openai_or_exits(monkeypatch, tmp_path, capsys) -> None:
    """Live mode calls build_chat_model; without key it should exit before network."""

    def no_key(**_kwargs):
        raise ValueError("OPENAI_API_KEY is not set and no api_key was provided")

    monkeypatch.setattr("ai_news_agent.cli.build_chat_model", no_key)
    buf = io.StringIO()
    code = main(
        [
            "digest",
            "--db-path",
            str(tmp_path / "live.db"),
            "--sources",
            "github",
            "--topics",
            "RAG",
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "OPENAI_API_KEY" in err


def test_cli_digest_defaults_to_juya_when_sources_omitted(capsys) -> None:
    """Omitting --sources resolves to juya-only (DEFAULT_SOURCE_NAMES)."""
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["digest", "--help"])
    help_text = capsys.readouterr().out
    ns = build_arg_parser().parse_args(["digest"])
    req = build_digest_request(ns)
    assert req.connector_names == ["juya"]
    assert _pick_connector_names(ns) == ["juya"]
    assert "juya" in help_text
    assert "huggingface" in help_text
    assert "zhihu" in help_text


def test_build_digest_request_accepts_huggingface_source() -> None:
    ns = Namespace(
        timeframe=None,
        topics=None,
        sources="huggingface",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.connector_names == ["huggingface"]
    assert req.primary_source == "huggingface"


def test_build_digest_request_maps_topics_to_huggingface_filtered() -> None:
    ns = Namespace(
        timeframe=None,
        topics="RAG,agents",
        sources="huggingface",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.topics == ["RAG", "agents"]
    assert req.huggingface_discovery_mode == "filtered"
    assert req.huggingface_search == "RAG"


def test_build_digest_request_huggingface_global_when_topics_omitted() -> None:
    ns = Namespace(
        timeframe=None,
        topics=None,
        sources="huggingface",
        top_n=None,
        max_items=None,
        db_path=None,
        fake=False,
    )
    req = build_digest_request(ns)
    assert req.huggingface_discovery_mode is None
    assert req.huggingface_search is None


def test_history_search_parser_accepts_spec_flags() -> None:
    ns = build_arg_parser().parse_args(["history-search", "--query", "rag"])
    assert ns.command == "history-search"
    assert ns.query == "rag"

    show_ns = build_arg_parser().parse_args(["history-show", "d12:r3"])
    assert show_ns.command == "history-show"
    assert show_ns.token == "d12:r3"


def test_history_search_empty_archive_exits_zero(tmp_path) -> None:
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "hist.db"),
            "--sources",
            "github",
        ],
        stdout=buf,
    )
    assert code == 0
    assert "No saved digests to search." in buf.getvalue()


def test_history_search_prints_chrome_for_match(tmp_path) -> None:
    store = DigestStore(tmp_path / "search-hit.db")
    store.init_schema()
    digest_id = _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "search-hit.db"),
            "--query",
            "transformer",
        ],
        stdout=buf,
    )
    out = buf.getvalue()
    assert code == 0
    assert f"d{digest_id}:r1" in out
    assert "a/b" in out
    assert "https://github.com/a/b" in out


def test_history_search_zero_matches_exits_zero_with_caveat(tmp_path) -> None:
    store = DigestStore(tmp_path / "search-miss.db")
    store.init_schema()
    _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "search-miss.db"),
            "--query",
            "nonexistentqueryterm",
        ],
        stdout=buf,
    )
    out = buf.getvalue()
    assert code == 0
    assert "No saved digests to search." not in out
    assert "Try broadening one criterion." in out


def test_history_search_rejects_no_criteria(tmp_path, capsys) -> None:
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "bad.db"),
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "at least one search criterion" in err
    assert NO_SAVED_DIGEST not in err


def test_history_search_rejects_unknown_source(tmp_path, capsys) -> None:
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "bad-source.db"),
            "--sources",
            "arxiv",
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "Unknown source" in err
    assert NO_SAVED_DIGEST not in err


def test_history_search_rejects_since_after_until(tmp_path, capsys) -> None:
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "bad-range.db"),
            "--since",
            "2026-08-03",
            "--until",
            "2026-08-01",
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "since must not be after until" in err
    assert NO_SAVED_DIGEST not in err


def test_history_show_prints_persist_only_card(tmp_path) -> None:
    store = DigestStore(tmp_path / "show-hit.db")
    store.init_schema()
    digest_id = _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-show",
            f"d{digest_id}:r1",
            "--db-path",
            str(tmp_path / "show-hit.db"),
        ],
        stdout=buf,
    )
    out = buf.getvalue()
    assert code == 0
    assert out.startswith("Digest item 1: a/b")


def test_history_show_not_found_bad_token(tmp_path, capsys) -> None:
    store = DigestStore(tmp_path / "show-bad.db")
    store.init_schema()
    _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-show",
            "bad-token",
            "--db-path",
            str(tmp_path / "show-bad.db"),
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "not found" in err
    assert buf.getvalue() == ""


def test_history_show_not_found_missing_digest(tmp_path, capsys) -> None:
    store = DigestStore(tmp_path / "show-missing.db")
    store.init_schema()
    _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-show",
            "d9999:r1",
            "--db-path",
            str(tmp_path / "show-missing.db"),
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "not found" in err


def test_history_search_store_failure_returns_one(monkeypatch, tmp_path, capsys) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("store boom")

    monkeypatch.setattr("ai_news_agent.cli.search_digest_history", boom)
    store = DigestStore(tmp_path / "fail-search.db")
    store.init_schema()
    _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-search",
            "--db-path",
            str(tmp_path / "fail-search.db"),
            "--query",
            "transformer",
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "store boom" in err
    assert buf.getvalue() == ""


def test_history_show_store_failure_returns_one(monkeypatch, tmp_path, capsys) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("show boom")

    monkeypatch.setattr("ai_news_agent.cli.show_historical_item", boom)
    store = DigestStore(tmp_path / "fail-show.db")
    store.init_schema()
    digest_id = _seed_github_digest(store)
    buf = io.StringIO()
    code = main(
        [
            "history-show",
            f"d{digest_id}:r1",
            "--db-path",
            str(tmp_path / "fail-show.db"),
        ],
        stdout=buf,
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "show boom" in err
