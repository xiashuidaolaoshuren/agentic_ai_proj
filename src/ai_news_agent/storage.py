"""Compatibility re-export for DigestStore (8A.1 T1)."""

from ai_news_agent.repositories.digest_store import (
    SCHEMA_VERSION,
    DigestStore,
    FollowupContext,
)

__all__ = ["SCHEMA_VERSION", "DigestStore", "FollowupContext"]
