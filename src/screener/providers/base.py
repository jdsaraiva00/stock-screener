"""The one interface every data source implements.

Analysis and UI code never import a concrete provider: they read the cache.
Only the refresh job calls providers, through this interface, so a paid API
can replace a free source by adding one class and changing [sources] in config.
A provider implements only the methods for the data it can supply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


class ProviderError(Exception):
    """A fetch failed for one key. The refresh job logs it and moves on."""


class NotSupported(ProviderError):
    pass


@dataclass(frozen=True)
class Member:
    ticker: str
    name: str | None
    cik: int | None
    sector: str | None
    sub_industry: str | None
    date_added: str | None


@dataclass(frozen=True)
class Profile:
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap: float | None
    shares_outstanding: float | None
    currency: str | None
    exchange: str | None
    quote_type: str | None


@dataclass(frozen=True)
class StatementItem:
    statement: str      # income | balance | cashflow
    freq: str           # annual | quarterly
    period_end: str
    item: str
    value: float


@dataclass(frozen=True)
class FilerInfo:
    cik: int
    name: str | None
    sic: str | None
    sic_description: str | None
    fiscal_year_end: str | None
    latest_report_filed: str | None
    latest_report_accession: str | None


@dataclass(frozen=True)
class Fact:
    """One reported figure, with the filing that reported it."""
    taxonomy: str
    tag: str
    unit: str
    period_start: str   # '' for point-in-time figures
    period_end: str
    value: float
    fy: int | None
    fp: str | None
    form: str | None
    filed: str
    accession: str
    frame: str | None


@dataclass(frozen=True)
class FactorSeries:
    dataset: str        # ff3 | ff5 | mom
    freq: str           # daily | monthly
    rows: list[tuple[str, str, float]]   # (date, factor, value in percent)


class DataProvider:
    name = "base"

    def universe_members(self, universe: str) -> list[Member]:
        raise NotSupported(f"{self.name} does not supply universe members")

    def prices(self, tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
        """Daily bars per ticker from `start`: columns date, open, high, low, close,
        adj_close, volume, dividend, split. Tickers with no data are left out."""
        raise NotSupported(f"{self.name} does not supply prices")

    def profile(self, ticker: str) -> Profile:
        raise NotSupported(f"{self.name} does not supply company profiles")

    def statements(self, ticker: str) -> list[StatementItem]:
        raise NotSupported(f"{self.name} does not supply statements")

    def filer_info(self, cik: int) -> FilerInfo:
        raise NotSupported(f"{self.name} does not supply filer information")

    def fundamentals(self, cik: int, offline: bool = False) -> Iterable[Fact]:
        """Every reported figure for a company. offline=True re-reads the provider's
        own raw copy without touching the network."""
        raise NotSupported(f"{self.name} does not supply filed fundamentals")

    def factor_datasets(self) -> list[tuple[str, str]]:
        """The (dataset, freq) pairs this provider can supply."""
        raise NotSupported(f"{self.name} does not supply factor returns")

    def factor_returns(self, dataset: str, freq: str) -> FactorSeries:
        raise NotSupported(f"{self.name} does not supply factor returns")
