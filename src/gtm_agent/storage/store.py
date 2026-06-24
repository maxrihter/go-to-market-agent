"""SQLite-backed history + override store (default backend).

A single local file (default ``data/state.db``); pass ``":memory:"`` for an ephemeral
store (demo + tests). Operations are small and synchronous, fine to call from async nodes.

This is the durable layer the month-over-month intelligence depends on: prior-report
payloads (for the MoM diff), follower/engagement history (for growth velocity), metric
history (for the wide KPI series), the reports index (for cross-period navigation),
funding events, and human-in-the-loop overrides, across eight tables. Postgres remains
available behind the [postgres] extra (see checkpoint.py and the docs).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from ..log import get_logger
from ..models.competitor import FollowerSnapshot, FollowerSource
from ..models.report import MarketReport
from ..models.sections import MonthlyValueSeries, ReportRef

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS report_store (
    report_period  TEXT PRIMARY KEY,        -- 'YYYY-MM'
    payload        TEXT NOT NULL,           -- json.dumps(MarketReport)
    schema_version TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_store_created ON report_store(created_at);

CREATE TABLE IF NOT EXISTS follower_history (
    account_url    TEXT NOT NULL,
    snapshot_date  TEXT NOT NULL,
    follower_count INTEGER NOT NULL CHECK (follower_count >= 0),
    source         TEXT NOT NULL DEFAULT 'apify',
    captured_at    TEXT NOT NULL,
    PRIMARY KEY (account_url, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_fh_account ON follower_history(account_url, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS engagement_history (
    account_url   TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    metric_name   TEXT NOT NULL,
    metric_value  REAL NOT NULL,
    captured_at   TEXT NOT NULL,
    PRIMARY KEY (account_url, snapshot_date, metric_name)
);
CREATE INDEX IF NOT EXISTS idx_eh_account
    ON engagement_history(account_url, metric_name, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS report_feedback (
    report_id            TEXT NOT NULL,
    reviewer             TEXT NOT NULL,
    submitted_at         TEXT NOT NULL,
    overall_rating       INTEGER NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
    would_share          INTEGER NOT NULL DEFAULT 0,
    section_ratings      TEXT NOT NULL DEFAULT '[]',
    key_gaps             TEXT NOT NULL DEFAULT '[]',
    biggest_wins         TEXT NOT NULL DEFAULT '[]',
    next_period_focus    TEXT,
    PRIMARY KEY (report_id, reviewer)
);
CREATE INDEX IF NOT EXISTS idx_feedback_submitted ON report_feedback(submitted_at DESC);

CREATE TABLE IF NOT EXISTS metric_history (
    report_period TEXT NOT NULL,
    report_type   TEXT NOT NULL,
    metric_scope  TEXT NOT NULL,
    scope_id      TEXT NOT NULL DEFAULT '',
    metric_label  TEXT NOT NULL,
    value_str     TEXT NOT NULL,
    value_num     REAL,
    currency      TEXT,
    unit          TEXT,
    report_id     TEXT NOT NULL,
    recorded_at   TEXT NOT NULL,
    PRIMARY KEY (report_period, report_type, metric_scope, scope_id, metric_label)
);
CREATE INDEX IF NOT EXISTS idx_metric_history_label
    ON metric_history(metric_scope, scope_id, metric_label, report_period DESC);

CREATE TABLE IF NOT EXISTS funding_events_log (
    event_id             TEXT PRIMARY KEY,
    event_date           TEXT NOT NULL,
    brand_slug           TEXT NOT NULL,
    amount_usd_m         REAL,
    lead_investor        TEXT,
    source_url           TEXT,
    first_seen_report_id TEXT NOT NULL,
    last_seen_report_id  TEXT NOT NULL,
    verified             INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_funding_brand ON funding_events_log(brand_slug, event_date DESC);

CREATE TABLE IF NOT EXISTS report_index (
    report_id    TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    type         TEXT NOT NULL,
    period_label TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'draft',
    page_url     TEXT,
    qa_verdict   TEXT,
    published_at TEXT,
    notes        TEXT,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_index_period ON report_index(period_label, type);

CREATE TABLE IF NOT EXISTS overrides (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    section_key        TEXT NOT NULL,
    override_value     TEXT NOT NULL,
    override_reason    TEXT,
    created_by         TEXT NOT NULL DEFAULT 'operator',
    created_at         TEXT NOT NULL,
    expires_at         TEXT,
    applied_to_reports TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_overrides_section ON overrides(section_key);
"""


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


