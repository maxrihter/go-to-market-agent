"""Top-level graph assembly: wire every node into one runnable report pipeline.

Flow:
  brief -> research (supervisor subgraph) -> [6 analysts | fan-out] -> [3 synthesizers]
    -> compute_mom -> enrich_prior -> assemble -> apply_overrides -> pre_publish_gate
    -> (fail -> END) -> qa_reviewer -> (reject -> END) -> render -> store_report -> END

Nodes receive their dependencies (router, store, settings) bound via functools.partial at
build time, so the graph holds no globals.
"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from ..integrations.output import render_markdown
from ..log import get_logger
from ..models import MarketReportState
from .nodes.analysts import ANALYSTS
from .nodes.annotators import compute_mom_node, enrich_with_prior_metrics_node, store_report_node
from .nodes.assembly import assemble_final_report
from .nodes.brief import write_brief
from .nodes.enrich import collect_enrichment
from .nodes.overrides import apply_overrides_node
from .nodes.qa_gates import (
    pre_publish_qa_agent_node,
    qa_agent_decision_router,
    run_all_gates,
    validate_cross_references,
)
from .nodes.synthesizers import SYNTHESIZERS
from .research import build_supervisor_graph

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ..config import Settings
    from ..llm.router import LLMRouter
    from ..storage.store import Store

logger = get_logger(__name__)

_RESEARCH_RECURSION_LIMIT = 60


async def run_research_supervisor(
    state: Any, config: RunnableConfig, *, router: LLMRouter
) -> dict[str, Any]:
    """Invoke the research subgraph and lift its notes into the top-level state."""
    supervisor = build_supervisor_graph(router)
    sub_state = {
        "research_brief": state.get("research_brief", ""),
        "section_briefs": state.get("section_briefs", {}),
        "supervisor_messages": [],
        "notes": [],
        "research_iterations": 0,
        "section_coverage": {},
        "period_type": state.get("period_type", "month"),
    }
    try:
        result = await supervisor.ainvoke(sub_state, {"recursion_limit": _RESEARCH_RECURSION_LIMIT})
    except Exception as exc:  # noqa: BLE001
        logger.exception("research_supervisor_crashed", error=str(exc)[:200])
        return {"error": [f"research_supervisor_crashed: {str(exc)[:120]}"], "notes": []}
    notes = result.get("notes", [])
    logger.info("research_complete", note_count=len(notes))
    return {"notes": notes, "raw_notes": notes}


async def _marker(state: Any, config: RunnableConfig) -> dict[str, Any]:
    """A no-op fan-in barrier."""
    return {}


async def pre_publish_gate(
    state: Any, config: RunnableConfig, *, settings: Settings
) -> dict[str, Any]:
    """Run the deterministic gates + cross-reference validation; set qa_status."""
    report = state.get("report")
    if report is None:
        return {"qa_status": "fail", "qa_issues": ["No report was assembled."]}
    passed, issues = run_all_gates(report, forbidden_keywords=tuple(settings.forbidden_keywords))
    validation = validate_cross_references(report)
    if not passed or not validation.ok:
        logger.warning("pre_publish_gate_failed", issue_count=len(issues) + len(validation.issues))
        return {"qa_status": "fail", "qa_issues": issues + validation.issues}
    return {"qa_status": "pending"}


def _write_outputs(report: Any, md: str) -> dict[str, str]:
    """Synchronous file IO (run via asyncio.to_thread to avoid blocking the event loop)."""
    outdir = Path("output")
    outdir.mkdir(parents=True, exist_ok=True)
    md_path = outdir / f"{report.report_id}.md"
    json_path = outdir / f"{report.report_id}.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


async def render_report(
    state: Any, config: RunnableConfig, *, settings: Settings
) -> dict[str, Any]:
    """Render the report to Markdown + JSON under output/."""
    report = state["report"]
    md = render_markdown(report, brand_name=settings.brand.name)
    paths = await asyncio.to_thread(_write_outputs, report, md)
    logger.info("report_rendered", path=paths["markdown"])
    return {"qa_status": "pass", "output_paths": paths}


def _gate_router(state: Any) -> str:
    return "fail" if state.get("qa_status") == "fail" else "pass"


def build_report_graph(
    settings: Settings,
    router: LLMRouter,
    store: Store,
    checkpointer: Any = None,
    *,
    offline: bool = False,
) -> Any:
    """Build + compile the report graph with all dependencies injected."""
    p = functools.partial
    b = StateGraph(MarketReportState)

    b.add_node("write_brief", p(write_brief, settings=settings))
    b.add_node("research", p(run_research_supervisor, router=router))
    b.add_node("enrich", p(collect_enrichment, settings=settings, store=store, offline=offline))
    for name, node in ANALYSTS.items():
        b.add_node(name, p(node, router=router))
    b.add_node("analysts_complete", _marker)
    for name, node in SYNTHESIZERS.items():
        b.add_node(name, p(node, router=router))
    b.add_node("synth_complete", _marker)
    b.add_node("compute_mom", p(compute_mom_node, store=store))
    b.add_node("enrich_prior", p(enrich_with_prior_metrics_node, store=store))
    b.add_node("assemble", assemble_final_report)
    b.add_node("apply_overrides", p(apply_overrides_node, store=store))
    b.add_node("pre_publish_gate", p(pre_publish_gate, settings=settings))
    b.add_node("qa_reviewer", p(pre_publish_qa_agent_node, router=router))
    b.add_node("render", p(render_report, settings=settings))
    b.add_node("store_report", p(store_report_node, store=store))

    b.add_edge(START, "write_brief")
    b.add_edge("write_brief", "research")
    b.add_edge("research", "enrich")
    for name in ANALYSTS:
        b.add_edge("enrich", name)
        b.add_edge(name, "analysts_complete")
    for name in SYNTHESIZERS:
        b.add_edge("analysts_complete", name)
        b.add_edge(name, "synth_complete")
    b.add_edge("synth_complete", "compute_mom")
    b.add_edge("compute_mom", "enrich_prior")
    b.add_edge("enrich_prior", "assemble")
    b.add_edge("assemble", "apply_overrides")
    b.add_edge("apply_overrides", "pre_publish_gate")
    b.add_conditional_edges("pre_publish_gate", _gate_router, {"pass": "qa_reviewer", "fail": END})
    b.add_conditional_edges(
        "qa_reviewer", qa_agent_decision_router, {"publish": "render", "reject": END}
    )
    b.add_edge("render", "store_report")
    b.add_edge("store_report", END)

    return b.compile(checkpointer=checkpointer) if checkpointer else b.compile()
