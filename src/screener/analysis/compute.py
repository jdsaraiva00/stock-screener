"""`screener compute`: rebuild the analysis tables from the cache.

Writes fundamental_history, snapshot, insights and statement_sources. Reads
nothing from the network. Runs automatically at the end of a refresh.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time

import numpy as np
import pandas as pd

from screener import db
from screener.analysis.engine import build_history, cross_section
from screener.analysis.insights import insights_for
from screener.analysis.prices import PriceData

log = logging.getLogger("screener.compute")


def load_members(conn: sqlite3.Connection, universe: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT u.ticker, u.cik, u.name, u.gics_sector AS sector, u.gics_sub_industry AS sub_industry, "
        "f.sic, f.sic_description, p.sector AS provider_sector, p.industry AS provider_industry "
        "FROM universe_membership u LEFT JOIN filer_info f ON f.cik=u.cik "
        "LEFT JOIN company_profile p ON p.ticker=u.ticker "
        "WHERE u.universe=? AND u.removed_on IS NULL ORDER BY u.ticker", conn, params=(universe,))


def load_history(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM fundamental_history", conn)


def _json_safe(value):
    if isinstance(value, (float, np.floating)):
        return None if np.isnan(value) or np.isinf(value) else float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def run(conn: sqlite3.Connection, universe: str) -> dict:
    started = time.time()
    history, sources = build_history(
        conn, universe, progress=lambda n, total: log.info("history: %d of %d companies", n, total))
    if history.empty:
        raise RuntimeError("no filed fundamentals in the cache; run `screener refresh` first")
    px = PriceData.load(conn)
    members = load_members(conn, universe)
    as_of = px.adj.index[-1]
    caps = pd.read_sql_query("SELECT ticker, market_cap FROM company_profile", conn).set_index("ticker")["market_cap"]
    snap = cross_section(members, history, px, as_of, market_caps=caps.dropna())

    latest_two = history.sort_values("period_end").groupby("cik").tail(2)
    previous = {cik: rows.iloc[0].to_dict() for cik, rows in latest_two.groupby("cik") if len(rows) == 2}
    insight_rows = []
    for ticker, row in snap.iterrows():
        items = insights_for(row.to_dict(), previous.get(row["cik"]))
        insight_rows.append((ticker, json.dumps(items)))

    history.to_sql("fundamental_history", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_history_cik ON fundamental_history(cik, period_end)")
    snap.reset_index().to_sql("snapshot", conn, if_exists="replace", index=False)
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS insights (ticker TEXT PRIMARY KEY, items TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS statement_sources (cik INTEGER PRIMARY KEY, detail TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS analysis_meta (key TEXT PRIMARY KEY, value TEXT);"
        "DELETE FROM insights; DELETE FROM statement_sources;")
    conn.executemany("INSERT INTO insights VALUES(?,?)", insight_rows)
    conn.executemany("INSERT INTO statement_sources VALUES(?,?)",
                     [(int(cik), json.dumps({k: _json_safe(v) if not isinstance(v, dict) else v
                                             for k, v in src.items()})) for cik, src in sources.items()])
    summary = {"as_of": as_of, "computed_at": db.now_utc(), "companies": int(history["cik"].nunique()),
               "history_rows": len(history), "snapshot_rows": len(snap),
               "seconds": round(time.time() - started, 1)}
    conn.executemany("INSERT OR REPLACE INTO analysis_meta VALUES(?,?)", [(k, str(v)) for k, v in summary.items()])
    conn.commit()
    return summary
