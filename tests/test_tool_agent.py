"""Tests for Milestone 2 bounded LangGraph tool agent (Task T5)."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage

from ai_news_agent.tools.agent import ToolAgentRunner, build_tool_agent_runner
from ai_news_agent.tools.registry import ToolDefinition, ToolRegistry
from ai_news_agent.tools.schemas import ToolObservation, ToolObservationStatus


class _FakeToolCallModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._index = 0
        self.bound_tools: list[Any] | None = None

    def bind_tools(self, tools: Any) -> "_FakeToolCallModel":
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: Any) -> AIMessage:
        msg = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return msg


def _sample_registry(*, execute: Any | None = None) -> ToolRegistry:
    async def _default_execute() -> ToolObservation:
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="ok",
        )

    tool = ToolDefinition(
        name="load_latest_digest",
        description="Load the latest saved digest.",
        args_schema={"type": "object", "properties": {}},
        execute=execute or _default_execute,
    )
    return ToolRegistry([tool])


def test_build_tool_agent_runner_returns_runner() -> None:
    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="done")])

    runner = build_tool_agent_runner(registry=registry, model=model)

    assert isinstance(runner, ToolAgentRunner)


def test_tool_agent_runner_direct_answer_returns_model_content() -> None:
    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="Grounded answer.")])
    runner = build_tool_agent_runner(registry=registry, model=model)

    answer = asyncio.run(runner.run("What is in the latest digest?"))

    assert answer == "Grounded answer."


def test_tool_agent_runner_executes_tool_then_returns_final_answer() -> None:
    calls: list[str] = []

    async def _execute() -> ToolObservation:
        calls.append("executed")
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="Loaded digest with 1 entry.",
        )

    registry = _sample_registry(execute=_execute)
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "load_latest_digest",
                        "args": {},
                        "id": "call-1",
                    }
                ],
            ),
            AIMessage(content="The latest digest has one entry."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    answer = asyncio.run(runner.run("Summarize the latest digest."))

    assert calls == ["executed"]
    assert answer == "The latest digest has one entry."


def test_tool_agent_runner_returns_fallback_when_iteration_cap_reached() -> None:
    registry = _sample_registry()
    always_tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "load_latest_digest",
                "args": {},
                "id": "call-loop",
            }
        ],
    )
    model = _FakeToolCallModel([always_tool_call, always_tool_call, always_tool_call])
    runner = build_tool_agent_runner(
        registry=registry,
        model=model,
        max_iterations=2,
        fallback_text="Stopped after cap.",
    )

    answer = asyncio.run(runner.run("Keep calling tools."))

    assert answer == "Stopped after cap."


def test_tool_agent_runner_survives_tool_execute_exception() -> None:
    async def _boom() -> ToolObservation:
        raise RuntimeError("boom")

    registry = _sample_registry(execute=_boom)
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "load_latest_digest",
                        "args": {},
                        "id": "call-error",
                    }
                ],
            ),
            AIMessage(content="Recovered after tool failure."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    answer = asyncio.run(runner.run("Try loading the digest."))

    assert answer == "Recovered after tool failure."


def test_build_tool_agent_runner_import_from_tools_package() -> None:
    from ai_news_agent.tools import ToolAgentRunner as PackageToolAgentRunner
    from ai_news_agent.tools import build_tool_agent_runner as package_build_tool_agent_runner

    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="package ok")])
    runner = package_build_tool_agent_runner(registry=registry, model=model)

    assert isinstance(runner, PackageToolAgentRunner)
    assert asyncio.run(runner.run("hello")) == "package ok"
