"""Shared live progress sink for tool agents and digest workflow nodes."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token

_progress_sink: ContextVar[Callable[[str], None] | None] = ContextVar(
    "_progress_sink",
    default=None,
)


def emit_progress(line: str) -> None:
    """Emit a live progress line when a tool-bound progress sink is active."""
    sink = _progress_sink.get()
    if sink is not None:
        sink(line)


def bind_progress_sink(sink: Callable[[str], None]) -> Token[Callable[[str], None] | None]:
    return _progress_sink.set(sink)


def reset_progress_sink(token: Token[Callable[[str], None] | None]) -> None:
    _progress_sink.reset(token)
