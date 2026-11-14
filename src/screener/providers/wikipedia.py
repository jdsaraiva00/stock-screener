"""S&P 500 constituents from Wikipedia's "List of S&P 500 companies", and the
record of additions and removals from "Historical components of the S&P 500".

There is no free official list. Both tables are community-maintained; the
member list is usually current within days of an index change. The change
record is reasonably complete from about 2011, thin for 2007-2010 and nearly
empty before, which the backtest states.
"""

from __future__ import annotations

import io

import pandas as pd

from screener.providers.base import Change, DataProvider, Member, NotSupported, ProviderError
from screener.providers.http import ThrottledClient

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
USER_AGENT = "personal-stock-screener/0.1 (local research tool)"
CHANGE_COLUMNS = ["Effective Date", "Added Ticker", "Added Security", "Removed Ticker", "Removed Security", "Reason"]


def _text(value) -> str | None:
    return None if pd.isna(value) else str(value).strip() or None


def _ticker(value) -> str | None:
    """Symbols as Yahoo and the SEC write them; the page has a few 'ABC |' artefacts."""
    text = _text(value)
    if text is None:
        return None
    return text.rstrip("|").strip().replace(".", "-") or None


def parse_changes(html: str, min_rows: int = 300) -> list[Change]:
    """Every addition and removal in the changes table, one Change per side."""
    try:
        table = pd.read_html(io.StringIO(html), attrs={"id": "changes"}, flavor="lxml")[0]
    except ValueError as exc:
        raise ProviderError(f"changes table not found on the Wikipedia page: {exc}") from exc
    # The header has two levels (Added / Ticker); flatten and drop repeats (Reason / Reason).
    table.columns = [" ".join(dict.fromkeys(str(p) for p in (c if isinstance(c, tuple) else (c,))))
                     for c in table.columns]
    missing = set(CHANGE_COLUMNS) - set(table.columns)
    if missing:
        raise ProviderError(f"Wikipedia changes table layout changed, missing columns: {sorted(missing)}")
    if len(table) < min_rows:
        raise ProviderError(f"expected at least {min_rows} recorded changes, found {len(table)}")
    changes = []
    for row in table.to_dict("records"):
        when = pd.to_datetime(row["Effective Date"], errors="coerce")
        if pd.isna(when):
            continue
        reason = _text(row["Reason"])
        for action, ticker_col, name_col in (("added", "Added Ticker", "Added Security"),
                                             ("removed", "Removed Ticker", "Removed Security")):
            ticker = _ticker(row[ticker_col])
            if ticker:
                changes.append(Change(when.date().isoformat(), action, ticker, _text(row[name_col]), reason))
    return changes


def parse_constituents(html: str, min_rows: int = 450, max_rows: int = 520) -> list[Member]:
    try:
        table = pd.read_html(io.StringIO(html), attrs={"id": "constituents"}, flavor="lxml")[0]
    except ValueError as exc:
        raise ProviderError(f"constituents table not found on the Wikipedia page: {exc}") from exc
    needed = {"Symbol", "Security", "GICS Sector", "GICS Sub-Industry", "Date added", "CIK"}
    missing = needed - set(table.columns)
    if missing:
        raise ProviderError(f"Wikipedia table layout changed, missing columns: {sorted(missing)}")
    # A page edit or layout change must not silently shrink the universe.
    if not min_rows <= len(table) <= max_rows:
        raise ProviderError(f"expected about 500 constituents, found {len(table)}")
    members = []
    for row in table.to_dict("records"):
        added = pd.to_datetime(row["Date added"], errors="coerce")
        cik = pd.to_numeric(row["CIK"], errors="coerce")
        members.append(Member(
            ticker=str(row["Symbol"]).strip().replace(".", "-"),
            name=_text(row["Security"]),
            cik=None if pd.isna(cik) else int(cik),
            sector=_text(row["GICS Sector"]),
            sub_industry=_text(row["GICS Sub-Industry"]),
            date_added=None if pd.isna(added) else added.date().isoformat(),
        ))
    return members


class WikipediaProvider(DataProvider):
    name = "wikipedia"

    def __init__(self, cfg):
        self.http = ThrottledClient(1, USER_AGENT)

    def universe_members(self, universe: str) -> list[Member]:
        if universe != "sp500":
            raise NotSupported(f"wikipedia provider only knows the sp500 universe, not {universe!r}")
        return parse_constituents(self.http.get(URL).text)

    def universe_changes(self, universe: str) -> list[Change]:
        if universe != "sp500":
            raise NotSupported(f"wikipedia provider only knows the sp500 universe, not {universe!r}")
        return parse_changes(self.http.get(CHANGES_URL).text)
