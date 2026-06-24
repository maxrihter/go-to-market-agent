"""Markdown emitter: the headline deliverable.

Renders the neutral RenderModel IR to GitHub-flavored Markdown. `render_markdown` lowers a
MarketReport and emits in one call. All cell values are escaped before going into tables,
since they originate from LLM output that can contain pipes or newlines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .render_model import (
    CompetitorCard,
    Heatmap,
    RenderModel,
    TimelineItem,
    to_render_model,
)

if TYPE_CHECKING:
    from ...models.report import MarketReport
    from .render_model import Recommendation, Section


_ARROW = {"up": "▲", "down": "▼", "flat": "→", "na": ""}


def _cell(value: object) -> str:
    """Escape a value for a GFM table cell (pipes, backslashes, newlines)."""
    s = str(value)
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def _oneline(value: object) -> str:
    """Collapse newlines for a heading or callout (no pipe escaping needed)."""
    return str(value).replace("\n", " ").replace("\r", " ").strip()


def render_markdown(report: MarketReport, *, brand_name: str | None = None) -> str:
    """Lower a report to the IR and emit Markdown."""
    return emit(to_render_model(report, brand_name=brand_name))


def emit(model: RenderModel) -> str:
    lines: list[str] = [f"# {_oneline(model.title)}", "", f"Reporting period: {model.period}", ""]
    if model.kpis:
        lines += _kpi_table(model)
    for section in model.sections:
        lines += _section(section)
    return "\n".join(lines).rstrip() + "\n"


def _kpi_table(model: RenderModel) -> list[str]:
    out = ["## Scoreboard", "", "| Metric | Value | Change |", "| --- | --- | --- |"]
    for k in model.kpis:
        arrow = _ARROW.get(k.direction, "")
        delta = f"{arrow} {k.delta}".strip() if k.delta else (arrow or "")
        out.append(f"| {_cell(k.label)} | {_cell(k.value)} | {_cell(delta)} |")
    out.append("")
    return out


def _section(section: Section) -> list[str]:
    out = [f"## {_oneline(section.title)}", ""]
    if section.body:
        out += [section.body, ""]
    for c in section.callouts:
        out.append(f"> {_oneline(c)}")
    if section.callouts:
        out.append("")
    cards = section.extras.get("cards")
    if cards:
        out += _cards(cards)
    heatmap = section.extras.get("heatmap")
    if isinstance(heatmap, Heatmap):
        out += _heatmap(heatmap)
    timeline = section.extras.get("timeline")
    if timeline:
        out += _timeline(timeline)
    recs = section.extras.get("recommendations")
    if recs:
        out += _recs(recs)
    sources = section.extras.get("sources")
    if sources:
        out += _sources(sources)
    return out


def _competitor_table(cards: list[CompetitorCard]) -> list[str]:
    """One consolidated metrics table: competitors as rows, shared tile labels as columns."""
    labels = [t.label for t in cards[0].tiles]
    out = [
        "**Competitor metrics**",
        "",
        "| Competitor | " + " | ".join(_cell(label) for label in labels) + " |",
        "| --- | " + " | ".join("---" for _ in labels) + " |",
    ]
    for c in cards:
        vals = {t.label: t.value for t in c.tiles}
        cells = " | ".join(_cell(vals.get(label, "")) for label in labels)
        name = _cell(c.name) + (f" ({_cell(c.threat)})" if c.threat else "")
        out.append(f"| {name} | {cells} |")
    out.append("")
    return out


def _cards(cards: list[CompetitorCard]) -> list[str]:
    out: list[str] = []
    carded = [c for c in cards if c.tiles]
    if len(carded) >= 2:
        # Lead with one consolidated metrics table, then qualitative notes per competitor.
        out += _competitor_table(carded)
        for card in cards:
            threat = f" ({_oneline(card.threat)} threat)" if card.threat else ""
            out += [f"### {_oneline(card.name)}{threat}", ""]
            for n in card.notes:
                out.append(f"- {_oneline(n)}")
            if card.notes:
                out.append("")
        return out
    for card in cards:
        threat = f" ({_oneline(card.threat)} threat)" if card.threat else ""
        out += [f"### {_oneline(card.name)}{threat}", ""]
        if card.tiles:
            out.append(" | ".join(_cell(t.label) for t in card.tiles))
            out.append(" | ".join("---" for _ in card.tiles))
            out.append(" | ".join(_cell(t.value) for t in card.tiles))
            out.append("")
        for n in card.notes:
            out.append(f"- {_oneline(n)}")
        if card.notes:
            out.append("")
    return out


def _heatmap(h: Heatmap) -> list[str]:
    if not h.cols or not h.rows:
        return []
    out = ["### Trend maturity", "", "| Trend | " + " | ".join(_cell(c) for c in h.cols) + " |"]
    out.append("| --- | " + " | ".join("---" for _ in h.cols) + " |")
    for label, row in zip(h.rows, h.values, strict=True):
        out.append(f"| {_cell(label)} | " + " | ".join(_cell(v) for v in row) + " |")
    out.append("")
    return out


def _timeline(items: list[TimelineItem]) -> list[str]:
    out = ["### Strategic moves", ""]
    for it in items:
        detail = f": {_oneline(it.detail)}" if it.detail else ""
        out.append(f"- {_oneline(it.when)} {_oneline(it.label)}{detail}")
    out.append("")
    return out


def _recs(recs: list[Recommendation]) -> list[str]:
    out = ["| Priority | ICE | Horizon | Effort | Action |", "| --- | --- | --- | --- | --- |"]
    for r in recs:
        out.append(
            f"| {_cell(r.priority)} | {r.ice} | {_cell(r.horizon)} | "
            f"{_cell(r.effort)} | {_cell(r.action)} |"
        )
    out.append("")
    return out


def _sources(sources: list) -> list[str]:  # list[SourceRef]
    out = ["### Sources", ""]
    for s in sources:
        title = _oneline(getattr(s, "title", ""))
        url = getattr(s, "url", "")
        out.append(f"- {title} ({url})" if url else f"- {title}")
    out.append("")
    return out
