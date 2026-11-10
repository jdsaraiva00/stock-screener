"""A company's annual statements as a table, as they were known on a given date.

`annual_view` resolves every concept for every fiscal year in one pass over the
company's filed facts. `derive` then adds the lines that formulas need but
companies do not always report as such, each flagged so the UI can say so.
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from screener.concepts import CONCEPTS
from screener.fundamentals import ANNUAL_DAYS, ANNUAL_FORMS, STATEMENT_FORMS, _FYE_CONCEPTS

_TAG_INDEX = {(c.taxonomy, tag, c.unit): (c.key, rank)
              for c in CONCEPTS.values() for rank, tag in enumerate(c.tags)}
_FYE_TAGS = {tag for key in _FYE_CONCEPTS for tag in CONCEPTS[key].tags}


def load_facts(conn: sqlite3.Connection, cik: int) -> pd.DataFrame:
    """All of a company's facts from periodic reports, oldest filing first."""
    marks = ",".join("?" * len(STATEMENT_FORMS))
    df = pd.read_sql_query(
        f"SELECT taxonomy, tag, unit, period_start, period_end, value, form, filed, accession "
        f"FROM fundamentals_facts WHERE cik=? AND form IN ({marks}) ORDER BY filed, accession",
        conn, params=[cik, *STATEMENT_FORMS])
    keys = pd.Series(list(zip(df["taxonomy"], df["tag"], df["unit"])), index=df.index)
    mapped = keys.map(_TAG_INDEX)
    df = df[mapped.notna()].copy()
    df["concept"] = [m[0] for m in mapped.dropna()]
    df["rank"] = [m[1] for m in mapped.dropna()]
    start = pd.to_datetime(df["period_start"].where(df["period_start"] != "", None))
    df["days"] = (pd.to_datetime(df["period_end"]) - start).dt.days
    df["full_year"] = df["days"].between(*ANNUAL_DAYS)
    return df.reset_index(drop=True)


def report_dates(facts: pd.DataFrame) -> pd.Series:
    """Fiscal year end -> date its annual report was first filed."""
    rows = facts[facts["full_year"] & facts["form"].isin(ANNUAL_FORMS) & facts["tag"].isin(_FYE_TAGS)]
    return rows.groupby("period_end")["filed"].min().sort_index()


def annual_view(facts: pd.DataFrame, as_of: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(values, tags): one row per fiscal year end, one column per concept, using only
    filings made on or before `as_of`. Where a period was reported more than once the
    latest filing wins; where several tags carry a concept the first listed wins."""
    f = facts if as_of is None else facts[facts["filed"] <= as_of]
    year_ends = set(report_dates(f).index)
    f = f.drop_duplicates(["tag", "unit", "period_start", "period_end"], keep="last")
    f = f[f["period_end"].isin(year_ends) & (f["full_year"] | (f["period_start"] == ""))]
    f = f.sort_values("rank", kind="stable").drop_duplicates(["concept", "period_end"])
    values = f.pivot(index="period_end", columns="concept", values="value").sort_index()
    tags = f.pivot(index="period_end", columns="concept", values="tag").sort_index()
    return values.reindex(columns=list(CONCEPTS)), tags.reindex(columns=list(CONCEPTS))


def _col(v: pd.DataFrame, name: str) -> pd.Series:
    return v[name] if name in v else pd.Series(np.nan, index=v.index)


def _sum_present(v: pd.DataFrame, names: list[str]) -> pd.Series:
    """Sum of the lines that are reported; missing only if none of them is."""
    cols = pd.concat([_col(v, n) for n in names], axis=1)
    return cols.sum(axis=1, min_count=1)


DERIVED_NOTES = {
    "net_income": "net income including minority interests, less the minority share where reported",
    "equity": "total equity less minority interests where reported",
    "gross_profit": "revenue minus cost of revenue",
    "total_liabilities": "total assets minus total equity (and temporary equity)",
    "ebit": "pre-tax income plus interest expense",
    "sga": "general and administrative plus selling and marketing",
    "cash_and_short_term": "cash plus short-term investments where reported",
}


def derive(values: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add derived lines. Returns (values, derived) where derived[c] is True for the
    years in which column c was computed here rather than reported."""
    v = values.copy()
    derived = pd.DataFrame(False, index=v.index, columns=list(DERIVED_NOTES))

    def fill(name: str, candidate: pd.Series) -> None:
        base = _col(v, name)
        use = base.isna() & candidate.notna()
        v[name] = base.where(~use, candidate)
        derived[name] = use

    # Net income to shareholders: ProfitLoss includes the minority owners' share.
    fill("net_income", _col(v, "profit_incl_minority") - _col(v, "minority_income").fillna(0))
    fill("equity", _col(v, "equity_incl_minority") - _col(v, "minority_interest").fillna(0))
    fill("gross_profit", _col(v, "revenue") - _col(v, "cost_of_revenue"))
    v["cost_of_revenue"] = _col(v, "cost_of_revenue").fillna(_col(v, "revenue") - _col(values, "gross_profit"))

    total_equity = _col(v, "equity_incl_minority").fillna(_col(v, "equity") + _col(v, "minority_interest").fillna(0))
    mezzanine = _col(v, "redeemable_minority").fillna(0) + _col(v, "temporary_equity").fillna(0)
    fill("total_liabilities", _col(v, "total_assets") - total_equity - mezzanine)

    v["ebit"] = _col(v, "operating_income")
    fill("ebit", _col(v, "pretax_income") + _col(v, "interest_expense"))
    fill("sga", _col(v, "general_admin") + _col(v, "selling_marketing"))
    fill("cash_and_short_term", _col(v, "cash") + _col(v, "short_term_investments").fillna(0))

    # Debt as presented: the sum of whichever debt lines the company tags.
    # If it tags none at all, debt is unknown (not assumed to be zero).
    current = _col(v, "debt_current_total").fillna(
        _sum_present(v, ["long_term_debt_current", "short_term_borrowings", "commercial_paper"]))
    noncurrent = _col(v, "long_term_debt").fillna(
        _col(v, "long_term_debt_total") - _col(v, "long_term_debt_current").fillna(0))
    any_debt = current.notna() | noncurrent.notna()
    v["debt_current"] = current.where(~any_debt, current.fillna(0))
    v["debt_noncurrent"] = noncurrent.where(~any_debt, noncurrent.fillna(0))
    v["total_debt"] = (v["debt_current"] + v["debt_noncurrent"]).fillna(_col(v, "debt_all"))

    v["working_capital"] = _col(v, "current_assets") - _col(v, "current_liabilities")
    v["free_cash_flow"] = _col(v, "cfo") - _col(v, "capex")
    # Shares: diluted weighted average covers all share classes; balance-sheet count as fallback.
    v["shares"] = _col(v, "shares_diluted").fillna(_col(v, "shares_outstanding"))
    return v, derived
