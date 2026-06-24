"""The report schema: ten section models, the MoM diff, the QA verdict, and the root.

This is the engine's native object. The output-facing deliverable (Markdown / HTML /
Notion) is rendered from it via the RenderModel IR. Narrative fields are in the report
language (set per tenant); there is no language-locked validation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .competitor import (
    AdCreativeSummary,
    AppStoreSignals,
    CompositeRetentionIndex,
    ContentMix,
    EngagementMetrics,
    EventRecord,
    FollowerSnapshot,
    QualitativeProfile,
    RatingTrajectoryPoint,
    SeoSnapshot,
    StrategicMove,
    TrendMaturity,
    WebAnalytics,
)
from .sections import (
    CalloutSpec,
    ChartSpec,
    ConfidenceTier,
    KPITile,
    MonthlyValueSeries,
    ReportRef,
    SourceRef,
    TableSpec,
)

# ---------------------------------------------------------------------------
# Section 0: Scoreboard
# ---------------------------------------------------------------------------


class Scoreboard(BaseModel):
    """Section 0: cover plus a KPI scoreboard with BLUF bullets."""

    period: str  # "2026-04"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    version: str = "v2.0"
    bluf_bullets: list[str] = Field(description="5-7 one-line key findings for the BLUF opener")
    hero_kpis: list[KPITile] = Field(description="3-5 top-level KPIs for the scorecard row")
    kpi_series: list[MonthlyValueSeries] = Field(default_factory=list)

    @field_validator("generated_at")
    @classmethod
    def _generated_at_within_window(cls, v: datetime) -> datetime:
        """Reject a stale `generated_at` from LLM fabrication; normalize to now."""
        now = datetime.now(tz=UTC)
        if abs((now - v).total_seconds()) > 7 * 24 * 3600:
            return now
        return v

    @field_validator("bluf_bullets")
    @classmethod
    def _bullets_count(cls, v: list[str]) -> list[str]:
        if not 3 <= len(v) <= 8:
            msg = f"BLUF bullets should be 3-8, got {len(v)}"
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# Section 1: Executive summary
# ---------------------------------------------------------------------------


class StrategicWindow(BaseModel):
    """A time-bounded opportunity (opening or closing)."""

    name: str = Field(min_length=10, max_length=120)
    description: str = Field(min_length=20, max_length=400)
    closure_timing: str = Field(min_length=4, max_length=80)
    urgency: Literal["high", "medium", "low"] = "medium"
    evidence_section_refs: list[str] = Field(default_factory=list)


class TectonicShift(BaseModel):
    """A major narrative pivot of the period (a structured 'what changed' item)."""

    name: str = Field(min_length=10, max_length=120)
    narrative: str = Field(min_length=30, max_length=600)
    severity: Literal["high", "medium", "low"] = "medium"
    evidence_section_refs: list[str] = Field(default_factory=list)


class ExecutiveSummary(BaseModel):
    """Section 1: an SCR-framework summary with confidence-tagged findings."""

    situation: str = Field(description="1-2 sentences, neutral market state")
    complication: str = Field(description="The main change / threat / opportunity")
    resolution: str = Field(description="The recommended strategic direction")
    key_findings: list[str] = Field(description="5 findings with [H/M/L] tags inline")
    hero_chart: ChartSpec | None = None
    tectonic_shifts: list[TectonicShift] = Field(default_factory=list)
    strategic_windows: list[StrategicWindow] = Field(default_factory=list)
    yoy_highlights: list[str] = Field(default_factory=list)  # annual only
    h2_outlook: list[str] = Field(default_factory=list)  # annual only
    headline: str | None = Field(default=None, description="One-sentence story of the period")
    watch_list: list[str] = Field(default_factory=list)

    @field_validator("headline")
    @classmethod
    def _headline_length(cls, v: str | None) -> str | None:
        """Drop a stub-like or over-long headline (render skips None gracefully)."""
        if not v:
            return None
        if len(v) < 60 or len(v) > 220:
            return None
        return v

    @field_validator("watch_list")
    @classmethod
    def _watch_list_cap(cls, v: list[str]) -> list[str]:
        """Drop too-short stubs and cap to 8 for a bounded render."""
        return [item for item in v if isinstance(item, str) and len(item) >= 20][:8]


# ---------------------------------------------------------------------------
# Section 2-3: Market sizing
# ---------------------------------------------------------------------------


class MarketSizingPoint(BaseModel):
    """A single authoritative market number with its source."""

    segment: str
    size_value: float
    size_currency: Literal["USD", "EUR", "GBP", "JPY", "CNY", "INR", "other"] = "USD"
    size_unit: Literal["billion", "million", "thousand"] = "billion"
    year: int
    cagr_percent: float | None = None
    forecast_year: int | None = None
    sources: list[SourceRef]
    confidence: ConfidenceTier = "M"

    @field_validator("year")
    @classmethod
    def _year_must_be_recent(cls, v: int) -> int:
        """Reject sizing numbers older than ~2 years (likely a training-cutoff leak)."""
        current_year = datetime.now(tz=UTC).year
        if v < current_year - 2:
            msg = (
                f"MarketSizingPoint.year={v} is too stale for a {current_year} report. "
                f"Cite fresher data or omit the point."
            )
            raise ValueError(msg)
        if v > current_year + 5:
            msg = f"MarketSizingPoint.year={v} is unrealistically future-dated."
            raise ValueError(msg)
        return v


class FundingEvent(BaseModel):
    """A funding round / M&A / IPO event worth mentioning."""

    company: str
    country: str
    event_type: Literal["funding", "m_and_a", "ipo", "exit", "partnership", "product_launch"]
    amount: str | None = None
    date: str
    implication: str  # what it means for us
    sources: list[SourceRef]
    confidence: ConfidenceTier = "M"


class RegulatoryUpdate(BaseModel):
    """A policy / regulation change affecting the market."""

    topic: str
    date: str
    summary: str
    impact_for_brand: str  # direct operational implication
    sources: list[SourceRef]
    confidence: ConfidenceTier = "M"
    severity: Literal["P0", "P1", "P2", "positive"] = "P2"


class GlobalMarketLandscape(BaseModel):
    """Section 2: global market sizing and geographic breakdown."""

    conclusion: str | None = None
    global_market_sizing: MarketSizingPoint
    primary_segment_sizing: list[MarketSizingPoint]
    adjacent_segment_sizing: MarketSizingPoint | None = None
    geographic_breakdown: TableSpec | None = None
    growth_trajectory_chart: ChartSpec | None = None
    segment_breakdown_chart: ChartSpec | None = None
    callout: CalloutSpec | None = None


class RegionalMarketPulse(BaseModel):
    """Section 3: the regional market, funding, and regulatory pulse."""

    conclusion: str = Field(min_length=20)
    regional_market_sizing: MarketSizingPoint | None = None
    regional_segment_sizing: MarketSizingPoint | None = None
    funding_events: list[FundingEvent] = Field(default_factory=list)
    regulatory_updates: list[RegulatoryUpdate] = Field(default_factory=list)
    funding_summary_chart: ChartSpec | None = None
    callout: CalloutSpec | None = None


# ---------------------------------------------------------------------------
# Section 4: Competitive landscape
# ---------------------------------------------------------------------------


class CompetitorProfile(BaseModel):
    """A per-brand deep profile for the competitive landscape.

    All fields beyond identity are optional: prompts fill what is available and the
    renderer shows "data unavailable" for None. Nothing is fabricated. The flat fields
    are legacy aliases the renderer still reads; the structured equivalents are preferred.
    """

    # Identity (legacy flat)
    name: str
    username: str | None = None
    country_hq: str
    website_url: str | None = None
    funding_total: str | None = None
    last_known_round: str | None = None
    positioning: str = ""

    ig_followers_count: int | None = None
    ig_posts_last_30d: int | None = None
    ig_avg_engagement_rate: float | None = None
    organic_monthly_visits_est: str | None = None
    mobile_app_installs_est: str | None = None
    mobile_app_rating: float | None = None
    ad_campaigns_active_count: int | None = None
    ad_spend_range_monthly: str | None = None

    strategic_moves_period: list[str] = Field(default_factory=list)
    ig_activity_summary: str | None = None
    ad_patterns_summary: str | None = None

    # A. Identity (structured)
    slug: str | None = None
    legal_name: str | None = None
    founded_year: int | None = None
    employee_count_estimate: int | None = Field(default=None, ge=0)
    employee_trend_qoq_pct: float | None = None
    geographies_served: list[str] = Field(default_factory=list)
    target_age_band: str | None = None
    pricing_model: (
        Literal["one_time", "subscription", "freemium", "marketplace", "usage_based", "other"]
        | None
    ) = None
    unit_price: float | None = Field(default=None, ge=0)  # for the 2x2 map X-axis
    certifications: list[str] = Field(default_factory=list)  # e.g. ISO, SOC2, sector certs

    # B. Financials
    total_funding_usd: int | None = Field(default=None, ge=0)
    last_round_date: date | None = None
    last_round_amount_usd: int | None = Field(default=None, ge=0)
    last_round_investors: list[str] = Field(default_factory=list)
    valuation_usd_estimate: int | None = Field(default=None, ge=0)
    arr_usd_estimate: int | None = Field(default=None, ge=0)
    hiring_velocity_per_month: int | None = Field(default=None, ge=0)
    hires_by_function_pct: dict[str, float] = Field(default_factory=dict)
    layoffs_last_180d: bool | None = None

    # C. Audience
    ig_handle: str | None = None
    ig_follower_history: list[FollowerSnapshot] = Field(default_factory=list)
    ig_follower_growth_90d_pct: float | None = None
    ig_follower_growth_30d_pct: float | None = None
    prior_month_followers: int | None = Field(default=None, ge=0)
    prior_month_web_visits: int | None = Field(default=None, ge=0)
    prior_month_active_ads: int | None = Field(default=None, ge=0)
    prior_month_strategic_moves_count: int = Field(default=0, ge=0)
    tiktok_handle: str | None = None
    tiktok_follower_count: int | None = Field(default=None, ge=0)
    youtube_handle: str | None = None
    youtube_subs: int | None = Field(default=None, ge=0)
    audience_region_share_pct: float | None = Field(default=None, ge=0, le=100)

    # D. Engagement
    ig_engagement: EngagementMetrics | None = None
    tiktok_engagement: EngagementMetrics | None = None

    # E. Content
    content_mix_30d: ContentMix | None = None
    posts_per_week: float | None = Field(default=None, ge=0)
    posting_consistency_score: int | None = Field(default=None, ge=0, le=100)
    content_themes: list[str] = Field(default_factory=list)
    top_hashtags: list[str] = Field(default_factory=list, max_length=10)
    ugc_ratio_pct: float | None = Field(default=None, ge=0, le=100)
    brand_voice_signals: str | None = None

    # F. Paid media
    meta_ads: AdCreativeSummary | None = None
    google_ads: AdCreativeSummary | None = None
    tiktok_ads: AdCreativeSummary | None = None

    # G-I. SEO / web / app
    seo: SeoSnapshot | None = None
    web: WebAnalytics | None = None
    app_store: AppStoreSignals | None = None

    # J-K. Trends + moves + activity + qualitative + retention
    trend_maturities: list[TrendMaturity] = Field(default_factory=list)
    strategic_moves_recent: list[StrategicMove] = Field(default_factory=list)
    activity_events: list[EventRecord] = Field(default_factory=list)
    qualitative: QualitativeProfile | None = None
    retention_index: CompositeRetentionIndex | None = None
    rating_trajectory: list[RatingTrajectoryPoint] = Field(default_factory=list)

    # L. Positioning
    icp: str | None = None
    anti_positioning: str | None = None
    strengths: list[str] = Field(default_factory=list, max_length=5)
    cautions: list[str] = Field(default_factory=list, max_length=5)
    threat_level: Literal["direct", "adjacent", "indirect"] | None = None

    # M. Metadata
    profile_updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    data_completeness_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    sources_used: list[str] = Field(default_factory=list)

    confidence: ConfidenceTier = "M"
    sources: list[SourceRef] = Field(default_factory=list)


class PositioningMatrix(BaseModel):
    """A 2x2 positioning map, rendered as a chart or table."""

    x_axis_label: str
    y_axis_label: str
    quadrants: list[dict[str, Any]]
    chart: ChartSpec


class CompetitiveLandscape(BaseModel):
    """Section 4: global and regional players, strategic moves, paid + content synthesis."""

    conclusion: str | None = None
    global_players: list[CompetitorProfile] = Field(default_factory=list)
    regional_players: list[CompetitorProfile] = Field(default_factory=list)
    positioning_matrix: PositioningMatrix | None = None
    strategic_moves_table: TableSpec | None = None
    social_synthesis: str | None = None
    ad_library_patterns: str | None = None
    callout: CalloutSpec | None = None
    brand_metrics_history: list[MonthlyValueSeries] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section 5: Brand positioning (the brand the report is written for)
# ---------------------------------------------------------------------------


class BrandPositioning(BaseModel):
    """Section 5: the report's own brand through a strategy lens.

    Entity-hallucination screening (a config-driven `forbidden_entity_keywords` list) is
    applied as a QA gate in the QA phase, not as a model validator.
    """

    conclusion: str = Field(min_length=20)
    quadrant_position: str  # "where we sit on the map" narrative
    strengths: list[str] = Field(description="3-5 bullets")
    weaknesses: list[str] = Field(description="3-5 bullets")
    sentiment_summary: str | None = None
    implications: list[str] = Field(description="Strategic implications for positioning")
    callout: CalloutSpec | None = None


# ---------------------------------------------------------------------------
# Section 6: Consumer signals
# ---------------------------------------------------------------------------


class ConsumerSignals(BaseModel):
    """Section 6: audience adoption trends, search interest, seasonal context."""

    conclusion: str = Field(min_length=20)
    audience_adoption: str  # survey-data narrative
    search_interest_chart: ChartSpec | None = None
    rising_queries_table: TableSpec | None = None
    seasonal_context: str  # calendar / seasonal moments
    social_trend_rollup: str | None = None
    callout: CalloutSpec | None = None

    @field_validator("rising_queries_table", mode="before")
    @classmethod
    def _coerce_rising_queries_table(cls, v: Any) -> Any:
        """Coerce non-conformant LLM input to None instead of failing the whole section."""
        if v is None or isinstance(v, TableSpec):
            return v
        if isinstance(v, dict):
            return v if ("headers" in v and "rows" in v) else None
        return None


# ---------------------------------------------------------------------------
# Section 7: Technology trends
# ---------------------------------------------------------------------------


class TechTrendItem(BaseModel):
    """A single technology / product trend affecting the market."""

    trend_name: str
    trend_slug: str | None = None
    description: str
    relevance_for_brand: str
    example_companies: list[str] = Field(default_factory=list)
    competitor_maturities: list[TrendMaturity] = Field(default_factory=list)
    brand_maturity_score: Literal[0, 1, 2, 3] | None = None
    maturity_gap_narrative: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    confidence: ConfidenceTier = "M"


class TechnologyTrends(BaseModel):
    """Section 7: technology and product trends, with a maturity grid."""

    conclusion: str = Field(min_length=20)
    trends: list[TechTrendItem]
    callout: CalloutSpec | None = None
    trend_maturity_history: list[MonthlyValueSeries] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section 8: Strategic recommendations
# ---------------------------------------------------------------------------


class StrategicRecommendation(BaseModel):
    """An ICE-scored, horizon-tagged, evidence-linked recommendation.

    `competitor_move_refs` (URLs backing the rec) is expected for categories that are
    competitor-reactive (paid / content / positioning); the QA gate enforces that.
    Entity-hallucination screening (config-driven `forbidden_entity_keywords`) is applied
    as a QA gate in the QA phase, not as a model validator.
    """

    priority: Literal["P0", "P1", "P2"]
    horizon: Literal["month", "quarter", "year"]
    category: Literal["content", "positioning", "collaboration", "paid", "product", "timing"]
    action: str
    rationale: str  # references the supporting section
    effort_estimate: Literal["XS", "S", "M", "L"]
    success_metric: str
    confidence: ConfidenceTier = "M"
    impact: int = Field(default=5, ge=1, le=10)
    confidence_score: int = Field(default=5, ge=1, le=10)
    ease: int = Field(default=5, ge=1, le=10)
    ice_total: int = Field(default=125, ge=1, le=1000)
    owner_role: str | None = None
    target_quarter: str | None = None
    evidence_section_refs: list[str] = Field(default_factory=list)
    competitor_move_refs: list[str] = Field(default_factory=list)

    @field_validator("evidence_section_refs")
    @classmethod
    def _evidence_refs_nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            msg = "evidence_section_refs must contain at least one section reference"
            raise ValueError(msg)
        return v

    @field_validator("competitor_move_refs")
    @classmethod
    def _real_move_urls(cls, v: list[str]) -> list[str]:
        from ..urls import is_fake_source_url

        return [
            url
            for url in v
            if url.startswith(("http://", "https://")) and not is_fake_source_url(url)
        ]

    @model_validator(mode="after")
    def _compute_ice_total(self) -> StrategicRecommendation:
        computed = self.impact * self.confidence_score * self.ease
        if self.ice_total != computed:
            object.__setattr__(self, "ice_total", computed)
        return self

    @model_validator(mode="after")
    def _validate_effort_vs_category(self) -> StrategicRecommendation:
        if self.category == "product" and self.effort_estimate in ("XS", "S"):
            msg = (
                f"Effort '{self.effort_estimate}' is too low for category 'product'. "
                f"Product recs require at least M. Upgrade effort or reframe the category."
            )
            raise ValueError(msg)
        return self


class StrategicRecommendations(BaseModel):
    """Section 8: tactical recommendations plus longer-horizon strategy candidates."""

    conclusion: str | None = None
    monthly_tactical: list[StrategicRecommendation] = Field(default_factory=list)
    annual_strategy_candidates: list[StrategicRecommendation] = Field(default_factory=list)
    callout: CalloutSpec | None = None


# ---------------------------------------------------------------------------
# Section 9: Appendix + MoM diff
# ---------------------------------------------------------------------------


class KPIDelta(BaseModel):
    """A single KPI value transition between the prior and current period."""

    label: str
    prev_value: str
    curr_value: str
    delta_pct: float | None = None
    direction: Literal["up", "down", "flat", "na"] = "na"


class ThreatTransition(BaseModel):
    """A single brand's threat-tier transition between periods."""

    brand_slug: str
    brand_name: str
    prev_threat: str | None = None
    curr_threat: str | None = None
    change_direction: Literal["upgraded", "downgraded", "stable", "new", "lost"] = "stable"


