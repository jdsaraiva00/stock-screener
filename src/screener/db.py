"""SQLite cache. The dashboard and analysis read only from here; only the refresh job writes.

WAL mode lets a refresh run while the app is reading.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS universe_membership (
    universe          TEXT NOT NULL,
    ticker            TEXT NOT NULL,      -- Yahoo/SEC style: BRK-B, not BRK.B
    cik               INTEGER,            -- SEC company id; two share classes can share one
    name              TEXT,
    gics_sector       TEXT,
    gics_sub_industry TEXT,
    date_added        TEXT,               -- date the source says it joined the index, if given
    first_seen        TEXT NOT NULL,      -- when this cache first saw it as a member
    removed_on        TEXT,               -- NULL while a current member
    source            TEXT NOT NULL,
    fetched_at        TEXT NOT NULL,
    PRIMARY KEY (universe, ticker)
);

-- One row per trading day. close is split-adjusted only; adj_close is also
-- dividend-adjusted (total return). Fetch time is per ticker, in price_series_meta.
CREATE TABLE IF NOT EXISTS prices_daily (
    ticker    TEXT NOT NULL,
    date      TEXT NOT NULL,
    open      REAL, high REAL, low REAL, close REAL, adj_close REAL,
    volume    INTEGER,
    dividend  REAL,
    split     REAL,
    PRIMARY KEY (ticker, date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS price_series_meta (
    ticker TEXT PRIMARY KEY, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
    first_date TEXT, last_date TEXT, rows INTEGER,
    full_refetches INTEGER NOT NULL DEFAULT 0   -- times history was reloaded after a split/dividend
);

CREATE TABLE IF NOT EXISTS company_profile (
    ticker TEXT PRIMARY KEY, name TEXT, sector TEXT, industry TEXT,
    market_cap REAL, shares_outstanding REAL, currency TEXT, exchange TEXT, quote_type TEXT,
    source TEXT NOT NULL, fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filer_info (
    cik INTEGER PRIMARY KEY, name TEXT, sic TEXT, sic_description TEXT,
    fiscal_year_end TEXT,              -- MMDD
    latest_report_filed TEXT,          -- newest 10-K/10-Q style filing date
    latest_report_accession TEXT,
    source TEXT NOT NULL, fetched_at TEXT NOT NULL
);

-- Every reported figure for the tags in screener.concepts, exactly as filed.
-- The same period appears once per filing that reported it, so restatements
-- are separate rows and "what was known on date X" is: filed <= X.
-- period_start is '' for balance-sheet (point in time) figures.
CREATE TABLE IF NOT EXISTS fundamentals_facts (
    cik INTEGER NOT NULL, taxonomy TEXT NOT NULL, tag TEXT NOT NULL, unit TEXT NOT NULL,
    period_start TEXT NOT NULL DEFAULT '', period_end TEXT NOT NULL,
    value REAL NOT NULL,
    fy INTEGER, fp TEXT,               -- fiscal year/period of the FILING, not of this figure
    form TEXT, filed TEXT NOT NULL, accession TEXT NOT NULL, frame TEXT,
    PRIMARY KEY (cik, taxonomy, tag, unit, period_end, period_start, accession)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS fundamentals_meta (
    cik INTEGER PRIMARY KEY, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
    facts_total INTEGER, facts_stored INTEGER
);

-- Statement lines as the price/profile provider reports them (recent years only).
CREATE TABLE IF NOT EXISTS statement_items (
    ticker TEXT NOT NULL, statement TEXT NOT NULL, freq TEXT NOT NULL,
    period_end TEXT NOT NULL, item TEXT NOT NULL, value REAL NOT NULL,
    source TEXT NOT NULL, fetched_at TEXT NOT NULL,
    PRIMARY KEY (ticker, statement, freq, period_end, item)
) WITHOUT ROWID;

-- value_pct is in percent, as published (1.23 means 1.23%).
CREATE TABLE IF NOT EXISTS factor_returns (
    dataset TEXT NOT NULL, freq TEXT NOT NULL, date TEXT NOT NULL, factor TEXT NOT NULL,
    value_pct REAL NOT NULL,
    PRIMARY KEY (dataset, freq, date, factor)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS factor_meta (
    dataset TEXT NOT NULL, freq TEXT NOT NULL, source TEXT NOT NULL, fetched_at TEXT NOT NULL,
    first_date TEXT, last_date TEXT, rows INTEGER,
    PRIMARY KEY (dataset, freq)
);

CREATE TABLE IF NOT EXISTS refresh_log (
    step TEXT NOT NULL, key TEXT NOT NULL,
    last_attempt TEXT NOT NULL, last_success TEXT,
    status TEXT NOT NULL,              -- ok | error
    error TEXT, detail TEXT,
    PRIMARY KEY (step, key)
);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
    conn.row_factory = sqlite3.Row
    return conn


def log_ok(conn: sqlite3.Connection, step: str, key: str, detail: str = "") -> None:
    ts = now_utc()
    conn.execute(
        "INSERT INTO refresh_log(step,key,last_attempt,last_success,status,error,detail) "
        "VALUES(?,?,?,?,'ok',NULL,?) ON CONFLICT(step,key) DO UPDATE SET "
        "last_attempt=excluded.last_attempt,last_success=excluded.last_success,"
        "status='ok',error=NULL,detail=excluded.detail",
        (step, key, ts, ts, detail),
    )
    conn.commit()


def log_error(conn: sqlite3.Connection, step: str, key: str, error: str) -> None:
    conn.rollback()
    conn.execute(
        "INSERT INTO refresh_log(step,key,last_attempt,last_success,status,error,detail) "
        "VALUES(?,?,?,NULL,'error',?,NULL) ON CONFLICT(step,key) DO UPDATE SET "
        "last_attempt=excluded.last_attempt,status='error',error=excluded.error",
        (step, key, now_utc(), error[:500]),
    )
    conn.commit()


def is_fresh(conn: sqlite3.Connection, step: str, key: str, max_age_hours: float) -> bool:
    row = conn.execute(
        "SELECT (julianday('now') - julianday(last_success)) * 24 AS age, status "
        "FROM refresh_log WHERE step=? AND key=?",
        (step, key),
    ).fetchone()
    return bool(row and row["status"] == "ok" and row["age"] is not None and row["age"] < max_age_hours)
