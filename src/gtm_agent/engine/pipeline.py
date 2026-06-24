"""Pipeline entry point: build the graph + router + store, run it, return the report."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..llm.router import LLMRouter
from ..log import get_logger
from ..storage.checkpoint import get_checkpointer
from ..storage.store import Store
from .graph import build_report_graph
from .research import set_offline, set_safety_blocklist

if TYPE_CHECKING:
    from ..config import Settings
    from ..models import MarketReport

logger = get_logger(__name__)

_MAIN_RECURSION_LIMIT = 80


def _last_month() -> str:
    first_of_this = datetime.now(tz=UTC).date().replace(day=1)
    return (first_of_this - timedelta(days=1)).strftime("%Y-%m")


async def run_pipeline(
    settings: Settings,
    *,
    month: str | None = None,
    router: LLMRouter | None = None,
    store: Store | None = None,
    offline: bool = False,
) -> MarketReport | None:
    """Run the full report pipeline for one period. Returns the report or None.

    `router` / `store` are injectable so the demo can pass hermetic substitutes; `offline`
    blocks live HTTP in the research tools.
    """
    period = month or _last_month()
    owns_store = store is None
    store = store or Store("data/state.db")
    router = router or LLMRouter(settings.llm)
    set_safety_blocklist(settings.safety_blocklist)
    set_offline(offline)
    graph = build_report_graph(settings, router, store, get_checkpointer(), offline=offline)

    init_state: dict[str, Any] = {"period": period, "quarter": None, "period_type": "month"}
    run_config = {"configurable": {"thread_id": period}, "recursion_limit": _MAIN_RECURSION_LIMIT}
    try:
        final = await graph.ainvoke(init_state, run_config)
    finally:
        if owns_store:
            store.close()
    report = final.get("report")
    logger.info("pipeline_complete", period=period, produced=report is not None)
    return report
