"""Storage tests: SQLite history round-trips for every dependent node."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from gtm_agent.models import MarketReport
from gtm_agent.storage.store import Store, should_apply_override


def test_report_store_roundtrip_and_mom(make_report: Callable[[str], MarketReport]) -> None:
    store = Store(":memory:")
    assert store.fetch_previous_report("2026-04") is None
    store.save_report(make_report("2026-03"))
    prev = store.fetch_previous_report("2026-04")
    assert prev is not None
    payload, _version = prev
    assert payload["period"] == "2026-03"
    assert store.fetch_previous_report("2026-03") is None  # earliest period has no prior
    store.close()


def test_follower_history_roundtrip() -> None:
    store = Store(":memory:")
    url = "https://www.instagram.com/acme/"
    store.write_follower_snapshot(url, date(2026, 1, 1), 1000)
    store.write_follower_snapshot(url, date(2026, 3, 1), 1300)
    hist = store.read_follower_history(url, days=4000)
    assert [s.follower_count for s in hist] == [1000, 1300]
    store.close()


def test_metric_history_series() -> None:
    store = Store(":memory:")
    for period, val in [("2026-02", "$2.0B"), ("2026-03", "$2.4B")]:
        store.record_metric_value(
            report_period=period,
            report_type="monthly",
            metric_scope="kpi",
            scope_id="",
            metric_label="VC funding",
            value_str=val,
            report_id=f"report-{period}-demo",
        )
    series = store.fetch_metric_series(metric_scope="kpi", metric_label="VC funding")
    assert series.monthly_values == {"2026-02": "$2.0B", "2026-03": "$2.4B"}
    store.close()


def test_reports_index_and_prior() -> None:
    store = Store(":memory:")
    store.register_report(
        report_id="report-2026-02-demo", title="Feb", report_type="monthly", period_label="2026-02"
    )
    store.register_report(
        report_id="report-2026-03-demo", title="Mar", report_type="monthly", period_label="2026-03"
    )
    refs = store.fetch_prior_reports(period="2026-04", include_latest_annual=False)
    assert [r.period_label for r in refs] == ["2026-03", "2026-02"]
    store.close()


def test_overrides_lifecycle() -> None:
    store = Store(":memory:")
    oid = store.upsert_override("section_competitive.acme.funding", "150000000", "manual fix")
    active = store.fetch_active_overrides()
    assert len(active) == 1 and active[0]["id"] == oid
    store.mark_override_applied(oid, "report-2026-04-demo")
    assert store.fetch_active_overrides()[0]["applied_to_reports"] == ["report-2026-04-demo"]
    store.upsert_override("section_competitive.acme.funding", "200000000")  # replaces
    assert len(store.fetch_active_overrides()) == 1
    store.close()


def test_funding_events_dedup_and_window() -> None:
    store = Store(":memory:")
    eid1 = store.record_funding_event(
        event_date="2026-03-15", brand_slug="acme", report_id="r1", amount_usd_m=20.0
    )
    eid2 = store.record_funding_event(
        event_date="2026-03-15", brand_slug="acme", report_id="r2", amount_usd_m=20.0, verified=True
    )
    assert eid1 == eid2  # same event collapses
    events = store.fetch_funding_events_window(months_back=6)
    assert len(events) == 1 and events[0]["verified"] == 1
    store.close()


def test_should_apply_override_heuristic() -> None:
    assert should_apply_override("x", None) is True
    assert should_apply_override("x", "") is True
    assert should_apply_override("x", []) is True
    assert should_apply_override("x", "TODO") is True  # placeholder marker
    assert should_apply_override("a much longer and richer replacement", "shortish v") is True
    assert should_apply_override("x", "a real existing value of substance") is False
