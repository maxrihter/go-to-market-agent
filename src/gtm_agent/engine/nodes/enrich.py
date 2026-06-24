"""Multi-source competitor enrichment: build competitor_raw from up to nine sources.

Pure helpers (parse + compute) are I/O-free and testable; the orchestrator batches the
upstream fetches (Apify IG profile, Meta Ad Library, SimilarWeb, Wayback, Google Trends,
YouTube, App Store, Ahrefs, DataForSEO) and joins them per competitor into a flat
competitor_raw dict the competitive analyst copies verbatim. Every source is fail-soft:
a missing key or a failed call degrades to absent data, never an abort. The node is gated
by APIFY_TOKEN and the offline flag so the hermetic demo never dials out.
"""

from __future__ import annotations

import asyncio
import os
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ...integrations import (
    ad_library,
    ahrefs,
    app_store,
    dataforseo,
    google_trends,
    similarweb,
    wayback,
    youtube,
)
from ...integrations.apify_client import fetch_dataset, run_actor
from ...log import get_logger
from ...models.competitor import AdCreativeSummary, ContentMix, EngagementMetrics

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ...config import Settings
    from ...storage.store import Store

logger = get_logger(__name__)

_IG_ACTOR = "apify/instagram-profile-scraper"
_IG_POST_LIMIT = 30
_GROWTH_DAYS = 90
_REEL_TYPES = {"clips", "clip", "reel"}


# ---------------------------------------------------------------------------
# Pure helpers (no I/O)
# ---------------------------------------------------------------------------


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or isinstance(value, bool):
        return int(value) if isinstance(value, bool) else default
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace(" ", "")
        if not cleaned:
            return default
        mult = 1
        if cleaned[-1].lower() == "k":
            mult, cleaned = 1_000, cleaned[:-1]
        elif cleaned[-1].lower() == "m":
            mult, cleaned = 1_000_000, cleaned[:-1]
        try:
            return int(float(cleaned) * mult)
        except ValueError:
            return default
    return default


