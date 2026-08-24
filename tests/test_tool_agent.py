"""Tests for Milestone 2 bounded LangGraph tool agent (Task T5)."""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, tool

from ai_news_agent.tools.agent import (
    ToolAgentRunner,
    _DEFAULT_FALLBACK,
    build_tool_agent_runner,
)
from ai_news_agent.tools.registry import ToolRegistry
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
    ToolObservation,
    ToolObservationStatus,
)


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
    async def load_latest_digest() -> ToolObservation:
        """Load the latest saved digest."""
        if execute is not None:
            return await execute()
        return ToolObservation(
            status=ToolObservationStatus.OK,
            summary="ok",
        )

    return ToolRegistry([tool(load_latest_digest)])


def test_build_tool_agent_runner_returns_runner() -> None:
    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="done")])

    runner = build_tool_agent_runner(registry=registry, model=model)

    assert isinstance(runner, ToolAgentRunner)
    assert model.bound_tools is not None
    assert len(model.bound_tools) == 1
    assert isinstance(model.bound_tools[0], BaseTool)


def test_tool_agent_runner_first_response_without_tool_calls_is_routing_failure() -> None:
    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="Grounded answer.")])
    runner = build_tool_agent_runner(registry=registry, model=model)

    assert model.bound_tools is not None
    assert all(isinstance(t, BaseTool) for t in model.bound_tools)

    result = asyncio.run(runner.run("What is in the latest digest?"))

    assert result.kind == InterfaceAgentResultKind.FALLBACK
    assert result.fallback_reason == "no_first_tool_call"
    assert result.text == _DEFAULT_FALLBACK


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

    result = asyncio.run(runner.run("Summarize the latest digest."))

    assert calls == ["executed"]
    assert isinstance(result, InterfaceAgentResult)
    assert result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert result.text == "The latest digest has one entry."
    assert result.progress_lines == [
        "Calling load_latest_digest…",
        "Done load_latest_digest: Loaded digest with 1 entry.",
    ]


def _terminal_digest_registry() -> ToolRegistry:
    @tool
    async def generate_digest() -> InterfaceAgentResult:
        """Generate a digest."""
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="Digest text",
            run_id=7,
        )

    return ToolRegistry([generate_digest])


def test_terminal_digest_tool_short_circuits() -> None:
    registry = _terminal_digest_registry()
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_digest",
                        "args": {},
                        "id": "call-digest",
                    }
                ],
            ),
            AIMessage(content="This second response must not be used."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    result = asyncio.run(runner.run("Generate the digest."))

    assert model._index == 1
    assert result.kind == InterfaceAgentResultKind.DIGEST
    assert result.text == "Digest text"
    assert result.run_id == 7
    assert result.progress_lines == [
        "Calling generate_digest…",
        "Done generate_digest: Digest ready.",
    ]


def _terminal_violation_registry() -> ToolRegistry:
    @tool
    async def bad_terminal_tool() -> InterfaceAgentResult:
        """Return a disallowed terminal kind."""
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.CONVERSATIONAL,
            text="Should not short-circuit.",
        )

    return ToolRegistry([bad_terminal_tool])


def test_tool_node_records_terminal_type_violation_and_recovers() -> None:
    registry = _terminal_violation_registry()
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "bad_terminal_tool",
                        "args": {},
                        "id": "call-violation",
                    }
                ],
            ),
            AIMessage(content="Recovered after terminal violation."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    result = asyncio.run(runner.run("Try the bad tool."))

    assert model._index == 2
    assert result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert result.text == "Recovered after terminal violation."
    assert result.progress_lines[0] == "Calling bad_terminal_tool…"
    assert result.progress_lines[1] == (
        "Tool failed bad_terminal_tool: terminal kind conversational not allowed from tool"
    )


def _terminal_structured_registry() -> ToolRegistry:
    @tool
    async def list_digest_sources() -> InterfaceAgentResult:
        """List digest sources."""
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.STRUCTURED,
            text="Sources from the latest digest.",
            run_id=3,
        )

    return ToolRegistry([list_digest_sources])


