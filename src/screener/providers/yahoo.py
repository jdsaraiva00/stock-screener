"""Yahoo Finance through the yfinance package: prices, profile, recent statements.

Unofficial and rate-limited; anything can fail for a ticker on a given day.
Yahoo's "Close" is split-adjusted; "Adj Close" is also dividend-adjusted, and
its whole history is rewritten after every dividend or split.
Statement period ends are rounded by Yahoo to the month end.
"""

from __future__ import annotations

import logging
import math
import time

import pandas as pd
import yfinance as yf

from screener.providers.base import DataProvider, Profile, ProviderError, StatementItem
from screener.providers.http import Throttle

logging.getLogger("yfinance").setLevel(logging.CRITICAL)

PRICE_COLUMNS = {
    "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
    "Volume": "volume", "Dividends": "dividend", "Stock Splits": "split",
}
STATEMENTS = [
    ("income", "annual", "income_stmt"), ("balance", "annual", "balance_sheet"),
    ("cashflow", "annual", "cashflow"), ("income", "quarterly", "quarterly_income_stmt"),
    ("balance", "quarterly", "quarterly_balance_sheet"), ("cashflow", "quarterly", "quarterly_cashflow"),
]


def _num(value) -> float | None:
    if value is None or isinstance(value, str):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) or math.isinf(number) else number


def tidy_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """One ticker's yfinance frame -> cache columns. Days without a close are dropped."""
    out = frame.rename(columns=PRICE_COLUMNS)
    out = out[[c for c in PRICE_COLUMNS.values() if c in out.columns]]
    out = out[out["close"].notna()].copy()
    out.insert(0, "date", pd.to_datetime(out.index).strftime("%Y-%m-%d"))
    return out.reset_index(drop=True)


class YahooProvider(DataProvider):
    name = "yfinance"

    def __init__(self, cfg):
        self.throttle = Throttle(cfg.yahoo_rps)
        self.retries = 3

    def _call(self, what: str, fn):
        problem = ""
        for attempt in range(self.retries + 1):
            self.throttle.wait()
            try:
                return fn()
            except Exception as exc:  # yfinance raises many unrelated types
                problem = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    rate_limited = "RateLimit" in type(exc).__name__ or "Too Many Requests" in str(exc)
                    time.sleep((30 if rate_limited else 2) * 2 ** attempt)
        raise ProviderError(f"{what}: {problem}")

    def prices(self, tickers: list[str], start: str) -> dict[str, pd.DataFrame]:
        data = self._call(f"prices for {len(tickers)} tickers", lambda: yf.download(
            tickers, start=start, auto_adjust=False, actions=True, group_by="ticker",
            progress=False, threads=True,
        ))
        result = {}
        if data is None or data.empty:
            return result
        for ticker in tickers:
            if ticker not in data.columns.get_level_values(0):
                continue
            frame = tidy_prices(data[ticker])
            if not frame.empty:
                result[ticker] = frame
        return result

    def profile(self, ticker: str) -> Profile:
        info = self._call(f"profile {ticker}", lambda: yf.Ticker(ticker).info)
        if not info or not info.get("quoteType"):
            raise ProviderError(f"profile {ticker}: Yahoo returned no quote data")
        return Profile(
            ticker=ticker, name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"), industry=info.get("industry"),
            market_cap=_num(info.get("marketCap")),
            shares_outstanding=_num(info.get("sharesOutstanding")),
            currency=info.get("currency"), exchange=info.get("exchange"),
            quote_type=info.get("quoteType"),
        )

    def statements(self, ticker: str) -> list[StatementItem]:
        handle = yf.Ticker(ticker)
        items: list[StatementItem] = []
        for statement, freq, attr in STATEMENTS:
            frame = self._call(f"{attr} {ticker}", lambda a=attr: getattr(handle, a))
            if frame is None or frame.empty:
                continue
            for period, column in frame.items():
                period_end = pd.Timestamp(period).strftime("%Y-%m-%d")
                for item, value in column.items():
                    number = _num(value)
                    if number is not None:
                        items.append(StatementItem(statement, freq, period_end, str(item), number))
        if not items:
            raise ProviderError(f"statements {ticker}: Yahoo returned none")
        return items
