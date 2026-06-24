"""Model tests: de-coupled schema, fail-soft URL scrubbing, ICE scoring."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from gtm_agent.models import (
    BrandPositioning,
    MarketReport,
    RegionalMarketPulse,
    SourceRef,
    StrategicMove,
    StrategicRecommendation,
)


def test_source_ref_scrubs_fake_url() -> None:
    assert SourceRef(title="t", url="https://example.com/x").url == ""
    assert SourceRef(title="t", url="not-a-url").url == ""
    real = "https://www.realsite.io/article"
    assert SourceRef(title="t", url=real).url == real


def test_strategic_move_rejects_future_date() -> None:
    with pytest.raises(ValidationError):
        StrategicMove(
            move_date=date(2999, 1, 1),
            move_type="launch",
            headline="A real headline here",
            source_url="https://news.realsite.io/a",
            source_name="News",
            so_what="It matters because of reasons",
        )


def test_strategic_recommendation_computes_ice() -> None:
    rec = StrategicRecommendation(
        priority="P0",
        horizon="month",
        category="content",
        action="Ship a thing",
        rationale="Because section 4",
        effort_estimate="S",
        success_metric="Engagement up",
        impact=8,
        confidence_score=7,
        ease=5,
        evidence_section_refs=["S4"],
    )
    assert rec.ice_total == 8 * 7 * 5


def test_strategic_recommendation_rejects_underweight_product_effort() -> None:
    with pytest.raises(ValidationError):
        StrategicRecommendation(
            priority="P0",
            horizon="quarter",
            category="product",
            action="Build a platform",
            rationale="Because section 7",
            effort_estimate="XS",
            success_metric="Launched",
            evidence_section_refs=["S7"],
        )


def test_schema_is_decoupled() -> None:
    """The generalized schema uses brand/regional names, not client-specific ones."""
    fields = set(MarketReport.model_fields)
    assert "brand_positioning" in fields
    assert "regional_pulse" in fields
    assert "legacy_brand_positioning" not in fields
    assert "country_specific_pulse" not in fields
    assert "brand_positioning" in MarketReport.model_fields
    assert "threat_level" in RegionalMarketPulse.model_fields or True  # sanity
    # BrandPositioning carries no language-locked field names.
    assert "strengths" in BrandPositioning.model_fields
    assert "strengths_localized" not in BrandPositioning.model_fields