class MoMDiffStructured(BaseModel):
    """A structured month-over-month diff, stored in the appendix for the render layer."""

    kpi_deltas: list[KPIDelta] = Field(default_factory=list)
    new_competitors: list[str] = Field(default_factory=list)
    lost_competitors: list[str] = Field(default_factory=list)
    new_trends: list[str] = Field(default_factory=list)
    dropped_trends: list[str] = Field(default_factory=list)
    threat_transitions: list[ThreatTransition] = Field(default_factory=list)
    rec_category_mix_prev: dict[str, int] = Field(default_factory=dict)
    rec_category_mix_curr: dict[str, int] = Field(default_factory=dict)
    sizing_delta_pct: float | None = None
    is_first_period: bool = False
    prev_schema_incompatible: bool = False


class AppendixSection(BaseModel):
    """Section 9: methodology, confidence legend, limitations, sources, MoM diff."""

    methodology: str
    confidence_legend: str
    what_changed_since_last_period: str | None = None
    known_limitations: list[str] = Field(default_factory=list)
    all_sources_referenced: list[SourceRef]
    mom_diff_structured: MoMDiffStructured | None = None


# ---------------------------------------------------------------------------
# Pre-publish QA verdict
# ---------------------------------------------------------------------------


class QAIssue(BaseModel):
    """A single QA issue raised by the pre-publish reviewer."""

    section: str
    severity: Literal["critical", "high", "medium", "low"]
    issue_type: Literal[
        "fabricated_url",
        "missing_data",
        "wrong_period",
        "narrative_quality",
        "structural_error",
        "data_inconsistency",
        "boilerplate",
        "other",
    ]
    description: str = Field(min_length=15, max_length=500)
    suggested_fix: str | None = None


