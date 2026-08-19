"""Canonical source registry and connector factory for CLI, Gradio, and future adapters."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from ai_news_agent.connectors.base import ConnectorResult, SourceConnector
from ai_news_agent.connectors.bilibili import BilibiliConnector
from ai_news_agent.connectors.github import GitHubConnector
from ai_news_agent.connectors.huggingface import HuggingFaceConnector
from ai_news_agent.connectors.juya import JuyaConnector
from ai_news_agent.connectors.zhihu import ZhihuConnector
from ai_news_agent.models import NewsItem, SourceKind

ALLOWED_SOURCES: frozenset[str] = frozenset(
    {"juya", "github", "bilibili", "huggingface", "zhihu"}
)
DEFAULT_SOURCE_NAMES: tuple[str, ...] = ("juya",)


class FakeDigestModel:
    """Matches summarizer contract: ``generate_entry_fields``."""

    def generate_entry_fields(self, context: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG002
        return {
            "summary": "Fake summary",
            "why_it_matters": "Because tests need it",
            "background_knowledge": "N/A",
            "follow_up_action": "read",
        }


class FakeGitHubConnector:
    """Deterministic offline stand-in for GitHub."""

    def name(self) -> str:
        return "github"

    async def collect(self, request) -> ConnectorResult:  # noqa: ANN001
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
        item = NewsItem(
            source=SourceKind.GITHUB,
            source_id="fake-github-1",
            url="https://example.com/fake-github",
            title="Fake GitHub repo",
            collected_at=now,
        )
        return ConnectorResult(items=[item], warnings=[], raw_count=1)


class FakeBilibiliConnector:
    """Deterministic offline stand-in for Bilibili."""

    def name(self) -> str:
        return "bilibili"

    async def collect(self, request) -> ConnectorResult:  # noqa: ANN001
        return ConnectorResult(items=[], warnings=[], raw_count=0)


class FakeJuyaConnector:
    """Deterministic offline stand-in for Juya."""

    def name(self) -> str:
        return "juya"

    async def collect(self, request) -> ConnectorResult:  # noqa: ANN001
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
        item = NewsItem(
            source=SourceKind.JUYA,
            source_id="fake-juya-1",
            url="https://daily.juya.uk/fake-juya",
            title="Fake Juya bulletin",
            collected_at=now,
        )
        return ConnectorResult(items=[item], warnings=[], raw_count=1)


class FakeHuggingFaceConnector:
    """Deterministic offline stand-in for Hugging Face."""

    def name(self) -> str:
        return "huggingface"

    async def collect(self, request) -> ConnectorResult:  # noqa: ANN001
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
        item = NewsItem(
            source=SourceKind.HUGGINGFACE,
            source_id="fake-huggingface-1",
            url="https://huggingface.co/fake-model",
            title="Fake Hugging Face model",
            collected_at=now,
        )
        return ConnectorResult(items=[item], warnings=[], raw_count=1)


class FakeZhihuConnector:
    """Deterministic offline stand-in for Zhihu."""

    def name(self) -> str:
        return "zhihu"

    async def collect(self, request) -> ConnectorResult:  # noqa: ANN001
        now = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
        item = NewsItem(
            source=SourceKind.ZHIHU,
            source_id="fake-zhihu-1",
            url="https://www.zhihu.com/question/fake-zhihu",
            title="Fake Zhihu insight",
            collected_at=now,
        )
        return ConnectorResult(items=[item], warnings=[], raw_count=1)


def parse_sources_csv(value: str | None) -> list[str]:
    if value is None or value.strip() == "":
        return []
    return [part.strip().lower() for part in value.split(",") if part.strip()]


def normalize_source_names(names: Sequence[str]) -> list[str]:
    """Validate and dedupe source names, preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw).strip().lower()
        if not name:
            continue
        if name not in ALLOWED_SOURCES:
            raise ValueError(
                f"Unknown source {name!r}; allowed: {', '.join(sorted(ALLOWED_SOURCES))}"
            )
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    if not out:
        raise ValueError("At least one source must be selected")
    return out


def build_connectors(*, fake: bool, names: Sequence[str]) -> list[SourceConnector]:
    """Return ordered connectors matching ``names``."""
    selected = normalize_source_names(names)
    if fake:
        factories: dict[str, SourceConnector] = {
            "juya": FakeJuyaConnector(),
            "github": FakeGitHubConnector(),
            "bilibili": FakeBilibiliConnector(),
            "huggingface": FakeHuggingFaceConnector(),
            "zhihu": FakeZhihuConnector(),
        }
    else:
        factories = {
            "juya": JuyaConnector(),
            "github": GitHubConnector(),
            "bilibili": BilibiliConnector(),
            "huggingface": HuggingFaceConnector(),
            "zhihu": ZhihuConnector(),
        }
    return [factories[name] for name in selected]


def resolve_connector_names(connector_names: list[str] | None) -> list[str]:
    if connector_names is None:
        return list(DEFAULT_SOURCE_NAMES)
    return list(connector_names)


def build_connector_factory(*, fake: bool, name: str) -> Callable[[], SourceConnector]:
    """Return a zero-arg factory that builds a fresh connector per call."""
    validated = normalize_source_names([name])[0]

    def _factory() -> SourceConnector:
        return build_connectors(fake=fake, names=[validated])[0]

    return _factory


__all__ = [
    "ALLOWED_SOURCES",
    "DEFAULT_SOURCE_NAMES",
    "FakeBilibiliConnector",
    "FakeDigestModel",
    "FakeGitHubConnector",
    "FakeHuggingFaceConnector",
    "FakeJuyaConnector",
    "FakeZhihuConnector",
    "build_connector_factory",
    "build_connectors",
    "normalize_source_names",
    "parse_sources_csv",
    "resolve_connector_names",
]
