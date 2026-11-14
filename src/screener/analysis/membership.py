"""Who was in the index on a given date.

Built from today's member list and the record of additions and removals
(`universe_changes`, from Wikipedia's "Historical components" article). The
backtest uses it so that on each rebalance date only that date's members are
eligible: a company that joined in 2020 is not in the 2015 universe just
because it is in the index today.

The record is reasonably complete from about 2011 and thin before 2007, so
membership before then is mostly "today's members", as it was without this.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

import pandas as pd

UNKNOWN = ""        # start: member since before the record begins; end: still a member
COLUMNS = ["ticker", "start", "end"]


def intervals(current: Iterable[str], changes: pd.DataFrame) -> pd.DataFrame:
    """Membership intervals [start, end) per ticker. `changes` has columns
    date, action ('added' | 'removed'), ticker, ascending or not.

    Rules, chosen so that a wrong company is never counted as a member:
    - a current member with no recorded addition is a member since UNKNOWN;
    - a removal with no earlier addition closes an interval that started at UNKNOWN;
    - a ticker that was added, never removed and is not a current member was
      renamed or the record is incomplete: nobody knows when it left, so it is
      never eligible (an empty interval), rather than eligible until today;
    - a current member whose last event is a removal (the record missed a
      re-addition) is a member again from that date.
    """
    current = set(current)
    rows: list[tuple[str, str, str]] = []
    if changes.empty:
        return pd.DataFrame([(t, UNKNOWN, UNKNOWN) for t in sorted(current)], columns=COLUMNS)
    order = changes.assign(_o=(changes["action"] == "added").astype(int)).sort_values(["date", "_o"], kind="stable")
    seen = set()
    for ticker, events in order.groupby("ticker", sort=True):
        seen.add(ticker)
        open_start: str | None = None
        last_action, last_date = None, None
        for e in events.itertuples(index=False):
            if e.action == "added":
                if open_start is None:
                    open_start = e.date
            elif e.action == "removed":
                rows.append((ticker, UNKNOWN if open_start is None else open_start, e.date))
                open_start = None
            last_action, last_date = e.action, e.date
        if ticker in current:
            if open_start is None:
                open_start = last_date if last_action == "removed" else UNKNOWN
            rows.append((ticker, open_start, UNKNOWN))
        elif open_start is not None:
            rows.append((ticker, open_start, open_start))     # empty: never eligible
    rows += [(t, UNKNOWN, UNKNOWN) for t in sorted(current - seen)]
    return pd.DataFrame(rows, columns=COLUMNS).sort_values(["ticker", "start"]).reset_index(drop=True)


def members_on(table: pd.DataFrame, date: str) -> set[str]:
    """Tickers whose interval contains `date` (ISO strings compare as dates)."""
    starts_ok = (table["start"] == UNKNOWN) | (table["start"] <= date)
    ends_ok = (table["end"] == UNKNOWN) | (table["end"] > date)
    return set(table.loc[starts_ok & ends_ok, "ticker"])


def load_changes(conn: sqlite3.Connection, universe: str) -> pd.DataFrame:
    return pd.read_sql_query(
        "SELECT date, action, ticker, name, reason FROM universe_changes WHERE universe=? ORDER BY date",
        conn, params=(universe,))


def load_intervals(conn: sqlite3.Connection, universe: str) -> pd.DataFrame | None:
    """None when no change record is cached (the backtest then uses today's members)."""
    changes = load_changes(conn, universe)
    if changes.empty:
        return None
    current = [r[0] for r in conn.execute(
        "SELECT ticker FROM universe_membership WHERE universe=? AND removed_on IS NULL", (universe,))]
    return intervals(current, changes)
