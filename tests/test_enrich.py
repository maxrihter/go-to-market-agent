"""Enricher tests: pure helpers, node gating (offline / no token), mocked orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any

import gtm_agent.engine.nodes.enrich as enrich_mod
from gtm_agent.config import WatchEntry, default_settings
from gtm_agent.engine.nodes.enrich import (
    _ads_to_summary,
    _safe_int,
    _spend_band,
    collect_enrichment,
    compute_content_mix,
    compute_engagement_metrics,
    compute_growth_velocity_pct,
    enrich_competitors,
    parse_apify_ig_profile,
)
from gtm_agent.models.competitor import FollowerSnapshot
from gtm_agent.storage.store import Store


def test_safe_int_handles_suffixes() -> None:
    assert _safe_int("1,200") == 1200
    assert _safe_int("3.8K") == 3800
    assert _safe_int("2M") == 2_000_000
    assert _safe_int(None, default=0) == 0


def test_parse_ig_profile() -> None:
    parsed = parse_apify_ig_profile(
        {"username": "@acme", "followersCount": "1000", "latestPosts": [{}]}
    )
    assert parsed["username"] == "acme"
    assert parsed["followers_count"] == 1000
    assert parse_apify_ig_profile({}) == {}


def test_content_mix_sums_to_100() -> None:
    mix = compute_content_mix([{"productType": "clips"}, {"type": "Sidecar"}, {"type": "Image"}])
    assert mix is not None
    assert abs(mix.reels_pct + mix.carousels_pct + mix.stories_pct + mix.static_pct - 100.0) < 1.0
    assert compute_content_mix([]) is None


def test_engagement_metrics() -> None:
    em = compute_engagement_metrics([{"likesCount": 50, "commentsCount": 5}], 1000)
    assert em is not None
    assert em.avg_er_pct == 5.5  # (50+5)/1000*100
    assert compute_engagement_metrics([], 1000) is None


def test_spend_band_and_ads_summary() -> None:
    assert _spend_band(0) == "unknown"
    assert _spend_band(3) == "low"
    assert _spend_band(25) == "high"
    summary = _ads_to_summary({"ad_count": 12, "creative_themes": ["fresh"]})
    assert summary.active_ads_count == 12 and summary.spend_estimate_band == "med"


def test_growth_velocity() -> None:
    history = [
        FollowerSnapshot(snapshot_date=date(2026, 1, 1), follower_count=1000),
        FollowerSnapshot(snapshot_date=date(2026, 3, 1), follower_count=1100),
    ]
    assert compute_growth_velocity_pct(history, today=date(2026, 3, 2), window_days=400) == 10.0
    assert compute_growth_velocity_pct(history[:1]) is None


async def test_collect_enrichment_offline_is_empty() -> None:
    out = await collect_enrichment(
        {}, None, settings=default_settings(), store=Store(":memory:"), offline=True
    )
    assert out == {}


async def test_collect_enrichment_no_token_is_empty(monkeypatch: Any) -> None:
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    out = await collect_enrichment(
        {}, None, settings=default_settings(), store=Store(":memory:"), offline=False
    )
    assert out == {}


async def test_orchestrator_joins_sources(monkeypatch: Any) -> None:
    async def fake_ig(token: str, handle: str) -> dict[str, Any]:
        return {
            "username": handle,
            "followersCount": 1000,
            "latestPosts": [{"productType": "clips", "likesCount": 50, "commentsCount": 5}],
        }

    async def empty_async(*a: Any, **k: Any) -> Any:
        return {}

    async def empty_list(*a: Any, **k: Any) -> list:
        return []

    monkeypatch.setattr(enrich_mod, "fetch_ig_profile", fake_ig)
    monkeypatch.setattr(enrich_mod.ad_library, "fetch_competitor_ads", empty_list)
    monkeypatch.setattr(enrich_mod.similarweb, "fetch_web_analytics", empty_async)
    monkeypatch.setattr(enrich_mod.app_store, "fetch_app_snapshots", empty_async)
    monkeypatch.setattr(enrich_mod.ahrefs, "fetch_ahrefs_batch", empty_async)
    monkeypatch.setattr(enrich_mod.wayback, "fetch_landing_pages_new_30d", empty_async)
    monkeypatch.setattr(
        enrich_mod.google_trends, "fetch_brand_interest_deltas", lambda kws, **k: {}
    )

    w = WatchEntry(slug="acme", name="Acme", ig_handle="acme", website_domain="acme.com")
    raw = await enrich_competitors([w], token="x", store=Store(":memory:"))
    assert raw["acme"]["ig_followers_count"] == 1000
    assert raw["acme"]["content_mix_30d"] is not None
    assert raw["acme"]["ig_avg_engagement_rate"] == 0.055
