"""Streaming helpers for Gradio and chat UI."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


async def iter_text_chunks(
    text: str,
    *,
    chunk_size: int = 80,
    delay_s: float = 0.02,
) -> AsyncIterator[str]:
    """Yield cumulative slices of ``text`` for progressive UI display."""
    if not text:
        yield ""
        return

    end = chunk_size
    while end < len(text):
        yield text[:end]
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        end += chunk_size
    yield text


__all__ = ["iter_text_chunks"]
