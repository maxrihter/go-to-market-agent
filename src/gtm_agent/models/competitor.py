"""Competitor intelligence: nested models for per-brand profiles.

Consumed by CompetitorProfile (the per-brand profile), TechTrendItem (trend maturity),
and StrategicRecommendation (move citations). Numeric fields default to None because
data unavailability is the baseline, not the exception. Narrative fields are in the
report language (set per tenant); there is no language-locked validation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..urls import is_fake_source_url

# ---------------------------------------------------------------------------
# Audience + content
# ---------------------------------------------------------------------------

FollowerSource = Literal["apify", "manual", "similarweb", "other"]


class FollowerSnapshot(BaseModel):
    """One point in a follower time series, feeding growth-velocity computation."""

    snapshot_date: date
    follower_count: int = Field(ge=0)
    source: FollowerSource = "apify"


class ContentMix(BaseModel):
    """30-day content-format mix for a competitor's primary social account.

    Reels / Carousels / Stories / Static must sum to 100 (plus or minus 1 for rounding).
    """

    reels_pct: float = Field(ge=0, le=100)
    carousels_pct: float = Field(ge=0, le=100)
    stories_pct: float = Field(ge=0, le=100)
    static_pct: float = Field(ge=0, le=100)

    @field_validator("static_pct")
    @classmethod
    def _sum_approx_100(cls, v: float, info: Any) -> float:
        d = info.data
        total = d.get("reels_pct", 0) + d.get("carousels_pct", 0) + d.get("stories_pct", 0) + v
        if abs(total - 100.0) > 1.0:
            msg = f"ContentMix percentages must sum to ~100, got {total:.1f}"
            raise ValueError(msg)
        return v


class EngagementMetrics(BaseModel):
    """Post-level engagement rollup over a ~30-day window.

    `avg_er_pct` is the only required field; the rest are opt-in because reach / saves /
    non-follower reach are only available through business APIs, not public scrapers.
    Caps are deliberately loose: a viral post can exceed 100% post-level ER when reach
    exceeds the follower base.
    """

    avg_er_pct: float = Field(ge=0, le=100)
    avg_save_rate_pct: float | None = Field(default=None, ge=0, le=100)
    avg_share_rate_pct: float | None = Field(default=None, ge=0, le=100)
    avg_reach_rate_pct: float | None = Field(default=None, ge=0, le=2000)
    non_follower_reach_pct: float | None = Field(default=None, ge=0, le=100)
    avg_watch_time_sec: float | None = Field(default=None, ge=0)
    top_post_er_pct: float | None = Field(default=None, ge=0, le=1000)
    median_er_pct: float | None = Field(default=None, ge=0, le=100)
    virality_ratio: float | None = Field(default=None, ge=0)  # top / median


# ---------------------------------------------------------------------------
# Strategic moves, annotated with "so what for us"
# ---------------------------------------------------------------------------

MoveType = Literal[
    "funding",
    "launch",
    "partnership",
    "hire_exec",
    "layoff",
    "campaign",
    "pricing",
    "acquisition",
    "regulatory",
    "other",
]

ThreatLevel = Literal["p0", "p1", "p2", "p3"]


class StrategicMove(BaseModel):
    """One dated competitor action with a required `so_what` implication and threat level.

    Threat level: p0 = direct hit on the core market (act now); p1 = significant pressure
    (plan this quarter); p2 = monitor; p3 = contextual noise (appendix only).
    """

    move_date: date
    move_type: MoveType
    headline: str = Field(min_length=10, max_length=200)
    source_url: str
    source_name: str = Field(min_length=1, max_length=80)
    so_what: str
    threat_level: ThreatLevel = "p2"

    @field_validator("move_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > datetime.now(tz=UTC).date():
            msg = f"move_date={v} is in the future"
            raise ValueError(msg)
        return v

    @field_validator("source_url")
    @classmethod
    def _real_http_source(cls, v: str) -> str:
        """Normalize fake / malformed URLs to empty (fail-soft)."""
        if not v or not v.startswith(("http://", "https://")):
            return ""
        if is_fake_source_url(v):
            return ""
        return v


# ---------------------------------------------------------------------------
# Trend maturity: a (trend x competitor) matrix cell
# ---------------------------------------------------------------------------


class TrendMaturity(BaseModel):
    """A competitor's maturity on a specific industry trend.

    Score: 0 = no visible implementation, 1 = exploratory (pilot / announcement),
    2 = shipped (production feature, limited scale), 3 = core offering (full rollout).
    Evidence URL is optional but recommended for scores of 1 or higher.
    """

    trend_slug: str = Field(min_length=2, max_length=60)
    competitor_slug: str = Field(min_length=2, max_length=60)
    maturity_score: Literal[0, 1, 2, 3]
    evidence_url: str | None = None
    observed_date: date
    notes: str = ""

    @field_validator("evidence_url")
    @classmethod
    def _evidence_url_real(cls, v: str | None) -> str | None:
        """Normalize fake / malformed URLs to None (fail-soft)."""
        if v is None or v == "":
            return None
        if not v.startswith(("http://", "https://")):
            return None
        if is_fake_source_url(v):
            return None
        return v

    @field_validator("observed_date")
    @classmethod
    def _observed_not_future(cls, v: date) -> date:
        # Allow a 45-day buffer: retrospective runs anchor observed_date at period end,
        # which can sit slightly ahead of the run date.
        cutoff = datetime.now(tz=UTC).date() + timedelta(days=45)
        if v > cutoff:
            msg = f"observed_date={v} is too far in the future (max allowed: {cutoff})"
            raise ValueError(msg)
        return v


# ---------------------------------------------------------------------------
# Paid media, SEO, web, app
# ---------------------------------------------------------------------------

SpendBand = Literal["low", "med", "high", "unknown"]
ConfidenceBand = Literal["low", "med", "high"]


class AdCreativeSummary(BaseModel):
    """Per-platform ad-library rollup from Meta Ad Library.

    Spend is a band plus confidence, not an exact number: precise spend is gated behind
    paid intelligence tools, and implying we have it would be dishonest.
    """

    active_ads_count: int = Field(ge=0)
    formats_pct: dict[str, float] = Field(default_factory=dict)
    creative_refresh_cadence_per_month: int | None = Field(default=None, ge=0)
    top_campaign_theme: str | None = None
    spend_estimate_band: SpendBand = "unknown"
    spend_estimate_confidence: ConfidenceBand = "low"


class SeoSnapshot(BaseModel):
    """Organic search footprint (Ahrefs / DataForSEO, optional/paid).

    All fields are nullable: the default posture is "data unavailable, low confidence"
    rather than fabrication.
    """

    organic_traffic_monthly: int | None = Field(default=None, ge=0)
    organic_traffic_trend_90d_pct: float | None = None
    referring_domains: int | None = Field(default=None, ge=0)
    domain_rating: int | None = Field(default=None, ge=0, le=100)
    top_keywords: list[str] = Field(default_factory=list, max_length=10)
    blog_posts_last_30d: int | None = Field(default=None, ge=0)


class OrganicKeyword(BaseModel):
    """A top organic search keyword (volume = monthly searches, cpc in the target geo)."""

    keyword: str = Field(max_length=80)
    volume: int | None = Field(default=None, ge=0)
    estimated_value: int | None = Field(default=None, ge=0)
    cpc: float | None = Field(default=None, ge=0)


class CountryTrafficShare(BaseModel):
    """A country's share of total web traffic (`share` is a 0.0-1.0 fraction)."""

    code: str = Field(max_length=2)  # ISO-2
    name: str | None = Field(default=None, max_length=80)
    share: float | None = Field(default=None, ge=0, le=1)


