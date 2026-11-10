"""S&P 500 constituents from Wikipedia's "List of S&P 500 companies".

There is no free official list. This table is community-maintained and usually
current within days of an index change. It gives today's members only.
"""

from __future__ import annotations

import io

import pandas as pd

from screener.providers.base import DataProvider, Member, NotSupported, ProviderError
from screener.providers.http import ThrottledClient

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = "personal-stock-screener/0.1 (local research tool)"


def _text(value) -> str | None:
    return None if pd.isna(value) else str(value).strip() or None


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
