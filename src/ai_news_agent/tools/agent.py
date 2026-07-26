"""Bounded LangGraph tool-calling runner for follow-up chat (Milestone 2 T5)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from ai_news_agent.logging_setup import get_logger
from ai_news_agent.tools.registry import ToolRegistry
from ai_news_agent.tools.schemas import ToolObservation, tool_observation_to_dict

logger = get_logger("tool_agent")

_DEFAULT_FALLBACK = "Unable to complete the answer within the allowed steps."


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

    async def run(self, question: str) -> str:
        result = await self._graph.ainvoke(self._initial_state(question))
        return self._final_answer_from_state(result)

    async def run_streaming(
        self, question: str
    ) -> AsyncIterator[tuple[str, bool, str | None]]:
        """Yield tool progress lines, then a final done event with the answer."""
        final_state: dict[str, Any] | None = None
        async for mode, chunk in self._graph.astream(
            self._initial_state(question),
            stream_mode=["updates", "values"],
        ):
            if mode == "updates":
                for update in chunk.values():
                    for line in update.get("progress_lines", []):
                        yield line, False, None
                continue
            final_state = chunk

        answer = (
            self._final_answer_from_state(final_state)
            if final_state is not None
            else self._fallback_text
        )
        yield "", True, answer

    def _initial_state(self, question: str) -> dict[str, Any]:
        return {
            "messages": [HumanMessage(content=question)],
            "iterations": 0,
            "progress_lines": [],
        }

    def _final_answer_from_state(self, state: dict[str, Any]) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.content:
            return str(last.content)
        return self._fallback_text


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
        for tool_call in ai_message.tool_calls:
            name = _tool_call_name(tool_call)
            args = _tool_call_args(tool_call)
            tool_call_id = _tool_call_id(tool_call)
            logger.info("tool_call start name=%r", name)
            progress_lines.append(_format_tool_call_start(name))
            try:
                tool = registry.get_tool(name)
                observation = await tool.ainvoke(args)
                if not isinstance(observation, ToolObservation):
                    raise TypeError(f"Tool {name!r} did not return ToolObservation")
                payload = tool_observation_to_dict(observation)
                progress_lines.append(_format_tool_call_done(name, observation))
                logger.info(
                    "tool_call end name=%r status=%r",
                    name,
                    observation.status,
                )
            except Exception as exc:
                logger.error("tool_call failed name=%r error=%r", name, exc)
                payload = {"error": str(exc)}
                progress_lines.append(_format_tool_call_failed(name, exc))
            tool_messages.append(
                ToolMessage(
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            )
        return {"messages": tool_messages, "progress_lines": progress_lines}

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
    builder.add_edge("tool_node", "agent_node")
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


__all__ = ["ToolAgentRunner", "ToolCallModel", "build_tool_agent_runner"]
