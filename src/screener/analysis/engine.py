"""Turns cached data into the tables the app reads.

history(): for every company and fiscal year, the statement lines and the
  fundamental measures, computed from what the annual report showed on the day
  it was filed (`available`).
cross_section(): for one date, each company's latest available fiscal year
  joined with price measures, market value, valuation, quality z-scores and
  percentile ranks. The screener uses today's; the backtest calls it per
  rebalance date, so both see exactly the same calculations.
"""

from __future__ import annotations

import math
import sqlite3

import numpy as np
import pandas as pd

from screener.analysis import formulas as F
from screener.analysis.catalog import BY_KEY, DEFAULT_WEIGHTS, NOT_FOR_FINANCIALS, RANKED
from screener.analysis.prices import PriceData, price_measures
from screener.analysis.statements import DERIVED_NOTES, annual_view, derive, load_facts, report_dates

KEEP_LINES = ["revenue", "gross_profit", "ebit", "net_income", "cfo", "capex", "free_cash_flow",
              "total_assets", "total_liabilities", "equity", "total_debt", "cash_and_short_term",
              "current_assets", "current_liabilities", "retained_earnings", "working_capital",
              "shares", "minority_interest", "preferred_stock", "eps_diluted", "dividends_paid"]
STALE_AFTER_DAYS = 550        # a fiscal year older than this is not used as "latest"
MIN_SECTOR_SIZE = 5


def is_financial(gics_sector: str | None, sic: str | None) -> bool:
    """Banks, insurers, brokers and other financials, for which Altman Z and Beneish M
    are not meaningful: GICS sector Financials, or an SEC industry code in 6000-6499
    (banks, credit, brokers, insurance) or 6700-6799 except 6798 (REITs)."""
    if gics_sector == "Financials":
        return True
    try:
        code = int(sic or 0)
    except ValueError:
        return False
    return 6000 <= code <= 6499 or (6700 <= code <= 6799 and code != 6798)


def _row_near(values: pd.DataFrame, end: str, years_back: int) -> dict | None:
    """The fiscal year ending about `years_back` years before `end`, if present."""
    target = pd.Timestamp(end) - pd.DateOffset(years=years_back)
    for other in values.index:
        if abs((pd.Timestamp(other) - target).days) <= 45:
            return values.loc[other].to_dict()
    return None


