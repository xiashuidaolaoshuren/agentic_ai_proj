"""Tests for the persistent local digest HTTP service."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ai_news_agent.app import digest_service
from ai_news_agent.app.digest_service import (
    DigestServiceRuntime,
    DigestServiceServer,
    build_digest_request_payload,
)
from ai_news_agent.request import DigestRequest
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
)


class _FakeInterfaceRouter:
    def __init__(
        self,
        *,
        result: InterfaceAgentResult | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._result = result or InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="unused",
        )

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage=None,
    ) -> InterfaceAgentResult:
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "session_connector_names": session_connector_names,
                "correlation_id": correlation_id,
                "on_stage": on_stage,
            }
        )
        return self._result


class _OnStageInvokingRouter:
    """Simulates agent-success digest by invoking on_stage without workflow_runner."""

    def __init__(
        self,
        *,
        result: InterfaceAgentResult | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._result = result or InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="digest body",
            run_id=7,
        )

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage=None,
    ) -> InterfaceAgentResult:
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "correlation_id": correlation_id,
                "on_stage": on_stage,
            }
        )
        if on_stage is not None:
            on_stage("parse_request")
            on_stage("collect_sources")
        return self._result


class _WorkflowInvokingRouter:
    """Simulates deterministic digest fallback by calling the runtime workflow runner."""

    def __init__(self, runtime: DigestServiceRuntime) -> None:
        self._runtime = runtime
        self.calls: list[dict[str, object]] = []

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage=None,
    ) -> InterfaceAgentResult:
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "correlation_id": correlation_id,
                "on_stage": on_stage,
            }
        )
        assert digest_request is not None
        digest_result = await self._runtime._workflow_runner(digest_request, on_stage=on_stage)
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text=digest_result.text,
            run_id=digest_result.run_id,
            digest=digest_result.digest,
        )


class _ConcurrentOverwriteRouter:
    """Simulates fallback while another request overwrites runtime._active_on_stage."""

    def __init__(self, runtime: DigestServiceRuntime) -> None:
        self._runtime = runtime
        self.calls: list[dict[str, object]] = []

    async def route(
        self,
        *,
        message: str,
        digest_request: DigestRequest | None = None,
        session_connector_names: list[str] | None = None,
        correlation_id: str | None = None,
        on_stage=None,
    ) -> InterfaceAgentResult:
        self.calls.append(
            {
                "message": message,
                "digest_request": digest_request,
                "correlation_id": correlation_id,
                "on_stage": on_stage,
            }
        )
        assert digest_request is not None
        if on_stage is not None and hasattr(self._runtime, "_active_on_stage"):
            self._runtime._active_on_stage = lambda stage: on_stage(f"stale_{stage}")
        digest_result = await self._runtime._workflow_runner(digest_request, on_stage=on_stage)
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text=digest_result.text,
            run_id=digest_result.run_id,
            digest=digest_result.digest,
        )


def test_build_digest_request_payload_maps_hints() -> None:
    payload = build_digest_request_payload(
        timeframe_hint="week",
        sources_hint="github",
        topics_hint="RAG, agents",
    )
    assert payload["timeframe"] == "last_7_days"
    assert payload["sources"] == "github"
    assert payload["topics"] == ["RAG", "agents"]


def test_build_digest_request_payload_omits_topics_when_absent() -> None:
    payload = build_digest_request_payload()
    assert payload["timeframe"] == "today"
    assert payload["sources"] == "github,bilibili"
    assert "topics" not in payload


@pytest.fixture
def service_server(tmp_path: Path) -> DigestServiceServer:
    server = DigestServiceServer(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "svc.db",
        fake=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while server.port is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.port is not None
    yield server
    server.shutdown()


def test_health_endpoint_returns_ok(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    assert resp.status == 200
    body = json.loads(resp.read().decode())
    assert body["status"] == "ok"
    assert body["fake"] is True


def test_digest_endpoint_returns_markdown_text(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=30)
    body = json.dumps(
        {
            "timeframe": "today",
            "sources": "github",
            "fake": True,
            "correlation_id": "test-corr-1",
        }
    )
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode())
    assert data["correlation_id"] == "test-corr-1"
    assert "AI News Digest" in data["text"]
    assert "Fake GitHub repo" in data["text"]
    assert isinstance(data["elapsed_s"], float)
    assert data["elapsed_s"] >= 0
    assert "stages" in data


def test_digest_service_runtime_live_builds_interface_tool_router(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router_calls: list[dict[str, object]] = []
    fake_router = MagicMock(name="InterfaceToolRouter")

    def spy_build_interface_tool_router(**kwargs: object) -> MagicMock:
        router_calls.append(kwargs)
        return fake_router

    monkeypatch.setattr(digest_service, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        digest_service,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_interface_tool_router",
        spy_build_interface_tool_router,
        raising=False,
    )

    runtime = DigestServiceRuntime(fake=False, db_path=tmp_path / "live-router.db")

    assert len(router_calls) == 1
    assert router_calls[0]["interface_name"] == "openclaw"
    assert router_calls[0]["tool_model"] is not None
    assert router_calls[0]["digest_model"] is not None
    assert callable(router_calls[0]["build_connectors_fn"])
    assert callable(router_calls[0]["workflow_runner"])
    assert router_calls[0]["streaming_workflow_runner"] is None
    assert runtime._interface_router is fake_router


def test_digest_service_runtime_fake_mode_has_no_interface_router(tmp_path: Path) -> None:
    runtime = DigestServiceRuntime(fake=True, db_path=tmp_path / "fake-router.db")
    assert runtime._interface_router is None


@pytest.fixture
def live_service_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> DigestServiceServer:
    monkeypatch.setattr(digest_service, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        digest_service,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    router = _FakeInterfaceRouter(
        result=InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="digest body",
            run_id=7,
        )
    )
    server = DigestServiceServer(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "live-svc.db",
        fake=False,
        interface_router=router,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5.0
    while server.port is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.port is not None
    yield server
    server.shutdown()


def test_live_digest_routes_through_router(live_service_server: DigestServiceServer) -> None:
    router = live_service_server._runtime._interface_router
    assert isinstance(router, _FakeInterfaceRouter)

    conn = HTTPConnection("127.0.0.1", live_service_server.port, timeout=30)
    body = json.dumps(
        {
            "timeframe": "today",
            "sources": "github",
            "correlation_id": "live-corr-1",
        }
    )
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode())
    assert data["text"] == "digest body"
    assert data["run_id"] == 7
    assert data["correlation_id"] == "live-corr-1"
    assert isinstance(data["elapsed_s"], float)
    assert "stages" in data
    assert len(router.calls) == 1
    assert router.calls[0]["digest_request"] is not None


def test_live_digest_passes_correlation_id_to_router(
    live_service_server: DigestServiceServer,
) -> None:
    router = live_service_server._runtime._interface_router
    assert isinstance(router, _FakeInterfaceRouter)

    conn = HTTPConnection("127.0.0.1", live_service_server.port, timeout=30)
    conn.request(
        "POST",
        "/digest",
        body=json.dumps({"timeframe": "today", "sources": "github", "correlation_id": "corr-9"}),
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode())
    assert data["correlation_id"] == "corr-9"
    assert router.calls[-1]["correlation_id"] == "corr-9"


def test_live_digest_fallback_preserves_stage_timings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(digest_service, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        digest_service,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_interface_tool_router",
        lambda **kwargs: MagicMock(name="InterfaceToolRouter"),
        raising=False,
    )
    original_build_connectors = digest_service.build_connectors
    monkeypatch.setattr(
        digest_service,
        "build_connectors",
        lambda *, fake, names: original_build_connectors(fake=True, names=names),
    )
    runtime = DigestServiceRuntime(fake=False, db_path=tmp_path / "stages.db")
    runtime._interface_router = _WorkflowInvokingRouter(runtime)

    request = DigestRequest(topics=["AI"], connector_names=["github"])
    result, stages, _elapsed = asyncio.run(
        runtime.run_digest(request, correlation_id="stage-corr", message="")
    )

    assert "AI News Digest" in result.text
    assert stages
    assert any(name for name in stages)


def test_live_digest_agent_success_preserves_stage_timings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(digest_service, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        digest_service,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_interface_tool_router",
        lambda **kwargs: MagicMock(name="InterfaceToolRouter"),
        raising=False,
    )
    runtime = DigestServiceRuntime(fake=False, db_path=tmp_path / "agent-stages.db")
    router = _OnStageInvokingRouter()
    runtime._interface_router = router

    request = DigestRequest(topics=["AI"], connector_names=["github"])
    result, stages, _elapsed = asyncio.run(
        runtime.run_digest(request, correlation_id="agent-stage-corr", message="")
    )

    assert result.run_id == 7
    assert stages
    assert "parse_request" in stages
    assert "collect_sources" in stages
    assert router.calls[-1]["on_stage"] is not None


def test_live_digest_fallback_uses_per_request_on_stage_not_instance_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(digest_service, "build_chat_model", lambda: MagicMock(name="ChatModel"))
    monkeypatch.setattr(
        digest_service,
        "build_tool_chat_model",
        lambda: MagicMock(name="ToolChatModel"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_connector_factory",
        lambda **kw: MagicMock(name="ConnectorFactory"),
        raising=False,
    )
    monkeypatch.setattr(
        digest_service,
        "build_interface_tool_router",
        lambda **kwargs: MagicMock(name="InterfaceToolRouter"),
        raising=False,
    )
    original_build_connectors = digest_service.build_connectors
    monkeypatch.setattr(
        digest_service,
        "build_connectors",
        lambda *, fake, names: original_build_connectors(fake=True, names=names),
    )
    runtime = DigestServiceRuntime(fake=False, db_path=tmp_path / "per-request-on-stage.db")
    runtime._interface_router = _ConcurrentOverwriteRouter(runtime)

    request = DigestRequest(topics=["AI"], connector_names=["github"])
    _result, stages, _elapsed = asyncio.run(
        runtime.run_digest(request, correlation_id="per-request-corr", message="")
    )

    assert not hasattr(runtime, "_active_on_stage")
    assert stages
    assert "parse_request" in stages
    assert "stale_parse_request" not in stages


def test_digest_endpoint_rejects_unknown_source(service_server: DigestServiceServer) -> None:
    conn = HTTPConnection("127.0.0.1", service_server.port, timeout=5)
    body = json.dumps({"sources": "arxiv", "fake": True})
    conn.request(
        "POST",
        "/digest",
        body=body,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    assert resp.status == 400
    data = json.loads(resp.read().decode())
    assert "error" in data