def parse_apify_ig_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an Apify IG-profile item to a canonical dict; {} when critical fields missing."""
    username = raw.get("username") or ""
    if not username:
        return {}
    followers = raw.get("followersCount") or raw.get("followers_count") or 0
    posts = raw.get("latestPosts") or raw.get("posts") or []
    return {
        "username": str(username).lstrip("@"),
        "followers_count": _safe_int(followers),
        "posts_count": _safe_int(raw.get("postsCount")),
        "latest_posts": posts if isinstance(posts, list) else [],
    }


def _classify_post_format(post: dict[str, Any]) -> str:
    product = (post.get("productType") or "").lower()
    if product in _REEL_TYPES:
        return "reel"
    ptype = (post.get("type") or "").lower()
    if ptype == "sidecar":
        return "carousel"
    if (ptype == "video" or post.get("videoUrl")) and product != "feed":
        return "reel"
    return "static"


def compute_content_mix(posts: list[dict[str, Any]]) -> ContentMix | None:
    if not posts:
        return None
    counts = {"reel": 0, "carousel": 0, "static": 0}
    for p in posts:
        counts[_classify_post_format(p)] += 1
    total = sum(counts.values())
    if total == 0:
        return None
    reels = round(counts["reel"] / total * 100, 1)
    carousels = round(counts["carousel"] / total * 100, 1)
    return ContentMix(
        reels_pct=reels,
        carousels_pct=carousels,
        stories_pct=0.0,
        static_pct=round(100.0 - reels - carousels, 1),
    )


def _post_er(post: dict[str, Any], followers: int) -> float | None:
    if followers <= 0:
        return None
    likes = post.get("likesCount") or post.get("likes_count") or 0
    comments = post.get("commentsCount") or post.get("comments_count") or 0
    try:
        return (float(likes) + float(comments)) / float(followers) * 100.0
    except (TypeError, ValueError):
        return None


def compute_engagement_metrics(
    posts: list[dict[str, Any]], followers: int
) -> EngagementMetrics | None:
    if followers <= 0 or not posts:
        return None
    ers = [er for p in posts if (er := _post_er(p, followers)) is not None]
    if not ers:
        return None
    median = statistics.median(ers)
    top = max(ers)
    return EngagementMetrics(
        avg_er_pct=round(statistics.mean(ers), 3),
        median_er_pct=round(median, 3),
        top_post_er_pct=round(top, 3),
        virality_ratio=round(top / median, 2) if median > 0 else None,
    )


def count_posts_last_30d(posts: list[dict[str, Any]]) -> int:
    cutoff = datetime.now(tz=UTC) - timedelta(days=30)
    seen = 0
    for p in posts:
        ts_raw = p.get("timestamp") or p.get("takenAtTimestamp")
        if not ts_raw:
            continue
        try:
            ts = (
                datetime.fromtimestamp(float(ts_raw), tz=UTC)
                if isinstance(ts_raw, (int, float))
                else datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            )
            if ts >= cutoff:
                seen += 1
        except (ValueError, TypeError):
            continue
    return seen


def compute_growth_velocity_pct(
    history: list[Any], *, today: date | None = None, window_days: int = _GROWTH_DAYS
) -> float | None:
    if len(history) < 2:
        return None
    today = today or datetime.now(tz=UTC).date()
    window = [s for s in history if s.snapshot_date >= today - timedelta(days=window_days)]
    if len(window) < 2:
        return None
    window.sort(key=lambda s: s.snapshot_date)
    start, end = window[0].follower_count, window[-1].follower_count
    return round((end - start) / start * 100.0, 2) if start > 0 else None


def _spend_band(count: int) -> str:
    if count <= 0:
        return "unknown"
    if count <= 5:
        return "low"
    return "med" if count <= 20 else "high"


def _ads_to_summary(entry: dict[str, Any]) -> AdCreativeSummary:
    count = int(entry.get("ad_count", 0) or 0)
    themes = entry.get("creative_themes") or []
    return AdCreativeSummary(
        active_ads_count=count,
        top_campaign_theme=themes[0] if themes else None,
        spend_estimate_band=_spend_band(count),  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Apify IG profile fetch (delete-after-read via fetch_dataset)
# ---------------------------------------------------------------------------


async def fetch_ig_profile(token: str, handle: str) -> dict[str, Any]:
    try:
        dataset_id = await run_actor(
            token,
            _IG_ACTOR,
            {"usernames": [handle], "resultsType": "details", "resultsLimit": _IG_POST_LIMIT},
        )
        items = await fetch_dataset(token, dataset_id)
        return items[0] if items else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ig_profile_failed", handle=handle, error=str(exc)[:150])
        return {}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def enrich_competitors(
    watchlist: list[Any], *, token: str, store: Store | None
) -> dict[str, dict[str, Any]]:
    """Fetch all sources and build {slug: flat-metrics-dict} for the watchlist."""
    if not watchlist or not token:
        return {}

    domains = [w.website_domain for w in watchlist if getattr(w, "website_domain", None)]
    brands = [w.name for w in watchlist]
    keywords = [w.name for w in watchlist]
    app_entries = [
        {"slug": w.slug, "ios_app_id": getattr(w, "ios_app_id", None)}
        for w in watchlist
        if getattr(w, "ios_app_id", None)
    ]

    ads, web, trends, apps = await asyncio.gather(
        ad_library.fetch_competitor_ads(brands, token=token),
        similarweb.fetch_web_analytics(domains, token=token),
        asyncio.to_thread(google_trends.fetch_brand_interest_deltas, keywords),
        app_store.fetch_app_snapshots(app_entries),
        return_exceptions=True,
    )
    ads_by_brand = {a["advertiser"].lower(): a for a in (ads if isinstance(ads, list) else [])}
    web = web if isinstance(web, dict) else {}
    trends = trends if isinstance(trends, dict) else {}
    apps = apps if isinstance(apps, dict) else {}
    seo = await ahrefs.fetch_ahrefs_batch(domains)
    yt_handles = [w.youtube_handle for w in watchlist if getattr(w, "youtube_handle", None)]
    yt = await youtube.fetch_channel_stats(yt_handles)
    serp = await dataforseo.fetch_serp_positions(keywords)
    overlap = dataforseo.compute_keyword_overlap(
        serp, {w.slug: (getattr(w, "website_domain", None) or "") for w in watchlist}
    )

    async def _one(w: Any) -> tuple[str, dict[str, Any]]:
        handle = (getattr(w, "ig_handle", None) or "").lstrip("@")
        raw = await fetch_ig_profile(token, handle) if handle else {}
        parsed = parse_apify_ig_profile(raw)
        followers = parsed.get("followers_count", 0)
        posts = parsed.get("latest_posts", [])
        engagement = compute_engagement_metrics(posts, followers) if posts else None
        mix = compute_content_mix(posts) if posts else None

        growth: float | None = None
        if store is not None and followers > 0:
            url = f"https://www.instagram.com/{handle}/"
            await asyncio.to_thread(store.write_follower_snapshot, url, date.today(), followers)
            history = await asyncio.to_thread(store.read_follower_history, url)
            growth = compute_growth_velocity_pct(history)

        domain = (getattr(w, "website_domain", None) or "").lower()
        wayback_count = await wayback.fetch_landing_pages_new_30d(domain) if domain else None
        ad_entry = ads_by_brand.get(w.name.lower())
        meta_ads = _ads_to_summary(ad_entry) if ad_entry else None
        tr = trends.get(w.name, {})
        web_a = web.get(domain, {})
        app_snap = apps.get(w.slug, {})
        seo_snap = seo.get(domain, {})
        yt_handle = getattr(w, "youtube_handle", None)
        yt_stats = yt.get(yt_handle, {}) if yt_handle else {}
        serp_overlap = overlap.get(w.slug, {})

        return w.slug, {
            "slug": w.slug,
            "ig_handle": handle or None,
            "ig_followers_count": followers or None,
            "ig_posts_last_30d": count_posts_last_30d(posts) if posts else 0,
            "ig_avg_engagement_rate": (engagement.avg_er_pct / 100.0 if engagement else None),
            "ig_follower_growth_90d_pct": growth,
            "ig_engagement": engagement.model_dump() if engagement else None,
            "content_mix_30d": mix.model_dump() if mix else None,
            "active_ads_count": meta_ads.active_ads_count if meta_ads else None,
            "creative_themes": (ad_entry or {}).get("creative_themes", []),
            "monthly_visits": web_a.get("monthly_visits"),
            "bounce_rate_pct": web_a.get("bounce_rate_pct"),
            "landing_pages_new_30d": wayback_count,
            "search_interest_direction": tr.get("trend_direction"),
            "search_interest_change_pct": tr.get("half_change_pct"),
            "ios_rating": app_snap.get("ios_rating"),
            "android_rating": app_snap.get("android_rating"),
            "domain_rating": seo_snap.get("domain_rating"),
            "referring_domains": seo_snap.get("referring_domains"),
            "youtube_subs": yt_stats.get("subscriber_count"),
            "ranking_keywords": serp_overlap.get("ranking_keywords", []),
        }

    results = await asyncio.gather(*[_one(w) for w in watchlist], return_exceptions=True)
    out: dict[str, dict[str, Any]] = {}
    for r in results:
        if isinstance(r, BaseException):
            logger.warning("enrich_one_failed", error=str(r)[:150])
            continue
        slug, data = r
        out[slug] = data
    logger.info("enrichment_complete", competitors=len(out))
    return out


async def collect_enrichment(
    state: Any, config: RunnableConfig, *, settings: Settings, store: Store, offline: bool = False
) -> dict[str, Any]:
    """Graph node: build competitor_raw from the watchlist (best-effort, offline-gated)."""
    if offline:
        return {}
    token = os.environ.get("APIFY_TOKEN", "")
    if not token or not settings.watchlist:
        logger.info("enrichment_skipped", reason="no token or empty watchlist")
        return {}
    try:
        raw = await enrich_competitors(settings.watchlist, token=token, store=store)
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrichment_failed", error=str(exc)[:200])
        return {"competitor_raw": {}}
    return {"competitor_raw": raw}
