"""Storage-backed annotators: month-over-month diff, prior-metric enrichment, persistence.

These read the prior period's report from the SQLite store (injected via the graph) to
produce cross-period intelligence. They are pure-compute plus storage I/O, no LLM calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...log import get_logger
from ...models import KPIDelta, MoMDiffStructured

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...storage.store import Store

logger = get_logger(__name__)

_CURRENT_SCHEMA = "5"


def _names(section: Any, *attrs: str) -> set[str]:
    """Collect competitor/trend names from a section payload (model or dict)."""
    out: set[str] = set()
    for attr in attrs:
        if section is None:
            continue
        items = getattr(section, attr, None) if not isinstance(section, dict) else section.get(attr)
        for it in items or []:
            name = getattr(it, "name", None) if not isinstance(it, dict) else it.get("name")
            name = name or (
                getattr(it, "trend_name", None)
                if not isinstance(it, dict)
                else it.get("trend_name")
            )
            if name:
                out.add(name)
    return out


async def compute_mom_node(state: Any, config: RunnableConfig, *, store: Store) -> dict[str, Any]:
    """Compare the current sections against the prior period's stored report."""
    period = state.get("period", "")
    prev = store.fetch_previous_report(period)
    if prev is None:
        return {
            "mom_narrative": "First period observed; no prior comparison available.",
            "mom_diff": MoMDiffStructured(is_first_period=True),
        }
    payload, schema_version = prev
    if schema_version != _CURRENT_SCHEMA:
        logger.warning("mom_schema_mismatch", prev=schema_version, current=_CURRENT_SCHEMA)
        return {
            "mom_narrative": "Prior report uses an incompatible schema; cross-period diff skipped.",
            "mom_diff": MoMDiffStructured(prev_schema_incompatible=True),
        }

    # KPI deltas by label (scoreboard hero KPIs).
    cur_sb = state.get("section_scoreboard")
    cur_kpis = {k.label: k for k in getattr(cur_sb, "hero_kpis", [])} if cur_sb else {}
    prev_kpis = {k.get("label"): k for k in payload.get("scoreboard", {}).get("hero_kpis", [])}
    kpi_deltas = [
        KPIDelta(
            label=label,
            prev_value=str(prev_kpis[label].get("value", "")),
            curr_value=str(k.value),
            direction=k.delta_direction,
        )
        for label, k in cur_kpis.items()
        if label in prev_kpis
    ]

    cur_comp = _names(state.get("section_competitive"), "global_players", "regional_players")
    prev_comp = _names(payload.get("competitive_landscape"), "global_players", "regional_players")
    cur_trends = _names(state.get("section_tech"), "trends")
    prev_trends = _names(payload.get("technology_trends"), "trends")

    diff = MoMDiffStructured(
        kpi_deltas=kpi_deltas,
        new_competitors=sorted(cur_comp - prev_comp),
        lost_competitors=sorted(prev_comp - cur_comp),
        new_trends=sorted(cur_trends - prev_trends),
        dropped_trends=sorted(prev_trends - cur_trends),
    )
    narrative = (
        f"Versus the prior period: {len(diff.new_competitors)} new and "
        f"{len(diff.lost_competitors)} dropped competitors, {len(diff.new_trends)} new and "
        f"{len(diff.dropped_trends)} dropped trends, {len(kpi_deltas)} tracked KPIs."
    )
    return {"mom_narrative": narrative, "mom_diff": diff}


async def enrich_with_prior_metrics_node(
    state: Any, config: RunnableConfig, *, store: Store
) -> dict[str, Any]:
    """Attach prior-period metrics onto each current competitor profile (for MoM columns)."""
    section = state.get("section_competitive")
    if section is None:
        return {}
    prev = store.fetch_previous_report(state.get("period", ""))
    if prev is None:
        return {}
    payload, _ = prev
    prior_comp = payload.get("competitive_landscape", {})
    prior_by_key: dict[str, dict[str, Any]] = {}
    for group in ("global_players", "regional_players"):
        for p in prior_comp.get(group, []):
            key = p.get("slug") or p.get("name")
            if key:
                prior_by_key[key] = p

    def _enriched(players: list[Any]) -> list[Any]:
        out = []
        for p in players:
            prior = prior_by_key.get(p.slug or p.name)
            if prior is None:
                out.append(p)
                continue
            out.append(
                p.model_copy(
                    update={
                        "prior_month_followers": prior.get("ig_followers_count"),
                        "prior_month_web_visits": (prior.get("web") or {}).get("monthly_visits"),
                        "prior_month_active_ads": (prior.get("meta_ads") or {}).get(
                            "active_ads_count"
                        ),
                        "prior_month_strategic_moves_count": len(
                            prior.get("strategic_moves_recent", [])
                        ),
                    }
                )
            )
        return out

    updated = section.model_copy(
        update={
            "global_players": _enriched(section.global_players),
            "regional_players": _enriched(section.regional_players),
        }
    )
    return {"section_competitive": updated}


async def store_report_node(state: Any, config: RunnableConfig, *, store: Store) -> dict[str, Any]:
    """Persist the finished report for the next period's comparison + the reports index."""
    report = state.get("report")
    if report is None or state.get("qa_status") == "fail":
        return {}
    try:
        store.save_report(report)
        store.register_report(
            report_id=report.report_id,
            title=f"Market intelligence {report.period}",
            report_type="annual" if report.period_type == "annual" else "monthly",
            period_label=report.period,
            status="published",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("store_report_failed", error=str(exc)[:200])
    return {}
