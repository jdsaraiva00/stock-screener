"""Read filed fundamentals from the cache as annual or quarterly series.

Every function takes `as_of`: only filings that had reached the SEC by that
date are used, which is what a backtest must pass. Without it the latest
filed value of each period is returned (restated where a later filing changed it).
"""

from __future__ import annotations

import sqlite3

import pandas as pd

from screener.concepts import CONCEPTS, Concept

ANNUAL_DAYS = (340, 380)      # 52/53-week and calendar fiscal years
QUARTER_DAYS = (80, 100)      # 12 to 14 week quarters
ANNUAL_FORMS = ("10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A")
# Only periodic financial reports feed the series. Other filings repeat some
# figures in XBRL (proxy statements carry net income for the pay-versus-performance
# table, often rounded) and would otherwise override the audited number.
STATEMENT_FORMS = ANNUAL_FORMS + ("10-Q", "10-Q/A", "10-QT")
_FYE_CONCEPTS = ("net_income", "revenue", "cfo")
COLUMNS = ["period_end", "value", "tag", "form", "filed", "accession",
           "first_filed", "first_value", "restated", "derived"]


def _concept(concept: str | Concept) -> Concept:
    return concept if isinstance(concept, Concept) else CONCEPTS[concept]


def _load(conn: sqlite3.Connection, cik: int, concept: Concept, as_of: str | None) -> pd.DataFrame:
    """One row per (tag, period): the latest filing's value, plus when and at what
    value the period was first reported."""
    marks = ",".join("?" * len(concept.tags))
    sql = (f"SELECT tag, period_start, period_end, value, form, filed, accession "
           f"FROM fundamentals_facts WHERE cik=? AND taxonomy=? AND unit=? AND tag IN ({marks}) "
           f"AND form IN ({','.join('?' * len(STATEMENT_FORMS))})")
    args: list = [cik, concept.taxonomy, concept.unit, *concept.tags, *STATEMENT_FORMS]
    if as_of:
        sql += " AND filed<=?"
        args.append(as_of)
    df = pd.read_sql_query(sql, conn, params=args)
    if df.empty:
        return df.assign(first_filed=[], first_value=[], rank=[], days=[])
    df = df.sort_values(["filed", "accession"], kind="stable")
    keys = ["tag", "period_start", "period_end"]
    grouped = df.groupby(keys, sort=False)
    latest = grouped.tail(1).set_index(keys)
    first = grouped.head(1).set_index(keys)
    latest["first_filed"] = first["filed"]
    latest["first_value"] = first["value"]
    out = latest.reset_index()
    out["rank"] = out["tag"].map({tag: i for i, tag in enumerate(concept.tags)})
    start = pd.to_datetime(out["period_start"].where(out["period_start"] != "", None))
    out["days"] = (pd.to_datetime(out["period_end"]) - start).dt.days
    return out


def _finish(df: pd.DataFrame) -> pd.DataFrame:
    """Per period keep the highest-priority tag, oldest period first.

    first_filed / first_value describe the earliest filing of the period under
    ANY candidate tag: a company that later re-tagged a line must not make the
    figure look as if it became known only when the new tag appeared.
    """
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    first = (df.sort_values(["period_end", "first_filed", "rank"], kind="stable")
             .drop_duplicates("period_end").set_index("period_end")[["first_filed", "first_value"]])
    df = (df.sort_values(["period_end", "rank"], kind="stable").drop_duplicates("period_end")
          .drop(columns=["first_filed", "first_value"]).join(first, on="period_end"))
    df = df.assign(restated=df["value"] != df["first_value"])
    if "derived" not in df:
        df = df.assign(derived=False)
    return df[COLUMNS].reset_index(drop=True)


def fiscal_year_ends(conn: sqlite3.Connection, cik: int, as_of: str | None = None) -> list[str]:
    """Fiscal year-end dates, taken from the full-year periods in annual reports."""
    tags = [t for key in _FYE_CONCEPTS for t in CONCEPTS[key].tags]
    sql = (f"SELECT DISTINCT period_end FROM fundamentals_facts WHERE cik=? AND period_start!='' "
           f"AND tag IN ({','.join('?' * len(tags))}) AND form IN ({','.join('?' * len(ANNUAL_FORMS))}) "
           f"AND julianday(period_end)-julianday(period_start) BETWEEN ? AND ?")
    args: list = [cik, *tags, *ANNUAL_FORMS, *ANNUAL_DAYS]
    if as_of:
        sql += " AND filed<=?"
        args.append(as_of)
    return sorted(r[0] for r in conn.execute(sql, args))


def annual_series(conn: sqlite3.Connection, cik: int, concept: str | Concept,
                  as_of: str | None = None) -> pd.DataFrame:
    """Fiscal-year values: full-year flows, or balances at fiscal year end."""
    concept = _concept(concept)
    df = _load(conn, cik, concept, as_of)
    if df.empty:
        return _finish(df)
    if concept.kind == "duration":
        df = df[df["days"].between(*ANNUAL_DAYS)]
    else:
        df = df[df["period_end"].isin(fiscal_year_ends(conn, cik, as_of))]
    return _finish(df)


def instant_series(conn: sqlite3.Connection, cik: int, concept: str | Concept,
                   as_of: str | None = None) -> pd.DataFrame:
    """Every reported balance date (year ends and quarter ends)."""
    concept = _concept(concept)
    if concept.kind != "instant":
        raise ValueError(f"{concept.key} is not a balance-sheet concept")
    return _finish(_load(conn, cik, concept, as_of))


def quarterly_series(conn: sqlite3.Connection, cik: int, concept: str | Concept,
                     as_of: str | None = None) -> pd.DataFrame:
    """Single-quarter flows.

    Companies do not report the fourth quarter on its own, and cash flow
    statements are year-to-date. Where a quarter is not reported directly it is
    derived as (year-to-date through this quarter) minus (year-to-date through
    the previous quarter), from the same tag, and flagged derived=True. A derived
    value counts as known only once both inputs were filed.
    """
    concept = _concept(concept)
    if concept.kind != "duration":
        raise ValueError(f"{concept.key} is a balance; use instant_series")
    df = _load(conn, cik, concept, as_of)
    if df.empty:
        return _finish(df)
    pieces = []
    for _, rows in df.groupby("tag", sort=False):
        direct = rows[rows["days"].between(*QUARTER_DAYS)].assign(derived=False)
        pieces.append(direct)
        have = set(direct["period_end"])
        by_start: dict[str, list] = {}
        for r in rows.itertuples(index=False):
            by_start.setdefault(r.period_start, []).append(r)
        for r in rows[rows["days"] > QUARTER_DAYS[1]].itertuples(index=False):
            if r.period_end in have:
                continue
            for prev in by_start[r.period_start]:
                gap = (pd.Timestamp(r.period_end) - pd.Timestamp(prev.period_end)).days
                if QUARTER_DAYS[0] <= gap <= QUARTER_DAYS[1]:
                    have.add(r.period_end)
                    pieces.append(pd.DataFrame([{
                        "tag": r.tag, "period_end": r.period_end, "rank": r.rank,
                        "value": r.value - prev.value, "form": r.form, "accession": r.accession,
                        "filed": max(r.filed, prev.filed),
                        "first_filed": max(r.first_filed, prev.first_filed),
                        "first_value": r.first_value - prev.first_value, "derived": True,
                    }]))
                    break
    return _finish(pd.concat([p for p in pieces if not p.empty], ignore_index=True)
                   if any(not p.empty for p in pieces) else df.iloc[0:0])
