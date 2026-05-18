"""CLI smoke tests (Task T12)."""

from __future__ import annotations

import io
from argparse import Namespace

import pytest

from ai_news_agent.cli import build_arg_parser, build_digest_request, main
from ai_news_agent import topics


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
    assert "CLI fake repo" in out


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
    with pytest.raises(ValueError, match="Unknown --sources"):
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