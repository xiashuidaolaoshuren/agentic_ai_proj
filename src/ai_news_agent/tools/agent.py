"""Bounded LangGraph tool-calling runner for follow-up chat (Milestone 2 T5)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, MessagesState, StateGraph

from ai_news_agent.logging_setup import get_logger
from ai_news_agent.progress import bind_progress_sink, emit_progress, reset_progress_sink
from ai_news_agent.tools.registry import ToolRegistry
from ai_news_agent.tools.schemas import (
    InterfaceAgentResult,
    InterfaceAgentResultKind,
    ToolObservation,
    ToolObservationStatus,
    tool_observation_to_dict,
)

logger = get_logger("tool_agent")

_DEFAULT_FALLBACK = "Unable to complete the answer within the allowed steps."

_TERMINAL_TOOL_KINDS = {
    InterfaceAgentResultKind.DIGEST,
    InterfaceAgentResultKind.STRUCTURED,
}


def _emit_custom_progress(line: str) -> None:
    try:
        writer = get_stream_writer()
        writer(line)
    except Exception:
        return


def _bind_progress_sink():
    return bind_progress_sink(_emit_custom_progress)


def _reset_progress_sink(token) -> None:
    reset_progress_sink(token)


def _append_progress_lines(
    existing: list[str] | None, new: list[str] | None
) -> list[str]:
    out = list(existing or [])
    if new:
        out.extend(new)
    return out


class ToolAgentState(MessagesState):
    iterations: int
    progress_lines: Annotated[list[str], _append_progress_lines]
    terminal_result: InterfaceAgentResult | None


@runtime_checkable
class ToolCallModel(Protocol):
    def bind_tools(self, tools: Any) -> ToolCallModel: ...

    async def ainvoke(self, messages: Any) -> AIMessage: ...


class ToolAgentRunner:
    """Runs a bounded tool-calling loop over a registry-backed tool set."""

    def __init__(
        self,
        *,
        graph: Any,
        fallback_text: str,
    ) -> None:
        self._graph = graph
        self._fallback_text = fallback_text

    async def run(self, question: str) -> InterfaceAgentResult:
        result = await self._graph.ainvoke(self._initial_state(question))
        return self._final_answer_from_state(result)

    async def run_streaming(
        self, question: str
    ) -> AsyncIterator[tuple[str, bool, InterfaceAgentResult | None]]:
        """Yield tool progress lines, then a final done event with the answer."""
        final_state: dict[str, Any] | None = None
        yielded: set[str] = set()
        async for mode, chunk in self._graph.astream(
            self._initial_state(question),
            stream_mode=["updates", "values", "custom"],
        ):
            if mode == "custom":
                line = str(chunk)
                if line not in yielded:
                    yielded.add(line)
                    yield line, False, None
                continue
            if mode == "updates":
                for update in chunk.values():
                    for line in update.get("progress_lines", []):
                        if line not in yielded:
                            yielded.add(line)
                            yield line, False, None
                continue
            final_state = chunk

        answer = (
            self._final_answer_from_state(final_state)
            if final_state is not None
            else InterfaceAgentResult(
                kind=InterfaceAgentResultKind.FALLBACK,
                text=self._fallback_text,
                fallback_reason="iteration_cap_exceeded",
            )
        )
        yield "", True, answer

    def _initial_state(self, question: str) -> dict[str, Any]:
        return {
            "messages": [HumanMessage(content=question)],
            "iterations": 0,
            "progress_lines": [],
        }

    def _final_answer_from_state(self, state: dict[str, Any]) -> InterfaceAgentResult:
        progress_lines = list(state.get("progress_lines") or [])
        terminal_result = state.get("terminal_result")
        if terminal_result is not None:
            return terminal_result.model_copy(update={"progress_lines": progress_lines})
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.content:
            iterations = state.get("iterations", 0)
            if iterations > 1:
                return InterfaceAgentResult(
                    kind=InterfaceAgentResultKind.CONVERSATIONAL,
                    text=str(last.content),
                    progress_lines=progress_lines,
                )
            return InterfaceAgentResult(
                kind=InterfaceAgentResultKind.FALLBACK,
                text=self._fallback_text,
                fallback_reason="no_first_tool_call",
                progress_lines=progress_lines,
            )
        return InterfaceAgentResult(
            kind=InterfaceAgentResultKind.FALLBACK,
            text=self._fallback_text,
            fallback_reason="iteration_cap_exceeded",
            progress_lines=progress_lines,
        )


def _tool_call_name(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("name", ""))
    return str(getattr(tool_call, "name", ""))


def _tool_call_args(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        args = tool_call.get("args")
        if isinstance(args, dict):
            return args
        return {}
    args = getattr(tool_call, "args", None)
    if isinstance(args, dict):
        return args
    return {}


def _tool_call_id(tool_call: Any) -> str:
    if isinstance(tool_call, dict):
        return str(tool_call.get("id", ""))
    return str(getattr(tool_call, "id", ""))


def _format_tool_call_start(name: str) -> str:
    return f"Calling {name}…"


def _format_tool_call_done(name: str, observation: ToolObservation) -> str:
    return f"Done {name}: {observation.summary}"


def _format_terminal_tool_call_done(name: str, result: InterfaceAgentResult) -> str:
    if result.kind is InterfaceAgentResultKind.DIGEST:
        return f"Done {name}: Digest ready."
    return f"Done {name}: {result.text}"


def _format_tool_call_failed(name: str, exc: BaseException) -> str:
    return f"Tool failed {name}: {exc}"


def _last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _build_tool_agent_graph(
    *,
    registry: ToolRegistry,
    bound_model: ToolCallModel,
    max_iterations: int,
) -> Any:
    async def agent_node(state: ToolAgentState) -> dict[str, Any]:
        response = await bound_model.ainvoke(state["messages"])
        return {
            "messages": [response],
            "iterations": state.get("iterations", 0) + 1,
        }

    async def tool_node(state: ToolAgentState) -> dict[str, Any]:
        ai_message = _last_ai_message(state["messages"])
        if ai_message is None or not ai_message.tool_calls:
            return {"messages": []}

        tool_messages: list[ToolMessage] = []
        progress_lines: list[str] = []
        terminal_result: InterfaceAgentResult | None = None
        for tool_call in ai_message.tool_calls:
            name = _tool_call_name(tool_call)
            args = _tool_call_args(tool_call)
            tool_call_id = _tool_call_id(tool_call)
            logger.info("tool_call start name=%r", name)
            start_line = _format_tool_call_start(name)
            progress_lines.append(start_line)
            _emit_custom_progress(start_line)
            progress_token = _bind_progress_sink()
            payload: dict[str, object] = {}
            try:
                tool = registry.get_tool(name)
                result = await tool.ainvoke(args)
                if (
                    isinstance(result, InterfaceAgentResult)
                    and result.kind in _TERMINAL_TOOL_KINDS
                ):
                    done_line = _format_terminal_tool_call_done(name, result)
                    progress_lines.append(done_line)
                    _emit_custom_progress(done_line)
                    terminal_result = result
                    logger.info(
                        "tool_call end name=%r terminal_kind=%r",
                        name,
                        result.kind,
                    )
                    continue
                if isinstance(result, InterfaceAgentResult):
                    violation = RuntimeError(
                        f"terminal kind {result.kind.value} not allowed from tool"
                    )
                    logger.error("tool_call failed name=%r error=%r", name, violation)
                    payload = {"error": str(violation)}
                    failed_line = _format_tool_call_failed(name, violation)
                    progress_lines.append(failed_line)
                    _emit_custom_progress(failed_line)
                    tool_messages.append(
                        ToolMessage(
                            content=json.dumps(payload, ensure_ascii=False),
                            tool_call_id=tool_call_id,
                        )
                    )
                    continue
                if not isinstance(result, ToolObservation):
                    raise TypeError(f"Tool {name!r} did not return ToolObservation")
                formatted_text = result.data.get("formatted_text")
                if (
                    result.status is ToolObservationStatus.OK
                    and isinstance(formatted_text, str)
                    and formatted_text.strip()
                ):
                    terminal_result = InterfaceAgentResult(
                        kind=InterfaceAgentResultKind.CONVERSATIONAL,
                        text=formatted_text,
                    )
                    done_line = _format_terminal_tool_call_done(name, terminal_result)
                    progress_lines.append(done_line)
                    _emit_custom_progress(done_line)
                    logger.info(
                        "tool_call end name=%r formatted_text_short_circuit",
                        name,
                    )
                    continue
                payload = tool_observation_to_dict(result)
                done_line = _format_tool_call_done(name, result)
                progress_lines.append(done_line)
                _emit_custom_progress(done_line)
                logger.info(
                    "tool_call end name=%r status=%r",
                    name,
                    result.status,
                )
            except Exception as exc:
                logger.error("tool_call failed name=%r error=%r", name, exc)
                payload = {"error": str(exc)}
                failed_line = _format_tool_call_failed(name, exc)
                progress_lines.append(failed_line)
                _emit_custom_progress(failed_line)
            finally:
                _reset_progress_sink(progress_token)
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            )
        out: dict[str, Any] = {
            "messages": tool_messages,
            "progress_lines": progress_lines,
        }
        if terminal_result is not None:
            out["terminal_result"] = terminal_result
        return out

    def route_after_tool_node(state: ToolAgentState) -> str:
        if state.get("terminal_result") is not None:
            return END
        return "agent_node"

    def route_after_agent(state: ToolAgentState) -> str:
        if state.get("iterations", 0) >= max_iterations:
            return END
        ai_message = _last_ai_message(state["messages"])
        if ai_message is not None and ai_message.tool_calls:
            return "tool_node"
        return END

    builder = StateGraph(ToolAgentState)
    builder.add_node("agent_node", agent_node)
    builder.add_node("tool_node", tool_node)
    builder.add_edge(START, "agent_node")
    builder.add_conditional_edges(
        "agent_node",
        route_after_agent,
        {
            "tool_node": "tool_node",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "tool_node",
        route_after_tool_node,
        {
            "agent_node": "agent_node",
            END: END,
        },
    )
    return builder.compile()


def build_tool_agent_runner(
    *,
    registry: ToolRegistry,
    model: Any,
    max_iterations: int = 5,
    fallback_text: str = _DEFAULT_FALLBACK,
) -> ToolAgentRunner:
    """Construct a bounded tool agent over the given registry and model."""
    bound_model = model.bind_tools(registry.all_tools())
    graph = _build_tool_agent_graph(
        registry=registry,
        bound_model=bound_model,
        max_iterations=max_iterations,
    )
    return ToolAgentRunner(graph=graph, fallback_text=fallback_text)


__all__ = [
    "ToolAgentRunner",
    "ToolCallModel",
    "build_tool_agent_runner",
]