class Store:
    """Durable history + override state on SQLite."""

    def __init__(self, db_path: str | Path = "data/state.db") -> None:
        self._path = str(db_path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        if self._path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -------------------------------------------------------------- report store
    def save_report(self, report: MarketReport) -> None:
        """Persist a report for the next period's MoM comparison (upsert by period)."""
        self._conn.execute(
            """
            INSERT INTO report_store (report_period, payload, schema_version, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(report_period) DO UPDATE SET
                payload = excluded.payload,
                schema_version = excluded.schema_version,
                created_at = excluded.created_at
            """,
            (report.period, report.model_dump_json(), str(report.schema_version), _now_iso()),
        )
        self._conn.commit()

    def fetch_previous_report(self, current_period: str) -> tuple[dict[str, Any], str] | None:
        """Return ``(payload_dict, schema_version)`` for the latest period before now."""
        row = self._conn.execute(
            "SELECT payload, schema_version FROM report_store "
            "WHERE report_period < ? ORDER BY report_period DESC LIMIT 1",
            (current_period,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"]), row["schema_version"]

    # ------------------------------------------------------------- follower hist
    def write_follower_snapshot(
        self, account_url: str, snapshot_date: date, follower_count: int, *, source: str = "apify"
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO follower_history
                (account_url, snapshot_date, follower_count, source, captured_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_url, snapshot_date) DO UPDATE SET
                follower_count = excluded.follower_count,
                source = excluded.source,
                captured_at = excluded.captured_at
            """,
            (account_url, snapshot_date.isoformat(), int(follower_count), source, _now_iso()),
        )
        self._conn.commit()

    def read_follower_history(self, account_url: str, *, days: int = 90) -> list[FollowerSnapshot]:
        cutoff = (datetime.now(tz=UTC).date() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT snapshot_date, follower_count, source FROM follower_history "
            "WHERE account_url = ? AND snapshot_date >= ? ORDER BY snapshot_date ASC",
            (account_url, cutoff),
        ).fetchall()
        out: list[FollowerSnapshot] = []
        for r in rows:
            src = (
                r["source"]
                if r["source"] in {"apify", "manual", "similarweb", "other"}
                else "other"
            )
            out.append(
                FollowerSnapshot(
                    snapshot_date=date.fromisoformat(r["snapshot_date"]),
                    follower_count=int(r["follower_count"]),
                    source=cast(FollowerSource, src),
                )
            )
        return out

    def write_engagement_snapshots(
        self, account_url: str, snapshot_date: date, metrics: dict[str, float]
    ) -> None:
        if not metrics:
            return
        now = _now_iso()
        self._conn.executemany(
            """
            INSERT INTO engagement_history
                (account_url, snapshot_date, metric_name, metric_value, captured_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_url, snapshot_date, metric_name) DO UPDATE SET
                metric_value = excluded.metric_value,
                captured_at = excluded.captured_at
            """,
            [
                (account_url, snapshot_date.isoformat(), n, float(v), now)
                for n, v in metrics.items()
            ],
        )
        self._conn.commit()

    # -------------------------------------------------------------------- feedback
    def write_feedback(
        self,
        *,
        report_id: str,
        reviewer: str,
        overall_rating: int,
        would_share: bool = False,
        section_ratings: list[Any] | None = None,
        key_gaps: list[str] | None = None,
        biggest_wins: list[str] | None = None,
        next_period_focus: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO report_feedback
                (report_id, reviewer, submitted_at, overall_rating, would_share,
                 section_ratings, key_gaps, biggest_wins, next_period_focus)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id, reviewer) DO UPDATE SET
                submitted_at = excluded.submitted_at,
                overall_rating = excluded.overall_rating,
                would_share = excluded.would_share,
                section_ratings = excluded.section_ratings,
                key_gaps = excluded.key_gaps,
                biggest_wins = excluded.biggest_wins,
                next_period_focus = excluded.next_period_focus
            """,
            (
                report_id,
                reviewer,
                _now_iso(),
                int(overall_rating),
                1 if would_share else 0,
                json.dumps(section_ratings or []),
                json.dumps(key_gaps or []),
                json.dumps(biggest_wins or []),
                next_period_focus,
            ),
        )
        self._conn.commit()

    def read_feedback_by_period_prefix(self, prev_period: str) -> list[dict[str, Any]]:
        """Read feedback for any report id starting ``report-{prev_period}`` (newest first)."""
        rows = self._conn.execute(
            "SELECT * FROM report_feedback WHERE report_id LIKE ? ORDER BY submitted_at DESC",
            (f"report-{prev_period}%",),
        ).fetchall()
        return [self._feedback_row(r) for r in rows]

    @staticmethod
    def _feedback_row(r: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id": r["report_id"],
            "reviewer": r["reviewer"],
            "submitted_at": r["submitted_at"],
            "overall_rating": r["overall_rating"],
            "would_share": bool(r["would_share"]),
            "section_ratings": json.loads(r["section_ratings"]),
            "key_gaps": json.loads(r["key_gaps"]),
            "biggest_wins": json.loads(r["biggest_wins"]),
            "next_period_focus": r["next_period_focus"],
        }

    # --------------------------------------------------------------- reports index
    def register_report(
        self,
        *,
        report_id: str,
        title: str,
        report_type: str,
        period_label: str,
        status: str = "published",
        page_url: str | None = None,
        qa_verdict: str | None = None,
        notes: str | None = None,
    ) -> None:
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO report_index
                (report_id, title, type, period_label, status, page_url, qa_verdict,
                 published_at, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_id) DO UPDATE SET
                title = excluded.title,
                status = excluded.status,
                page_url = excluded.page_url,
                qa_verdict = excluded.qa_verdict,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                report_id,
                title,
                report_type,
                period_label,
                status,
                page_url,
                qa_verdict,
                now,
                notes,
                now,
            ),
        )
        self._conn.commit()

    def fetch_prior_reports(
        self, *, period: str, limit_monthly: int = 3, include_latest_annual: bool = True
    ) -> list[ReportRef]:
        rows = self._conn.execute(
            "SELECT report_id, title, period_label, type, page_url, published_at "
            "FROM report_index WHERE type = 'monthly' AND status = 'published' "
            "AND period_label < ? ORDER BY period_label DESC LIMIT ?",
            (period, limit_monthly),
        ).fetchall()
        refs = [self._report_ref(r) for r in rows]
        if include_latest_annual:
            ann = self._conn.execute(
                "SELECT report_id, title, period_label, type, page_url, published_at "
                "FROM report_index WHERE type = 'annual' AND status = 'published' "
                "ORDER BY published_at DESC LIMIT 1"
            ).fetchone()
            if ann is not None:
                refs.append(self._report_ref(ann))
        return refs

    @staticmethod
    def _report_ref(r: sqlite3.Row) -> ReportRef:
        return ReportRef(
            report_id=r["report_id"],
            period_label=r["period_label"],
            period_type="annual" if r["type"] == "annual" else "monthly",
            page_url=r["page_url"],
            published_at=r["published_at"],
        )

    # --------------------------------------------------------------- metric history
    def record_metric_value(
        self,
        *,
        report_period: str,
        report_type: str,
        metric_scope: str,
        scope_id: str,
        metric_label: str,
        value_str: str,
        report_id: str,
        value_num: float | None = None,
        currency: str | None = None,
        unit: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO metric_history
                (report_period, report_type, metric_scope, scope_id, metric_label,
                 value_str, value_num, currency, unit, report_id, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_period, report_type, metric_scope, scope_id, metric_label)
            DO UPDATE SET
                value_str = excluded.value_str,
                value_num = excluded.value_num,
                currency = excluded.currency,
                unit = excluded.unit,
                report_id = excluded.report_id,
                recorded_at = excluded.recorded_at
            """,
            (
                report_period,
                report_type,
                metric_scope,
                scope_id,
                metric_label,
                value_str,
                value_num,
                currency,
                unit,
                report_id,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def fetch_metric_series(
        self, *, metric_scope: str, metric_label: str, scope_id: str = "", months: int = 12
    ) -> MonthlyValueSeries:
        rows = self._conn.execute(
            "SELECT report_period, value_str, currency, unit FROM metric_history "
            "WHERE metric_scope = ? AND scope_id = ? AND metric_label = ? "
            "ORDER BY report_period DESC LIMIT ?",
            (metric_scope, scope_id, metric_label, months),
        ).fetchall()
        values = {r["report_period"]: r["value_str"] for r in rows}
        periods = sorted(values)
        currency = rows[0]["currency"] if rows else None
        unit = rows[0]["unit"] if rows else None
        return MonthlyValueSeries(
            label=metric_label,
            monthly_values=values,
            currency=currency,
            unit=unit,
            earliest_period=periods[0] if periods else None,
            latest_period=periods[-1] if periods else None,
        )

    # --------------------------------------------------------------- funding events
    @staticmethod
    def compute_funding_event_id(
        brand_slug: str, event_date: str, amount_usd_m: float | None
    ) -> str:
        raw = f"{brand_slug}|{event_date}|{amount_usd_m}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]  # noqa: S324 (id only, not security)

    def record_funding_event(
        self,
        *,
        event_date: str,
        brand_slug: str,
        report_id: str,
        amount_usd_m: float | None = None,
        lead_investor: str | None = None,
        source_url: str | None = None,
        verified: bool = False,
    ) -> str:
        event_id = self.compute_funding_event_id(brand_slug, event_date, amount_usd_m)
        self._conn.execute(
            """
            INSERT INTO funding_events_log
                (event_id, event_date, brand_slug, amount_usd_m, lead_investor, source_url,
                 first_seen_report_id, last_seen_report_id, verified, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                last_seen_report_id = excluded.last_seen_report_id,
                verified = MAX(funding_events_log.verified, excluded.verified)
            """,
            (
                event_id,
                event_date,
                brand_slug,
                amount_usd_m,
                lead_investor,
                source_url,
                report_id,
                report_id,
                1 if verified else 0,
                _now_iso(),
            ),
        )
        self._conn.commit()
        return event_id

    def fetch_funding_events_window(
        self, *, months_back: int = 12, brand_slug: str | None = None
    ) -> list[dict[str, Any]]:
        # Months approximated as 30 days; exact calendar months are unnecessary here.
        cutoff = (datetime.now(tz=UTC).date() - timedelta(days=30 * months_back)).isoformat()
        if brand_slug:
            rows = self._conn.execute(
                "SELECT * FROM funding_events_log WHERE brand_slug = ? AND event_date >= ? "
                "ORDER BY event_date DESC",
                (brand_slug, cutoff),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM funding_events_log WHERE event_date >= ? ORDER BY event_date DESC",
                (cutoff,),
            ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_old_funding_events(self, *, months_keep: int = 13) -> int:
        cutoff = (datetime.now(tz=UTC).date() - timedelta(days=30 * months_keep)).isoformat()
        cur = self._conn.execute("DELETE FROM funding_events_log WHERE event_date < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------- overrides
    def upsert_override(
        self,
        section_key: str,
        override_value: str,
        override_reason: str | None = None,
        *,
        created_by: str = "operator",
        expires_at: str | None = None,
    ) -> int:
        """Replace any existing override for this section key, returning the new id."""
        self._conn.execute("DELETE FROM overrides WHERE section_key = ?", (section_key,))
        cur = self._conn.execute(
            "INSERT INTO overrides (section_key, override_value, override_reason, created_by, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (section_key, override_value, override_reason, created_by, _now_iso(), expires_at),
        )
        self._conn.commit()
        return int(cur.lastrowid or 0)

    def fetch_active_overrides(self) -> list[dict[str, Any]]:
        now = _now_iso()
        rows = self._conn.execute(
            "SELECT * FROM overrides WHERE expires_at IS NULL OR expires_at > ? "
            "ORDER BY section_key",
            (now,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            d["applied_to_reports"] = json.loads(r["applied_to_reports"])
            out.append(d)
        return out

    def mark_override_applied(self, override_id: int, report_id: str) -> None:
        row = self._conn.execute(
            "SELECT applied_to_reports FROM overrides WHERE id = ?", (override_id,)
        ).fetchone()
        if row is None:
            return
        applied = json.loads(row["applied_to_reports"])
        if report_id not in applied:
            applied.append(report_id)
        self._conn.execute(
            "UPDATE overrides SET applied_to_reports = ? WHERE id = ?",
            (json.dumps(applied), override_id),
        )
        self._conn.commit()

    def cleanup_expired_overrides(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM overrides WHERE expires_at IS NOT NULL AND expires_at < ?", (_now_iso(),)
        )
        self._conn.commit()
        return cur.rowcount


# Generic placeholder / stub markers that signal a field was never really filled.
# The list is language-neutral; extend it for your own report language.
_OVERRIDE_PLACEHOLDERS = {"-", "—", "n/a", "na", "none", "null", "todo", "tbd", "tba", "test"}


def should_apply_override(override_value: str, current_value: Any) -> bool:
    """True if the current report value is empty, a stub, or weaker than the override.

    Applies when the current value is missing/blank, a known placeholder, or when the
    override is substantially richer (more than 1.5x longer). The placeholder phrase list
    is language-neutral and can be extended for your own report language.
    """
    if current_value is None:
        return True
    if isinstance(current_value, str):
        stripped = current_value.strip()
        if len(stripped) < 10:
            return True
        if stripped.lower() in _OVERRIDE_PLACEHOLDERS:
            return True
        if any(marker in stripped.lower() for marker in ("todo", "tbd", "tba")):
            return True
        return len(override_value.strip()) > len(stripped) * 1.5
    if isinstance(current_value, (list, dict)):
        return len(current_value) == 0
    return False