def company_history(facts: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per fiscal year. Each year is computed from the filings available
    on the day its annual report was filed, so later restatements do not leak in.
    Also returns, for the latest year, which lines were derived and from which tags."""
    rows, latest_sources = [], {}
    dates = report_dates(facts)
    for end, available in dates.items():
        raw, tags = annual_view(facts, as_of=available)
        if end not in raw.index:
            continue
        values, derived = derive(raw)
        cur = values.loc[end].to_dict()
        prev, prev2 = _row_near(values, end, 1), _row_near(values, end, 2)
        y5, y6 = _row_near(values, end, 5), _row_near(values, end, 6)
        roe_history = []
        for back in range(4, -1, -1):
            year = cur if back == 0 else _row_near(values, end, back)
            be = F.book_equity(year)
            roe_history.append(F.div(F.g(year, "net_income"), be) if be > 0 else F.NAN)
        row = {"period_end": end, "available": available}
        row.update({k: cur.get(k, F.NAN) for k in KEEP_LINES})
        row.update(F.piotroski(cur, prev, prev2))
        row.update(F.beneish_m(cur, prev))
        row.update(F.accruals(cur, prev))
        row["gross_profitability"] = F.gross_profitability(cur)
        row["asset_growth"] = F.asset_growth(cur, prev)
        row.update(F.quality_inputs(cur, prev, y5, y6, roe_history))
        rows.append(row)
        if end == dates.index[-1]:
            latest_sources = {
                "period_end": end, "available": available,
                "derived": {c: DERIVED_NOTES[c] for c in derived.columns if bool(derived.loc[end, c])},
                "tags": {c: t for c, t in tags.loc[end].dropna().items()},
            }
    return pd.DataFrame(rows), latest_sources


def build_history(conn: sqlite3.Connection, universe: str, progress=None) -> tuple[pd.DataFrame, dict]:
    companies = conn.execute(
        "SELECT DISTINCT cik FROM universe_membership WHERE universe=? AND cik IS NOT NULL", (universe,)).fetchall()
    frames, sources = [], {}
    for n, row in enumerate(companies, 1):
        facts = load_facts(conn, row["cik"])
        if facts.empty:
            continue
        hist, src = company_history(facts)
        if not hist.empty:
            hist.insert(0, "cik", row["cik"])
            frames.append(hist)
            sources[row["cik"]] = src
        if progress and n % 100 == 0:
            progress(n, len(companies))
    history = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return history, sources


def rank_z(x: pd.Series) -> pd.Series:
    """z-score of cross-sectional ranks, as in Asness, Frazzini and Pedersen (2019)."""
    r = x.rank()
    sd = r.std()
    return (r - r.mean()) / sd if sd and not math.isnan(sd) else r * np.nan


def percentile(x: pd.Series, better: int) -> pd.Series:
    """0-100 within the group, 100 = most favourable. Ties share the average rank."""
    n = x.notna().sum()
    if n < 2:
        return x * np.nan
    r = (x.rank() - 1) / (n - 1) * 100
    return 100 - r if better < 0 else r


def composite(frame: pd.DataFrame, weights: dict[str, float], suffix: str = "__pct") -> pd.Series:
    """Weighted average of percentile ranks. A stock missing some measures is
    scored on the rest, provided at least half of the total weight is present."""
    weights = {k: w for k, w in weights.items() if w > 0 and f"{k}{suffix}" in frame}
    if not weights:
        return pd.Series(np.nan, index=frame.index)
    cols = pd.concat([frame[f"{k}{suffix}"] for k in weights], axis=1)
    w = np.array(list(weights.values()), dtype=float)
    present = cols.notna().values * w
    total = present.sum(axis=1)
    score = np.nansum(cols.values * w, axis=1) / np.where(total > 0, total, np.nan)
    return pd.Series(np.where(total >= w.sum() / 2, score, np.nan), index=frame.index)


def add_ranks(frame: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Percentiles within the universe (__pct) and within the sector (__spct),
    group scores and the composite."""
    out = frame.copy()
    extra = {}

    def rank_all(key: str) -> None:
        better = BY_KEY[key].better
        extra[f"{key}__pct"] = percentile(out[key], better)
        by_sector = out.groupby("sector")[key]
        sized = by_sector.transform(lambda s: s.notna().sum())
        extra[f"{key}__spct"] = by_sector.transform(lambda s: percentile(s, better)).where(sized >= MIN_SECTOR_SIZE)

    for key in RANKED:
        if key in out and key not in ("value_score", "low_risk_score"):
            rank_all(key)
    for score, parts in (("value_score", ["book_to_market", "earnings_yield", "ebit_ev", "fcf_yield"]),
                         ("low_risk_score", ["beta", "vol_1y"])):
        for suffix in ("__pct", "__spct"):
            cols = pd.concat([extra[f"{p}{suffix}"] for p in parts if f"{p}{suffix}" in extra], axis=1)
            enough = cols.notna().sum(axis=1) >= math.ceil(len(parts) / 2)
            extra[f"{score}{suffix}" if suffix == "__spct" else score] = cols.mean(axis=1).where(enough)
        extra[f"{score}__pct"] = extra[score]
    out = pd.concat([out.drop(columns=[c for c in extra if c in out]), pd.DataFrame(extra, index=out.index)], axis=1)
    out["composite"] = composite(out, weights or DEFAULT_WEIGHTS)
    out["composite__pct"] = out["composite"]
    return out


def cross_section(members: pd.DataFrame, history: pd.DataFrame, px: PriceData, date: str,
                  market_caps: pd.Series | None = None, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """One row per member ticker as of `date`.

    members: ticker, cik, name, sector, sub_industry, sic.
    market_caps: optional ticker -> market cap to use instead of price x shares
    (today's screen uses the provider's figure; history has to be computed)."""
    hist = history[history["available"] <= date]
    hist = hist.sort_values("period_end").drop_duplicates("cik", keep="last")
    age = (pd.Timestamp(date) - pd.to_datetime(hist["period_end"])).dt.days
    hist = hist[age <= STALE_AFTER_DAYS]
    frame = members.merge(hist, on="cik", how="left").set_index("ticker")
    frame = frame.join(price_measures(px, date), how="left")
    frame["financial"] = [is_financial(s, c) for s, c in zip(frame["sector"], frame["sic"])]

    factors = pd.Series([px.split_factor_after(t, a) if isinstance(a, str) else np.nan
                         for t, a in zip(frame.index, frame["available"])], index=frame.index)
    frame["market_cap_computed"] = frame["price"] * frame["shares"] * factors
    frame["market_cap"] = frame["market_cap_computed"]
    frame["market_cap_source"] = np.where(frame["market_cap"].notna(), "price x filed shares", None)
    if market_caps is not None:
        given = market_caps.reindex(frame.index)
        frame["market_cap"] = given.fillna(frame["market_cap"])
        frame.loc[given.notna(), "market_cap_source"] = "provider"

    records = frame.to_dict("index")
    value_rows, z_rows = {}, {}
    for ticker, r in records.items():
        value_rows[ticker] = F.valuation(r, F.g(r, "market_cap"))
        z_rows[ticker] = F.altman_z(r, F.g(r, "market_cap"))
    frame = frame.join(pd.DataFrame.from_dict(value_rows, orient="index"))
    frame = frame.join(pd.DataFrame.from_dict(z_rows, orient="index"))
    frame.loc[frame["financial"], list(NOT_FOR_FINANCIALS)] = np.nan

    # Quality composite: z-scores of ranks, averaged over whichever parts exist.
    def z(col: str, sign: int = 1) -> pd.Series:
        return rank_z(sign * frame[col]) if col in frame else pd.Series(np.nan, index=frame.index)

    frame["q_profitability"] = pd.concat([z("q_gpoa"), z("q_roe"), z("q_roa"), z("q_cfoa"), z("q_gmar"), z("q_acc")],
                                         axis=1).mean(axis=1)
    frame["q_growth"] = pd.concat([z("q_d_gpoa"), z("q_d_roe"), z("q_d_roa"), z("q_d_cfoa"), z("q_d_gmar")],
                                  axis=1).mean(axis=1)
    frame["q_safety"] = pd.concat([z("beta", -1), z("q_lev", -1), z("altman_z"), z("q_evol", -1)], axis=1).mean(axis=1)
    parts = frame[["q_profitability", "q_growth", "q_safety"]]
    frame["quality"] = rank_z(parts.mean(axis=1).where(frame["q_profitability"].notna()))
    frame["as_of"] = date
    return add_ranks(frame, weights)
