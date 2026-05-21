"""Tests for local .env loading (CLI / Gradio startup)."""

from __future__ import annotations

import io
import os

import pytest

from ai_news_agent import env
from ai_news_agent.env import load_local_env


@pytest.fixture(autouse=True)
def _reset_env_loader() -> None:
    env._reset_loaded_state_for_testing()
    yield
    env._reset_loaded_state_for_testing()


def test_load_local_env_reads_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")

    assert load_local_env() is True
    assert os.environ.get("OPENAI_API_KEY") == "sk-from-dotenv"


def test_load_local_env_does_not_override_shell(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shell")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-from-dotenv\n", encoding="utf-8")

    load_local_env()
    assert os.environ.get("OPENAI_API_KEY") == "sk-shell"


def test_load_local_env_explicit_path(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    dotenv_file = tmp_path / "secrets.env"
    dotenv_file.write_text("GITHUB_TOKEN=gh-test\n", encoding="utf-8")

    assert load_local_env(dotenv_path=dotenv_file) is True
    assert os.environ.get("GITHUB_TOKEN") == "gh-test"


def test_get_bilibili_credential_returns_none_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("BILIBILI_SESSDATA", raising=False)
    monkeypatch.delenv("BILIBILI_BILI_JCT", raising=False)
    monkeypatch.delenv("BILIBILI_BUVID3", raising=False)

    assert env.get_bilibili_credential() is None


def test_get_bilibili_credential_from_separate_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("BILIBILI_SESSDATA", "sess-abc")
    monkeypatch.setenv("BILIBILI_BILI_JCT", "jct-xyz")
    monkeypatch.setenv("BILIBILI_BUVID3", "buvid3-123")

    cred = env.get_bilibili_credential()
    assert cred is not None
    assert cred.sessdata == "sess-abc"
    assert cred.bili_jct == "jct-xyz"
    assert cred.buvid3 == "buvid3-123"


def test_cli_live_uses_dotenv_before_build_chat_model(
    tmp_path, monkeypatch, capsys
) -> None:
    """CLI should load .env so live mode passes key check when only file has it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-cli-dotenv\n", encoding="utf-8")

    called: list[bool] = []

    def fake_build(**_kwargs):
        called.append(True)
        from ai_news_agent.cli import _FakeDigestModel

        return _FakeDigestModel()

    monkeypatch.setattr("ai_news_agent.cli.build_chat_model", fake_build)
    async def fake_run(*_a, **_k):
        return _FakeDigestRunResult()

    monkeypatch.setattr("ai_news_agent.cli._run_digest_async", fake_run)

    from ai_news_agent.cli import main

    buf = io.StringIO()
    code = main(
        [
            "digest",
            "--db-path",
            str(tmp_path / "cli.db"),
            "--sources",
            "github",
            "--topics",
            "RAG",
        ],
        stdout=buf,
    )
    assert code == 0
    assert called
    assert "OPENAI_API_KEY" not in capsys.readouterr().err


def test_gradio_build_service_live_with_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-gradio-dotenv\n", encoding="utf-8")

    load_local_env()

    from ai_news_agent.app.gradio_app import _build_service

    service = _build_service(fake=False, db_path=tmp_path / "gradio.db")
    assert service is not None


class _FakeDigestRunResult:
    text = "ok\n"
    run_id = 1
    warnings: list = []
    errors: list = []
