"""Tests for streaming text helpers."""

from __future__ import annotations

import asyncio

from ai_news_agent.streaming import iter_text_chunks


def test_iter_text_chunks_yields_cumulative_slices() -> None:
    chunks = asyncio.run(_collect("abcdef", chunk_size=2, delay_s=0))
    assert chunks == ["ab", "abcd", "abcdef"]


def test_iter_text_chunks_empty_string_yields_blank_once() -> None:
    chunks = asyncio.run(_collect("", chunk_size=10, delay_s=0))
    assert chunks == [""]


async def _collect(text: str, *, chunk_size: int, delay_s: float) -> list[str]:
    out: list[str] = []
    async for chunk in iter_text_chunks(text, chunk_size=chunk_size, delay_s=delay_s):
        out.append(chunk)
    return out