class WebAnalytics(BaseModel):
    """SimilarWeb-style traffic breakdown.

    `traffic_sources_pct` keys are canonical channels: direct / organic / paid / social /
    referral / email.
    """

    monthly_visits: int | None = Field(default=None, ge=0)
    trend_90d_pct: float | None = None
    trend_30d_pct: float | None = None
    monthly_visits_3mo_series: dict[str, int] = Field(default_factory=dict)
    top_keywords: list[OrganicKeyword] = Field(default_factory=list)
    top_countries_detailed: list[CountryTrafficShare] = Field(default_factory=list)
    category: str | None = Field(default=None, max_length=120)
    country_rank: int | None = Field(default=None, ge=1)
    country_rank_country_code: str | None = Field(default=None, max_length=2)
    category_rank: int | None = Field(default=None, ge=1)
    global_rank: int | None = Field(default=None, ge=1)
    traffic_sources_pct: dict[str, float] = Field(default_factory=dict)
    top_pages: list[str] = Field(default_factory=list)
    bounce_rate_pct: float | None = Field(default=None, ge=0, le=100)
    avg_session_duration_sec: int | None = Field(default=None, ge=0)


class AppStoreSignals(BaseModel):
    """App Store / Play Store signals. DAU/MAU are estimates; left None when unavailable."""

    ios_rating: float | None = Field(default=None, ge=0, le=5)
    android_rating: float | None = Field(default=None, ge=0, le=5)
    ios_reviews_30d: int | None = Field(default=None, ge=0)
    android_reviews_30d: int | None = Field(default=None, ge=0)
    review_sentiment_pos_pct: float | None = Field(default=None, ge=0, le=100)
    category_rank: int | None = Field(default=None, ge=1)
    estimated_dau: int | None = Field(default=None, ge=0)
    estimated_mau: int | None = Field(default=None, ge=0)
    update_velocity_per_month: float | None = Field(default=None, ge=0)
    ios_recent_reviews: list[Any] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Retention intelligence (composite index)
# ---------------------------------------------------------------------------


