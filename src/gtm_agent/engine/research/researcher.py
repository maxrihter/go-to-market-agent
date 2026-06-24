"""Researcher subgraph: handles one ConductResearch task.

Pattern (from open_deep_research): researcher <-> researcher_tools (loop, capped) then
compress_research, returning compressed findings + sources to the supervisor. The router
is injected at build time, so there is no module-level provider singleton.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from ...llm.router import LLMRole, LLMRouter
from ...models import ResearcherState, SourceRef
from ...prompts import load_prompt
from .tools import (
    _sanitize_text,
    execute_tools_parallel,
    get_research_tools,
    scrub_duplicate_tool_calls,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

_MAX_TOOL_ITERATIONS = 6
_COMPRESS_MAX_RETRIES = 3

_DEPTH_HINT = {
    "quick": "1-2 queries, only the key facts",
    "standard": "3-4 queries, balanced depth",
    "deep": "5-6 queries, maximum sources and cross-referencing",
}


def _build_researcher_prompt(
    research_topic: str, preferred_sources: list[str], depth: str, max_iters: int
) -> str:
    base = load_prompt("researcher_system").format(max_iters=max_iters)
    sources_hint = (
        f"Priority sources: {', '.join(preferred_sources)}"
        if preferred_sources
        else "Sources are open; find the best signal."
    )
    depth_hint = _DEPTH_HINT.get(depth, _DEPTH_HINT["standard"])
    return (
        f"{base}\n\n--- CURRENT TASK ---\n"
        f"Research topic: {research_topic}\n"
        f"Depth: {depth} ({depth_hint})\n"
        f"{sources_hint}\n"
    )


async def researcher_step(
    state: ResearcherState, config: RunnableConfig, *, router: LLMRouter
) -> Command[Literal["researcher_tools", "compress_research"]]:
    """One researcher decision: call tools, signal completion, or hit the cap."""
    iterations = state.get("tool_call_iterations", 0)
    if iterations >= _MAX_TOOL_ITERATIONS:
        return Command(goto="compress_research")

    system_prompt = _build_researcher_prompt(
        research_topic=state["research_topic"],
        preferred_sources=state.get("preferred_sources", []),
        depth=state.get("depth", "standard"),
        max_iters=_MAX_TOOL_ITERATIONS,
    )
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Begin researching: {state['research_topic']}"),
        *state["researcher_messages"],
    ]
    model = router.chat_model(LLMRole.RESEARCH).bind_tools(get_research_tools())
    response: AIMessage = await model.ainvoke(scrub_duplicate_tool_calls(messages))

    if not response.tool_calls:
        return Command(goto="compress_research", update={"researcher_messages": [response]})
    return Command(goto="researcher_tools", update={"researcher_messages": [response]})


async def researcher_tools_step(
    state: ResearcherState, config: RunnableConfig
) -> Command[Literal["researcher", "compress_research"]]:
    """Execute the last message's tool calls and append observations."""
    last_msg = state["researcher_messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", []) or []
    if not tool_calls:
        return Command(goto="researcher")

    real_calls = [tc for tc in tool_calls if tc["name"] != "ResearchComplete"]
    completion_calls = [tc for tc in tool_calls if tc["name"] == "ResearchComplete"]
    results = await execute_tools_parallel(real_calls) if real_calls else []

    tool_messages: list[Any] = []
    raw_findings_new: list[str] = []
    sources_new: list[SourceRef] = []
    # strict=False (not True): tolerate a length mismatch by processing the prefix rather
    # than crashing the subgraph mid-loop, matching the production source's defensive choice.
    for call, result in zip(real_calls, results, strict=False):
        content = _format_tool_result(result)
        tool_messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
        raw_findings_new.append(f"[{call['name']}] {content[:500]}")
        result_dict = result.get("result", {}) if isinstance(result, dict) else {}
        for src_url in result_dict.get("sources", [])[:5]:
            url = src_url if src_url.startswith("http") else f"https://{src_url}"
            sources_new.append(SourceRef(title=src_url, url=url))

    # Acknowledge ResearchComplete calls so the message pairing stays valid.
    for tc in completion_calls:
        tool_messages.append(
            ToolMessage(content="Research completion acknowledged.", tool_call_id=tc["id"])
        )

    goto: Literal["researcher", "compress_research"] = (
        "compress_research" if completion_calls else "researcher"
    )
    return Command(
        goto=goto,
        update={
            "researcher_messages": tool_messages,
            "tool_call_iterations": state.get("tool_call_iterations", 0) + 1,
            "raw_findings": raw_findings_new,
            "sources_collected": sources_new,
        },
    )


def _format_tool_result(result: dict[str, Any]) -> str:
    if "error" in result:
        return f"Tool error: {result['error']}"
    r = result.get("result", {})
    if not r:
        return "No results returned."
    if isinstance(r, dict):
        return "\n".join(f"{k}: {v}" for k, v in r.items() if k != "sources")[:1500]
    return str(r)[:1500]


async def compress_research_step(
    state: ResearcherState, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Compress raw findings into a dense, sourced summary, truncating on token errors."""
    raw_findings = state.get("raw_findings", [])
    topic = state["research_topic"]
    if not raw_findings:
        return {"compressed_findings": f"No data found for topic: {topic}"}

    findings_text = "\n\n---\n\n".join(raw_findings)
    compress_prompt = load_prompt("compress_research_system")
    model = router.chat_model(LLMRole.RESEARCH)

    char_limit: int | None = None
    truncated = findings_text
    for attempt in range(_COMPRESS_MAX_RETRIES):
        try:
            user_content = (
                f"Topic: {topic}\n\nGathered data:\n{truncated}\n\n"
                f"Compress into a dense, structured summary per the rules above."
            )
            response = await model.ainvoke(
                [SystemMessage(content=compress_prompt), HumanMessage(content=user_content)]
            )
            return {
                "compressed_findings": _sanitize_text(
                    str(response.content), f"compress:{topic[:40]}"
                )
            }
        except Exception as exc:  # noqa: BLE001
            is_token_error = any(k in str(exc).lower() for k in ("token", "context", "length"))
            if not is_token_error or attempt >= _COMPRESS_MAX_RETRIES - 1:
                return {"compressed_findings": f"[Compression failed: {str(exc)[:120]}]"}
            char_limit = 12_000 if char_limit is None else int(char_limit * 0.9)
            truncated = findings_text[:char_limit]

    return {"compressed_findings": "[Compression exhausted retries]"}


def build_researcher_graph(router: LLMRouter) -> Any:
    """Build + compile the researcher subgraph with the router injected."""
    builder = StateGraph(ResearcherState)
    builder.add_node("researcher", functools.partial(researcher_step, router=router))
    builder.add_node("researcher_tools", researcher_tools_step)
    builder.add_node("compress_research", functools.partial(compress_research_step, router=router))
    builder.add_edge(START, "researcher")
    builder.add_edge("compress_research", END)
    return builder.compile()
