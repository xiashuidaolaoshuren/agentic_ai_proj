"""Correlation IDs and per-stage digest timing helpers."""

from __future__ import annotations

import time
import uuid
from typing import Any

from ai_news_agent.logging_setup import get_logger

_DEFAULT_LOGGER = "telemetry"


def new_correlation_id() -> str:
    """Return a new opaque correlation id for one digest request."""
    return uuid.uuid4().hex


class DigestStageTimer:
    """Record monotonic stage marks and emit a summary log line on exit."""

    def __init__(
        self,
        correlation_id: str,
        *,
        logger_name: str = _DEFAULT_LOGGER,
    ) -> None:
        self.correlation_id = correlation_id
        self._logger = get_logger(logger_name)
        self._started = time.perf_counter()
        self._last = self._started
        self.stages: dict[str, float] = {}

    def __enter__(self) -> DigestStageTimer:
        self._logger.info(
            "digest_request_start correlation_id=%s",
            self.correlation_id,
        )
        return self

    def __exit__(self, *_exc: object) -> None:
        total = time.perf_counter() - self._started
        self._logger.info(
            "digest_stages_complete correlation_id=%s total_s=%.3f stages=%s",
            self.correlation_id,
            total,
            _format_stages(self.stages),
        )

    def mark(self, stage: str) -> None:
        """Record elapsed time since the previous mark for ``stage``."""
        now = time.perf_counter()
        elapsed = now - self._last
        self._last = now
        self.stages[stage] = round(elapsed, 4)
        self._logger.info(
            "digest_stage correlation_id=%s stage=%s elapsed_s=%.3f",
            self.correlation_id,
            stage,
            elapsed,
        )


def _format_stages(stages: dict[str, float]) -> str:
    if not stages:
        return "{}"
    parts = [f"{name}={secs:.3f}s" for name, secs in stages.items()]
    return "{" + ", ".join(parts) + "}"


__all__ = ["DigestStageTimer", "new_correlation_id"]
