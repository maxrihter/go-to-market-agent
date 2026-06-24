"""RenderModel: a format-neutral intermediate representation of the report.

The assembled `MarketReport` (rich Pydantic models) is lowered once into this neutral
block IR via `to_render_model`; each output adapter (markdown, html, notion, and any
plugin) then emits from the IR. This is what lets the same report render to a local
Markdown file, an HTML page, or a Notion page without three copies of the layout logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models.report import CompetitorProfile, MarketReport, MarketSizingPoint


@dataclass(slots=True)
class KpiTile:
    label: str
    value: str
    delta: str | None = None
    direction: str = "flat"  # up | down | flat | na


@dataclass(slots=True)
class CompetitorCard:
    name: str
    threat: str | None = None
    tiles: list[KpiTile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Heatmap:
    """Trend x competitor maturity grid."""

    rows: list[str] = field(default_factory=list)  # trends
    cols: list[str] = field(default_factory=list)  # competitors
    values: list[list[str]] = field(default_factory=list)  # row-major cells


@dataclass(slots=True)
class TimelineItem:
    label: str
    when: str
    detail: str | None = None


@dataclass(slots=True)
class Recommendation:
    priority: str
    action: str
    ice: int
    horizon: str
    effort: str
    rationale: str = ""
    owner: str | None = None


@dataclass(slots=True)
class Section:
    key: str
    title: str
    body: str = ""
    callouts: list[str] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)  # cards / heatmap / timeline / recs


@dataclass(slots=True)
class RenderModel:
    """The whole report as neutral blocks."""

    title: str
    period: str
    kpis: list[KpiTile] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Lowering helpers
# ---------------------------------------------------------------------------


def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "n/a"


def _fmt_pct(x: float | None) -> str:
    return f"{x:.1f}%" if isinstance(x, (int, float)) else "n/a"


def _competitor_card(p: CompetitorProfile) -> CompetitorCard:
    tiles = [
        KpiTile("Followers", _fmt_int(p.ig_followers_count)),
        KpiTile("Posts/30d", _fmt_int(p.ig_posts_last_30d)),
        KpiTile(
            "ER",
            _fmt_pct(p.ig_avg_engagement_rate * 100)
            if p.ig_avg_engagement_rate is not None
            else "n/a",
        ),
        KpiTile("Growth 90d", _fmt_pct(p.ig_follower_growth_90d_pct)),
    ]
    notes = [f"Strength: {s}" for s in p.strengths[:3]] + [f"Watch: {c}" for c in p.cautions[:3]]
    return CompetitorCard(name=p.name, threat=p.threat_level, tiles=tiles, notes=notes)


def _heatmap(report: MarketReport) -> Heatmap | None:
    trends = report.technology_trends.trends
    if not trends:
        return None
    cols: list[str] = []
    for t in trends:
        for m in t.competitor_maturities:
            if m.competitor_slug not in cols:
                cols.append(m.competitor_slug)
    if not cols:
        return None
    rows = [t.trend_name for t in trends]
    values: list[list[str]] = []
    for t in trends:
        score_by_slug = {m.competitor_slug: str(m.maturity_score) for m in t.competitor_maturities}
        values.append([score_by_slug.get(c, "-") for c in cols])
    return Heatmap(rows=rows, cols=cols, values=values)


def _timeline(report: MarketReport) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    players = (
        report.competitive_landscape.global_players + report.competitive_landscape.regional_players
    )
    for p in players:
        for mv in p.strategic_moves_recent:
            items.append(
                TimelineItem(label=p.name, when=mv.move_date.isoformat(), detail=mv.headline)
            )
    items.sort(key=lambda i: i.when, reverse=True)
    return items[:12]


def _sizing_line(prefix: str, sizing: MarketSizingPoint | None) -> str:
    if sizing is None:
        return ""
    cagr = f", CAGR {sizing.cagr_percent}%" if sizing.cagr_percent else ""
    return (
        f"{prefix} ({sizing.segment}): {sizing.size_value} {sizing.size_unit} "
        f"{sizing.size_currency} ({sizing.year}{cagr})"
    )


def _join(parts: list[str]) -> str:
    return "\n\n".join(p for p in parts if p)


def _bullets(title: str, items: list[str]) -> str:
    """A titled bullet block, or empty string when there are no items."""
    if not items:
        return ""
    return f"{title}:\n" + "\n".join(f"- {i}" for i in items)


# ---------------------------------------------------------------------------
# Lowering
# ---------------------------------------------------------------------------


def to_render_model(report: MarketReport, *, brand_name: str | None = None) -> RenderModel:
    """Lower a MarketReport into the neutral block IR."""
    title = f"{brand_name}: Market Intelligence" if brand_name else "Market Intelligence Report"

    kpis = [
        KpiTile(label=k.label, value=k.value, delta=k.delta, direction=k.delta_direction)
        for k in report.scoreboard.hero_kpis
    ]

    sections: list[Section] = []
    es = report.executive_summary
    sections.append(
        Section(
            key="executive_summary",
            title="Executive summary",
            body=_join(
                [
                    es.headline or "",
                    es.situation,
                    es.complication,
                    es.resolution,
                    "\n".join(f"- {f}" for f in es.key_findings),
                    _bullets("Tectonic shifts", [t.narrative for t in es.tectonic_shifts]),
                    _bullets("Watch list", es.watch_list),
                ]
            ),
            callouts=[s.name for s in es.strategic_windows],
        )
    )

    gm = report.global_market
    sections.append(
        Section(
            key="global_market",
            title="Global market",
            body=_join(
                [
                    gm.conclusion or "",
                    _sizing_line("Total market", gm.global_market_sizing),
                    *[_sizing_line("Segment", s) for s in gm.primary_segment_sizing],
                    _sizing_line("Adjacent", gm.adjacent_segment_sizing),
                ]
            ),
        )
    )

    rp = report.regional_pulse
    sections.append(
        Section(
            key="regional_pulse",
            title="Regional pulse",
            body=_join(
                [
                    rp.conclusion,
                    "\n".join(
                        f"- {f.company}: {f.event_type} {f.amount or ''}".rstrip()
                        for f in rp.funding_events
                    ),
                    "\n".join(
                        f"- {r.topic} ({r.severity}): {r.summary}" for r in rp.regulatory_updates
                    ),
                ]
            ),
        )
    )

    cl = report.competitive_landscape
    cards = [_competitor_card(p) for p in cl.global_players + cl.regional_players]
    sections.append(
        Section(
            key="competitive_landscape",
            title="Competitive landscape",
            body=_join(
                [cl.conclusion or "", cl.social_synthesis or "", cl.ad_library_patterns or ""]
            ),
            extras={"cards": cards, "timeline": _timeline(report)},
        )
    )

    bp = report.brand_positioning
    sections.append(
        Section(
            key="brand_positioning",
            title="Brand positioning",
            body=_join(
                [
                    bp.conclusion,
                    bp.quadrant_position,
                    bp.sentiment_summary or "",
                    "Strengths:\n" + "\n".join(f"- {s}" for s in bp.strengths),
                    "Weaknesses:\n" + "\n".join(f"- {w}" for w in bp.weaknesses),
                    "Implications:\n" + "\n".join(f"- {i}" for i in bp.implications),
                ]
            ),
        )
    )

    cs = report.consumer_signals
    sections.append(
        Section(
            key="consumer_signals",
            title="Consumer signals",
            body=_join(
                [
                    cs.conclusion,
                    cs.audience_adoption,
                    cs.seasonal_context,
                    cs.social_trend_rollup or "",
                ]
            ),
        )
    )

    tt = report.technology_trends
    sections.append(
        Section(
            key="technology_trends",
            title="Technology trends",
            body=_join([tt.conclusion, *[f"- {t.trend_name}: {t.description}" for t in tt.trends]]),
            extras={"heatmap": _heatmap(report)},
        )
    )

    sr = report.strategic_recommendations
    rec_source = list(sr.monthly_tactical)
    if report.period_type == "annual":
        rec_source += list(sr.annual_strategy_candidates)
    recs = [
        Recommendation(
            priority=r.priority,
            action=r.action,
            ice=r.ice_total,
            horizon=r.horizon,
            effort=r.effort_estimate,
            rationale=r.rationale,
            owner=r.owner_role,
        )
        for r in rec_source
    ]
    recs.sort(key=lambda r: r.ice, reverse=True)
    sections.append(
        Section(
            key="strategic_recommendations",
            title="Strategic recommendations",
            body=report.strategic_recommendations.conclusion or "",
            extras={"recommendations": recs},
        )
    )

    ap = report.appendix
    sections.append(
        Section(
            key="appendix",
            title="Appendix",
            body=_join(
                [
                    ap.methodology,
                    ap.confidence_legend,
                    ap.what_changed_since_last_period or "",
                    "\n".join(f"- {limit}" for limit in ap.known_limitations),
                ]
            ),
            extras={"sources": ap.all_sources_referenced},
        )
    )

    return RenderModel(title=title, period=report.period, kpis=kpis, sections=sections)