def test_terminal_structured_tool_short_circuits() -> None:
    registry = _terminal_structured_registry()
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_digest_sources",
                        "args": {},
                        "id": "call-structured",
                    }
                ],
            ),
            AIMessage(content="This second response must not be used."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    result = asyncio.run(runner.run("List digest sources."))

    assert model._index == 1
    assert result.kind == InterfaceAgentResultKind.STRUCTURED
    assert result.text == "Sources from the latest digest."
    assert result.run_id == 3


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

    assert answer.kind == InterfaceAgentResultKind.FALLBACK
    assert answer.fallback_reason == "iteration_cap_exceeded"
    assert answer.text == "Stopped after cap."


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

    result = asyncio.run(runner.run("Try loading the digest."))

    assert result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert result.text == "Recovered after tool failure."
    assert "Calling load_latest_digest…" in result.progress_lines
    assert any(
        line.startswith("Tool failed load_latest_digest:")
        for line in result.progress_lines
    )


async def _collect_tool_agent_stream(
    runner: ToolAgentRunner, question: str
) -> list[tuple[str, bool, InterfaceAgentResult | None]]:
    events: list[tuple[str, bool, InterfaceAgentResult | None]] = []
    async for event in runner.run_streaming(question):
        events.append(event)
    return events


def test_tool_agent_run_streaming_emits_ordered_tool_progress_then_done() -> None:
    async def _execute() -> ToolObservation:
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
                        "id": "call-stream-1",
                    }
                ],
            ),
            AIMessage(content="The latest digest has one entry."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    events = asyncio.run(
        _collect_tool_agent_stream(runner, "Summarize the latest digest.")
    )

    progress_lines = [text for text, done, _answer in events if not done and text]
    assert progress_lines == [
        "Calling load_latest_digest…",
        "Done load_latest_digest: Loaded digest with 1 entry.",
    ]
    done_result = events[-1][2]
    assert events[-1][0] == ""
    assert events[-1][1] is True
    assert isinstance(done_result, InterfaceAgentResult)
    assert done_result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert done_result.text == "The latest digest has one entry."


def test_tool_agent_run_streaming_live_calling_before_slow_digest_tool_completes() -> None:
    """Slow digest tool must emit Calling before ainvoke finishes."""
    proceed = asyncio.Event()
    completed = asyncio.Event()

    @tool
    async def generate_ai_news_digest() -> InterfaceAgentResult:
        """Generate the AI news digest for this request."""
        await proceed.wait()
        completed.set()
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="Full digest body with many sections.",
            run_id=7,
        )

    registry = ToolRegistry([generate_ai_news_digest])
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-slow-digest",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    async def _run() -> list[tuple[str, bool, InterfaceAgentResult | None]]:
        events: list[tuple[str, bool, InterfaceAgentResult | None]] = []
        stream = runner.run_streaming("Give me today's AI digest.")

        async def collect() -> None:
            async for event in stream:
                events.append(event)

        task = asyncio.create_task(collect())
        for _ in range(50):
            if events:
                break
            await asyncio.sleep(0.01)
        assert events, "expected Calling before slow digest tool completes"
        assert events[0] == ("Calling generate_ai_news_digest…", False, None)
        assert not completed.is_set()
        proceed.set()
        await task
        return events

    events = asyncio.run(_run())

    assert events[0] == ("Calling generate_ai_news_digest…", False, None)


def test_tool_agent_run_streaming_digest_done_is_short_summary_not_full_body() -> None:
    @tool
    async def generate_ai_news_digest() -> InterfaceAgentResult:
        """Generate the AI news digest for this request."""
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.DIGEST,
            text="Full digest body with many sections and URLs.",
            run_id=7,
        )

    registry = ToolRegistry([generate_ai_news_digest])
    model = _FakeToolCallModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "generate_ai_news_digest",
                        "args": {},
                        "id": "call-digest-done",
                    }
                ],
            ),
            AIMessage(content="unused"),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    events = asyncio.run(
        _collect_tool_agent_stream(runner, "Give me today's AI digest.")
    )
    progress_lines = [text for text, done, _answer in events if not done and text]
    done_line = progress_lines[-1]
    assert done_line.startswith("Done generate_ai_news_digest:")
    assert "Full digest body" not in done_line
    assert done_line == "Done generate_ai_news_digest: Digest ready."


def test_tool_agent_run_streaming_emits_failure_progress_line() -> None:
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
                        "id": "call-stream-fail",
                    }
                ],
            ),
            AIMessage(content="Recovered after tool failure."),
        ]
    )
    runner = build_tool_agent_runner(registry=registry, model=model)

    events = asyncio.run(_collect_tool_agent_stream(runner, "Try loading the digest."))

    progress_lines = [text for text, done, _answer in events if not done and text]
    assert progress_lines[0] == "Calling load_latest_digest…"
    assert progress_lines[1].startswith("Tool failed load_latest_digest:")
    done_result = events[-1][2]
    assert isinstance(done_result, InterfaceAgentResult)
    assert done_result.kind == InterfaceAgentResultKind.CONVERSATIONAL
    assert done_result.text == "Recovered after tool failure."


def test_build_tool_agent_runner_import_from_tools_package() -> None:
    from ai_news_agent.tools import ToolAgentRunner as PackageToolAgentRunner
    from ai_news_agent.tools import build_tool_agent_runner as package_build_tool_agent_runner

    registry = _sample_registry()
    model = _FakeToolCallModel([AIMessage(content="package ok")])
    runner = package_build_tool_agent_runner(registry=registry, model=model)

    assert isinstance(runner, PackageToolAgentRunner)
    package_result = asyncio.run(runner.run("hello"))
    assert isinstance(package_result, InterfaceAgentResult)
    assert package_result.kind == InterfaceAgentResultKind.FALLBACK
    assert package_result.fallback_reason == "no_first_tool_call"
