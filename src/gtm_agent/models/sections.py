"""Shared report primitives: citations, chart/table/callout specs, KPI tiles.

These are the building blocks the section models compose. They are output-neutral:
the RenderModel IR (integrations/output/render_model.py) lowers them for each emitter.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..urls import is_fake_source_url

ConfidenceTier = Literal["H", "M", "L"]  # High, Medium, Low
CredibilityTier = Literal["tier_1", "tier_2", "tier_3", "tier_4", "unknown"]


class SourceRef(BaseModel):
    """A citation, shown inline and in the appendix Sources section.

    `credibility_score` / `credibility_tier` are assigned by the source curator from a
    domain whitelist; the fact-checker uses them to down-weight weakly-sourced claims.
    """

    title: str
    url: str
    publisher: str | None = None
    date_accessed: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    credibility_score: float = Field(default=0.5, ge=0.0, le=1.0)
    credibility_tier: CredibilityTier = "unknown"

    @field_validator("url")
    @classmethod
    def _url_must_be_real_http(cls, v: str) -> str:
        """Normalize fake / malformed URLs to empty (fail-soft, never raise).

        A hard rejection here would cascade: one fabricated URL in a structured-output
        call would fail the whole section. Instead the SourceRef survives with an empty
        url, which the aggregator and validator surface downstream.
        """
        if not v:
            return ""
        if not v.startswith(("http://", "https://")):
            return ""
        if is_fake_source_url(v):
            return ""
        return v


# ---------------------------------------------------------------------------
# Chart / table / callout rendering specs
# ---------------------------------------------------------------------------

ChartType = Literal["column", "bar", "line", "donut", "number"]
ChartAggregator = Literal["sum", "count", "average", "min", "max"]
ChartColorTheme = Literal[
    "blue", "gray", "yellow", "green", "purple", "teal", "orange", "pink", "red", "auto", "colorful"
]
ChartHeight = Literal["small", "medium", "large", "extra_large"]


class ChartDataRow(BaseModel):
    """One row of data backing a chart."""

    properties: dict[str, Any]


class ChartSpec(BaseModel):
    """A chart specification, rendered to a local image or an output-adapter native chart."""

    chart_type: ChartType
    title: str
    caption: str | None = None
    property_schema: dict[str, Literal["title", "number", "select", "date", "rich_text"]]
    data: list[ChartDataRow]
    x_axis_property: str
    y_axis_property: str
    aggregator: ChartAggregator = "sum"
    color_theme: ChartColorTheme = "blue"
    height: ChartHeight = "medium"
    show_data_labels: bool = True
    # Populated by an output adapter that needs to back the chart with a data store.
    supporting_db_id: str | None = None
    supporting_view_id: str | None = None


class TableSpec(BaseModel):
    """A table with optional column widths."""

    caption: str | None = None
    headers: list[str]
    rows: list[list[str]]
    column_widths: list[int] | None = None

    @field_validator("rows")
    @classmethod
    def rows_match_headers(cls, v: list[list[str]], info: Any) -> list[list[str]]:
        expected = len(info.data.get("headers", []))
        if expected and any(len(r) != expected for r in v):
            msg = f"row widths must match headers (expected {expected})"
            raise ValueError(msg)
        return v


CalloutIcon = Literal[
    "💡",
    "⚠️",
    "📊",
    "🎯",
    "🔑",
    "📈",
    "📉",
    "✅",
    "ℹ️",
    "🔴",
    "🔶",
    "🟠",
    "🟡",
    "🟢",
    "🔵",
]


class CalloutSpec(BaseModel):
    """A callout block highlighting a takeaway or warning."""

    icon: CalloutIcon = "💡"
    text: str
    color: Literal["default", "gray", "blue", "green", "yellow", "red", "purple"] = "blue"


# ---------------------------------------------------------------------------
# KPI + history primitives
# ---------------------------------------------------------------------------


class KPITile(BaseModel):
    """A single hero KPI, rendered as a number tile."""

    label: str
    value: str
    delta: str | None = None
    delta_direction: Literal["up", "down", "flat", "na"] = "na"
    footnote: str | None = None


class MonthlyValueSeries(BaseModel):
    """A labeled metric with its per-period values, rendered as a wide history row."""

    label: str = Field(min_length=2, max_length=120)
    monthly_values: dict[str, str] = Field(default_factory=dict)
    unit: str | None = None
    currency: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    earliest_period: str | None = None
    latest_period: str | None = None
    notes: str | None = None


class ReportRef(BaseModel):
    """A reference to a prior report, for cross-period navigation and history."""

    report_id: str
    period_label: str
    period_type: Literal["annual", "monthly"]
    page_url: str | None = None
    published_at: Any | None = None  # date, kept loose for store round-trips
    key_metrics: dict[str, str] = Field(default_factory=dict)
