"""Opt-in live tests against the real Bilibili API (network required).

Run::

    RUN_LIVE_BILIBILI=1 uv run pytest -m live tests/test_connectors_bilibili_live.py -q

Loads ``.env`` so ``BILIBILI_SESSDATA``, ``BILIBILI_BILI_JCT``, and ``BILIBILI_BUVID3`` apply when set.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from ai_news_agent.connectors.base import ConnectorRequest
from ai_news_agent.connectors.bilibili import BilibiliConnector, extract_bvid
from ai_news_agent.env import load_local_env
from ai_news_agent.models import SourceKind

# Stable public video used as a live smoke target (metadata may change over time).
LIVE_BV_ID = "BV1LoLK6pEXE"
LIVE_VIDEO_URL = (
    "https://www.bilibili.com/video/BV1LoLK6pEXE/"
    "?spm_id_from=333.337.search-card.all.click"
    "&vd_source=96537af7a0f5bcc39751e573c2e27da4"
)


def _live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_BILIBILI", "").strip() in ("1", "true", "yes")


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _live_enabled(),
        reason="Set RUN_LIVE_BILIBILI=1 to run live Bilibili connector tests",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def _load_env_once() -> None:
    load_local_env()


def test_extract_bvid_from_full_tracking_url() -> None:
    assert extract_bvid(LIVE_VIDEO_URL) == LIVE_BV_ID


def test_live_manual_url_fetches_video_metadata() -> None:
    async def main() -> None:
        conn = BilibiliConnector()
        try:
            out = await conn.collect(
                ConnectorRequest(
                    topics=[],
                    bilibili_manual_urls=[LIVE_VIDEO_URL],
                    max_items=5,
                ),
            )
        finally:
            await conn.aclose()

        assert not any(w.code == "anti_bot_blocked" for w in out.warnings), out.warnings
        assert not any(w.code == "view_fetch_failed" for w in out.warnings), out.warnings
        assert len(out.items) == 1, out.warnings

        item = out.items[0]
        assert item.source is SourceKind.BILIBILI
        assert item.source_id == LIVE_BV_ID
        assert item.url == f"https://www.bilibili.com/video/{LIVE_BV_ID}"
        assert item.title.strip()
        assert item.collected_at is not None

    asyncio.run(main())