class RatingTrajectoryPoint(BaseModel):
    """One month bucket of a brand's app-rating trajectory."""

    month: str  # "2026-03"
    avg_rating: float = Field(ge=0, le=5)
    review_count: int = Field(ge=0)


class CompositeRetentionIndex(BaseModel):
    """A 0-100 composite summarizing retention signals.

    Weights (sum to 100): rating 30, review velocity 25, update velocity 20, SEO
    authority 15, web bounce 10. Each sub-score is 0 when the underlying data is missing,
    so the composite degrades gracefully. Benchmarks come from RETENTION_BENCHMARKS.
    """

    total: int = Field(ge=0, le=100)
    rating_score: int = Field(ge=0, le=30)
    review_velocity_score: int = Field(ge=0, le=25)
    update_velocity_score: int = Field(ge=0, le=20)
    seo_authority_score: int = Field(ge=0, le=15)
    web_bounce_score: int = Field(ge=0, le=10)
    benchmark_tier: Literal["top", "median", "below", "insufficient_data"]
    notes: str | None = Field(default=None, max_length=400)


# Comparative anchors for the retention index. These are vertical-specific; override
# them in your own deployment to match your category's norms.
RETENTION_BENCHMARKS = {
    "app_rating_top_quartile": 4.6,
    "app_rating_median": 4.3,
    "reviews_30d_top_quartile": 300,
    "reviews_30d_median": 50,
    "update_velocity_top_quartile": 4.0,  # releases/mo
    "update_velocity_median": 1.5,
    "seo_dr_top_quartile": 75,
    "seo_dr_median": 50,
    "bounce_rate_top_quartile_pct": 35.0,  # lower is better
    "bounce_rate_median_pct": 55.0,
}


# ---------------------------------------------------------------------------
# Qualitative profile (narrative + pillars + tone)
# ---------------------------------------------------------------------------

BrandTone = Literal[
    "playful",
    "authoritative",
    "aspirational",
    "warm_supportive",
    "edgy_irreverent",
    "pragmatic",
]

HorizonClassification = Literal[
    "horizon_1",  # core business, optimize existing
    "horizon_2",  # emerging, scale promising bets
    "horizon_3",  # disruptive, seed options
]

HypeCycleStage = Literal[
    "innovation_trigger",
    "peak_inflated_expectations",
    "trough_of_disillusionment",
    "slope_of_enlightenment",
    "plateau_of_productivity",
]


class QualitativeProfile(BaseModel):
    """A qualitative brand portrait for direct-threat competitors.

    Holds the narrative / emotional layer that quantitative fields on CompetitorProfile
    cannot capture. All text is in the report language.
    """

    slug: str
    narrative: str = Field(min_length=80, max_length=1200)
    content_pillars: list[str] = Field(default_factory=list, max_length=5)
    tone: BrandTone
    tone_evidence: str | None = Field(default=None, max_length=400)
    target_audience_profile: str | None = Field(default=None, max_length=500)
    audience_insights: str | None = Field(default=None, max_length=300)
    pricing_strategy: str | None = Field(default=None, max_length=400)
    horizon: HorizonClassification | None = None
    horizon_reasoning: str | None = Field(default=None, max_length=300)


class HypeCyclePosition(BaseModel):
    """A trend's position on the hype-cycle curve, rendered as a scatter point."""

    trend_name: str
    stage: HypeCycleStage
    years_to_plateau: int | None = Field(default=None, ge=0, le=15)
    reasoning: str = Field(min_length=30, max_length=400)


class PositioningMatrix2D(BaseModel):
    """A 2D positioning map (audience x price), rendered as a bubble chart."""

    brands: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Each brand: {name, x, y, size, color, quadrant}; x/y normalized 0-100.",
    )
    x_label: str = "Target audience"
    y_label: str = "Unit price"
    source: str = "competitor enricher data"


# ---------------------------------------------------------------------------
# Activity feed (per-brand event timeline)
# ---------------------------------------------------------------------------

EventType = Literal[
    "funding",
    "product",
    "pricing",
    "hire",
    "partnership",
    "press",
    "ad_campaign",
    "content",
    "expansion",
]


class EventRecord(BaseModel):
    """One discrete event in a competitor's 30-day activity feed.

    Aggregated from news search, pricing-page snapshot diffs, ad-library campaign
    start dates, and viral content signals. `title` is the "so what" framing; `so_what`
    expands on why it matters.
    """

    slug: str
    event_date: date
    event_type: EventType
    title: str = Field(min_length=15, max_length=220)
    url: str | None = None
    source: str | None = None
    confidence: Literal["high", "medium", "low"] = "medium"
    so_what: str | None = Field(default=None, max_length=300)

    @field_validator("url")
    @classmethod
    def _strip_fake_url(cls, v: str | None) -> str | None:
        if v and is_fake_source_url(v):
            return None
        return v