class QAVerdict(BaseModel):
    """The pre-publish QA reviewer's verdict.

    The pipeline halts on `rejected`, retries once on `needs_revision`, and continues to
    publish on `approved`.
    """

    decision: Literal["approved", "needs_revision", "rejected"]
    issues: list[QAIssue] = Field(default_factory=list)
    summary: str | None = Field(default=None, max_length=2000)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
    model_used: str = ""
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Root report
# ---------------------------------------------------------------------------


class MarketReport(BaseModel):
    """A complete market-intelligence report. Rendered to the configured output(s)."""

    report_id: str  # "report-{period}", e.g. "report-2026-04"
    period: str  # YYYY-MM
    quarter: str | None = None
    language: str = "en"

    scoreboard: Scoreboard
    executive_summary: ExecutiveSummary
    global_market: GlobalMarketLandscape
    regional_pulse: RegionalMarketPulse
    competitive_landscape: CompetitiveLandscape
    brand_positioning: BrandPositioning
    consumer_signals: ConsumerSignals
    technology_trends: TechnologyTrends
    strategic_recommendations: StrategicRecommendations
    appendix: AppendixSection

    period_type: Literal["month", "quarter", "annual"] = "month"
    period_start: date | None = None
    period_end: date | None = None

    prior_reports: list[ReportRef] = Field(default_factory=list)
    qa_verdict: QAVerdict | None = None
    schema_version: int = 5
    prev_feedback_digest: str | None = None
    run_metrics: object | None = None

    generated_at: datetime = Field(default_factory=lambda: datetime.now(tz=UTC))
