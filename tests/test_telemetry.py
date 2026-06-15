"""Tests for digest correlation-id and stage timing helpers."""

from __future__ import annotations

from ai_news_agent.telemetry import DigestStageTimer, new_correlation_id


def test_new_correlation_id_returns_nonempty_uuid_like_string() -> None:
    cid = new_correlation_id()
    assert isinstance(cid, str)
    assert len(cid) >= 8
    assert cid != new_correlation_id()


def test_digest_stage_timer_logs_stages() -> None:
    with DigestStageTimer("corr-test", logger_name="telemetry") as timer:
        timer.mark("collect")
        timer.mark("summarize")
    assert "collect" in timer.stages
    assert "summarize" in timer.stages
    assert timer.stages["collect"] >= 0
