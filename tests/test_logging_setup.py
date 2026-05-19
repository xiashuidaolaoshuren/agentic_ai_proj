"""Tests for centralized logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from ai_news_agent.logging_setup import configure_logging, get_logger, reset_logging_for_tests


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    reset_logging_for_tests()
    yield
    reset_logging_for_tests()


def test_configure_logging_creates_console_and_file_handlers(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    log_file = tmp_path / "logs" / "test.log"
    monkeypatch.setenv("AI_NEWS_AGENT_LOG_PATH", str(log_file))
    monkeypatch.setenv("AI_NEWS_AGENT_LOG_LEVEL", "DEBUG")

    logger = configure_logging()
    logger.info("hello from test")

    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "hello from test" in content
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    assert any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def test_configure_logging_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_NEWS_AGENT_LOG_PATH", str(tmp_path / "logs" / "once.log"))

    logger1 = configure_logging()
    n1 = len(logger1.handlers)
    logger2 = configure_logging()
    assert logger1 is logger2
    assert len(logger2.handlers) == n1


def test_get_logger_child_name() -> None:
    configure_logging()
    child = get_logger("chat")
    assert child.name == "ai_news_agent.chat"


def test_gradio_respond_returns_friendly_message_on_exception(tmp_path) -> None:
    import asyncio

    from ai_news_agent.app.gradio_app import _UI_ERROR_MESSAGE, create_app
    from ai_news_agent.chat import ChatService
    from ai_news_agent.graph.state import DigestResult
    from ai_news_agent.request import DigestRequest
    from ai_news_agent.storage import DigestStore

    async def boom(_: DigestRequest) -> DigestResult:
        raise RuntimeError("simulated failure")

    store = DigestStore(tmp_path / "g.db")
    store.init_schema()
    configure_logging()
    svc = ChatService(store=store, workflow_runner=boom)
    create_app(svc)

    async def call_respond() -> str:
        try:
            return await svc.handle_message_async("Give me today's AI digest")
        except Exception:
            get_logger("gradio").exception("gradio request failed")
            return _UI_ERROR_MESSAGE

    reply = asyncio.run(call_respond())
    assert reply == _UI_ERROR_MESSAGE
    assert "simulated failure" not in reply
