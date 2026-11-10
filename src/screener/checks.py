"""Cross-check filed (EDGAR) figures against the statements provider (Yahoo).

Two independent routes to the same number: agreement is evidence the tag
mapping picked the right line; disagreement or a gap flags a company to look at.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pandas as pd

from screener.fundamentals import annual_series, instant_series

# concept -> (statement, provider's line name, sign to apply to the provider value)
CROSSCHECK = {
    "revenue": ("income", "Total Revenue", 1),
    "gross_profit": ("income", "Gross Profit", 1),
    "operating_income": ("income", "Operating Income", 1),
    "net_income": ("income", "Net Income", 1),
    "total_assets": ("balance", "Total Assets", 1),
    "total_liabilities": ("balance", "Total Liabilities Net Minority Interest", 1),
    "equity": ("balance", "Stockholders Equity", 1),
    "cfo": ("cashflow", "Operating Cash Flow", 1),
    "capex": ("cashflow", "Capital Expenditure", -1),   # Yahoo shows the outflow as negative
}
MATCH_TOLERANCE = 0.005      # 0.5%
DATE_TOLERANCE_DAYS = 10     # Yahoo rounds period ends to the month end


def compare(conn: sqlite3.Connection, ticker: str, cik: int, years: int = 4) -> pd.DataFrame:
    """Latest `years` fiscal years, EDGAR next to the provider, one row per concept and year.
    A side with no value is None; diff_pct is None unless both sides have one."""
    theirs = pd.read_sql_query(
        "SELECT statement, item, period_end, value FROM statement_items "
        "WHERE ticker=? AND freq='annual'", conn, params=(ticker,))
    theirs["when"] = pd.to_datetime(theirs["period_end"])
    rows = []
    for concept, (statement, item, sign) in CROSSCHECK.items():
        ours = annual_series(conn, cik, concept).tail(years)
        other = theirs[(theirs["statement"] == statement) & (theirs["item"] == item)]
        used = set()
        for r in ours.itertuples(index=False):
            near = other[(other["when"] - pd.Timestamp(r.period_end)).abs().dt.days <= DATE_TOLERANCE_DAYS]
            value = None
            if not near.empty:
                value = sign * float(near.iloc[0]["value"])
                used.add(near.iloc[0]["period_end"])
            diff = None if value is None or r.value == 0 else (value - r.value) / abs(r.value)
            rows.append({"concept": concept, "period_end": r.period_end, "edgar": r.value,
                         "provider": value, "diff_pct": diff, "tag": r.tag, "filed": r.filed,
                         "accession": r.accession, "restated": r.restated})
        latest_ours = ours["period_end"].max() if not ours.empty else ""
        for o in other.sort_values("when").tail(years).itertuples(index=False):
            # provider has a year EDGAR lacks (only newer years: Yahoo's window is short)
            if o.period_end not in used and (not latest_ours or o.when > pd.Timestamp(latest_ours)
                                             + pd.Timedelta(days=DATE_TOLERANCE_DAYS)):
                rows.append({"concept": concept, "period_end": o.period_end, "edgar": None,
                             "provider": sign * float(o.value), "diff_pct": None, "tag": None,
                             "filed": None, "accession": None, "restated": None})
    return pd.DataFrame(rows, columns=["concept", "period_end", "edgar", "provider", "diff_pct",
                                       "tag", "filed", "accession", "restated"])


def universe_summary(conn: sqlite3.Connection, universe: str) -> pd.DataFrame:
    """Per concept, for each company's most recent fiscal year on the provider side:
    how many agree, disagree, or are missing from EDGAR under the current tag mapping."""
    members = conn.execute(
        "SELECT ticker, cik FROM universe_membership WHERE universe=? AND removed_on IS NULL "
        "AND cik IS NOT NULL ORDER BY ticker", (universe,)).fetchall()
    tally: dict[str, dict[str, list[str]]] = {
        c: {"match": [], "mismatch": [], "edgar_missing": [], "provider_missing": []} for c in CROSSCHECK}
    for m in members:
        theirs = pd.read_sql_query(
            "SELECT statement, item, period_end, value FROM statement_items "
            "WHERE ticker=? AND freq='annual'", conn, params=(m["ticker"],))
        if theirs.empty:
            continue
        theirs["when"] = pd.to_datetime(theirs["period_end"])
        for concept, (statement, item, sign) in CROSSCHECK.items():
            other = theirs[(theirs["statement"] == statement) & (theirs["item"] == item)]
            ours = annual_series(conn, m["cik"], concept)
            if other.empty:
                if not ours.empty:
                    tally[concept]["provider_missing"].append(m["ticker"])
                continue
            latest = other.sort_values("when").iloc[-1]
            near = ours[(pd.to_datetime(ours["period_end"]) - latest["when"]).abs().dt.days
                        <= DATE_TOLERANCE_DAYS]
            if near.empty:
                tally[concept]["edgar_missing"].append(m["ticker"])
                continue
            ours_value, their_value = float(near.iloc[-1]["value"]), sign * float(latest["value"])
            close = abs(their_value - ours_value) <= MATCH_TOLERANCE * max(abs(ours_value), 1.0)
            tally[concept]["match" if close else "mismatch"].append(m["ticker"])
    return pd.DataFrame([{"concept": c, **{k: len(v) for k, v in groups.items()},
                          "mismatch_tickers": " ".join(groups["mismatch"][:12]),
                          "edgar_missing_tickers": " ".join(groups["edgar_missing"][:12])}
                         for c, groups in tally.items()])


def short_histories(conn: sqlite3.Connection, universe: str, floor: str = "2012-01-01",
                    slack_years: int = 2) -> pd.DataFrame:
    """Companies whose filed fundamentals start well after their price history.

    Usually this means earlier filings sit under a predecessor SEC registrant
    (see reference/cik_predecessors.toml); it can also be a genuine gap. Companies
    with no filed facts at all are listed with first_filed empty.
    """
    df = pd.read_sql_query(
        "SELECT u.ticker, u.name, u.cik, p.first_date AS price_start, "
        " (SELECT MIN(filed) FROM fundamentals_facts f WHERE f.cik=u.cik "
        "   AND f.form IN ('10-K','10-Q','20-F','40-F')) AS first_filed "
        "FROM universe_membership u LEFT JOIN price_series_meta p ON p.ticker=u.ticker "
        "WHERE u.universe=? AND u.removed_on IS NULL ORDER BY u.ticker", conn, params=(universe,))
    start = pd.to_datetime(df["price_start"]).fillna(pd.Timestamp(floor))
    expected = (start + pd.DateOffset(years=slack_years)).clip(lower=pd.Timestamp(floor))
    late = df["first_filed"].isna() | (pd.to_datetime(df["first_filed"]) > expected)
    return df[late].reset_index(drop=True)


def concept_gaps(conn: sqlite3.Connection, universe: str, stale_months: int = 18) -> pd.DataFrame:
    """Per concept: how many companies have a recent fiscal-year value, an outdated
    one (latest year ended more than `stale_months` ago), or none at all, under
    the current tag mapping."""
    from screener.concepts import CONCEPTS

    cutoff = (date.today() - timedelta(days=30.4 * stale_months)).isoformat()
    companies = conn.execute(
        "SELECT MIN(ticker) AS ticker, cik FROM universe_membership WHERE universe=? "
        "AND removed_on IS NULL AND cik IS NOT NULL GROUP BY cik ORDER BY 1", (universe,)).fetchall()
    rows = []
    for key, concept in CONCEPTS.items():
        outdated, absent = [], []
        for c in companies:
            # cover-page share counts are dated a few weeks after the period end
            read = instant_series if concept.taxonomy == "dei" else annual_series
            series = read(conn, c["cik"], concept)
            if series.empty:
                absent.append(c["ticker"])
            elif series["period_end"].max() < cutoff:
                outdated.append(c["ticker"])
        rows.append({"concept": key, "current": len(companies) - len(outdated) - len(absent),
                     "outdated": len(outdated), "none": len(absent),
                     "outdated_tickers": " ".join(outdated), "none_tickers": " ".join(absent)})
    return pd.DataFrame(rows)
