"""Research supervisor subgraph: plan and delegate web research.

Pattern: supervisor <-> supervisor_tools (loop). The supervisor delegates ConductResearch
tasks; each spawns the researcher subgraph, whose compressed findings are appended to
state.notes. The supervisor stops when it emits ResearchComplete, when coverage is full, or
at the iteration cap. The router and the researcher graph are injected at build time.
"""

from __future__ import annotations

import asyncio
import functools
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph import START as _START
from langgraph.types import Command

from ...llm.router import LLMRole, LLMRouter
from ...log import get_logger
from ...models import ConductResearch, ResearchComplete, ResearchSupervisorState
from ...prompts import load_prompt
from .researcher import build_researcher_graph
from .tools import scrub_duplicate_tool_calls

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

logger = get_logger(__name__)

_MAX_ITERS = 8
_MAX_ITERS_ANNUAL = 20


def _build_supervisor_context(state: ResearchSupervisorState) -> str:
    section_briefs = state.get("section_briefs", {})
    coverage = state.get("section_coverage", {}) or {}
    notes = state.get("notes", [])

    coverage_lines = [
        f"- {sid}: {'[covered]' if coverage.get(sid) else '[pending]'}\n  brief: {brief[:200]}"
        for sid, brief in section_briefs.items()
    ]
    notes_preview = ""
    if notes:
        notes_preview = f"\n\nFindings so far ({len(notes)}, preview):\n" + "\n---\n".join(
            n[:400] for n in notes[:3]
        )
    return (
        f"Research brief:\n{state.get('research_brief', '')}\n\n"
        f"Section coverage:\n" + "\n".join(coverage_lines) + notes_preview
    )


async def supervisor_step(
    state: ResearchSupervisorState, config: RunnableConfig, *, router: LLMRouter
) -> Command[Literal["supervisor_tools", END]]:  # type: ignore[valid-type]
    """Delegate research, or end when complete / capped."""
    iterations = state.get("research_iterations", 0)
    is_annual = state.get("period_type", "month") == "annual"
    max_iters = _MAX_ITERS_ANNUAL if is_annual else _MAX_ITERS
    if iterations == 0:
        logger.info("supervisor_start", is_annual=is_annual, max_iters=max_iters)
    if iterations >= max_iters:
        logger.info(
            "supervisor_max_iterations", iterations=iterations, notes=len(state.get("notes", []))
        )
        return Command(goto=END)

    messages: list[Any] = [
        SystemMessage(content=load_prompt("supervisor_system")),
        HumanMessage(content=_build_supervisor_context(state)),
        *state.get("supervisor_messages", []),
    ]
    model = router.chat_model(LLMRole.RESEARCH).bind_tools([ConductResearch, ResearchComplete])
    response: AIMessage = await model.ainvoke(scrub_duplicate_tool_calls(messages))

    if not response.tool_calls:
        logger.info("supervisor_no_tool_calls_ending", iterations=iterations)
        return Command(goto=END, update={"supervisor_messages": [response]})
    return Command(goto="supervisor_tools", update={"supervisor_messages": [response]})


async def supervisor_tools_step(
    state: ResearchSupervisorState, config: RunnableConfig, *, researcher_graph: Any
) -> Command[Literal["supervisor", END]]:  # type: ignore[valid-type]
    """Run a researcher subgraph per ConductResearch call; acknowledge other tool calls."""
    last_msg = state["supervisor_messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", []) or []
    if not tool_calls:
        return Command(goto=END)

    conduct_calls = [tc for tc in tool_calls if tc["name"] == "ConductResearch"]
    non_conduct = [tc for tc in tool_calls if tc["name"] != "ConductResearch"]
    has_completion = any(tc["name"] == "ResearchComplete" for tc in non_conduct)

    async def _run_one(call: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        args = call.get("args", {})
        target = args.get("section_target", "unknown")
        initial_state = {
            "research_topic": args.get("research_topic", ""),
            "section_target": target,
            "depth": args.get("depth", "standard"),
            "preferred_sources": args.get("preferred_sources", []),
            "researcher_messages": [],
            "tool_call_iterations": 0,
            "raw_findings": [],
            "sources_collected": [],
        }
        try:
            sub_result = await researcher_graph.ainvoke(initial_state)
            return call, target, sub_result.get("compressed_findings", "")
        except Exception as exc:  # noqa: BLE001
            logger.error("researcher_subgraph_failed", target=target, error=str(exc)[:200])
            return call, target, f"[Research failed: {str(exc)[:120]}]"

    results = await asyncio.gather(*[_run_one(c) for c in conduct_calls]) if conduct_calls else []

    tool_messages: list[Any] = []
    new_notes: list[str] = []
    coverage_update: dict[str, bool] = {}
    for call, target, findings in results:
        tool_messages.append(ToolMessage(content=findings[:2000], tool_call_id=call["id"]))
        new_notes.append(f"[{target}]\n{findings}")
        coverage_update[target] = bool(findings and "[Research failed" not in findings)

    for call in non_conduct:
        if call["name"] == "ResearchComplete":
            ack = "Research completion acknowledged."
        else:
            ack = f"Unknown tool '{call['name']}' ignored."
            logger.warning("supervisor_unknown_tool_acked", name=call["name"])
        tool_messages.append(ToolMessage(content=ack, tool_call_id=call["id"]))

    return Command(
        goto=END if has_completion else "supervisor",
        update={
            "supervisor_messages": tool_messages,
            "notes": new_notes,
            "research_iterations": state.get("research_iterations", 0) + 1,
            "section_coverage": {**state.get("section_coverage", {}), **coverage_update},
        },
    )


def build_supervisor_graph(router: LLMRouter) -> Any:
    """Build + compile the supervisor subgraph with the router + researcher graph injected."""
    researcher_graph = build_researcher_graph(router)
    builder = StateGraph(ResearchSupervisorState)
    builder.add_node("supervisor", functools.partial(supervisor_step, router=router))
    builder.add_node(
        "supervisor_tools",
        functools.partial(supervisor_tools_step, researcher_graph=researcher_graph),
    )
    builder.add_edge(_START, "supervisor")
    return builder.compile()
