"""Price-based measures for the whole universe at one date.

Returns use the dividend-adjusted close; levels (52-week high, moving averages)
use the split-adjusted close. A ticker with no price on the date gets no measures.
"""

from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

MARKET_PROXY = "SPY"
DAYS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252, "3y": 756, "5y": 1260}
BETA_SHRINK = 0.6          # Frazzini and Pedersen (2014): 0.6 * estimate + 0.4 * 1
MIN_VOL_DAYS, MIN_CORR_DAYS = 120, 750


@dataclass
class PriceData:
    adj: pd.DataFrame       # dates x tickers, dividend-adjusted close
    close: pd.DataFrame     # dates x tickers, split-adjusted close
    splits: pd.DataFrame    # long: ticker, date, split ratio

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "PriceData":
        df = pd.read_sql_query("SELECT ticker, date, close, adj_close, split FROM prices_daily", conn)
        adj = df.pivot(index="date", columns="ticker", values="adj_close").sort_index()
        close = df.pivot(index="date", columns="ticker", values="close").sort_index()
        splits = df[df["split"].fillna(0) != 0][["ticker", "date", "split"]]
        return cls(adj, close, splits)

    def position(self, date: str) -> int:
        """Index of the last trading day on or before `date` (-1 if none)."""
        return int(np.searchsorted(self.adj.index.values, date, side="right")) - 1

    def split_factor_after(self, ticker: str, date: str) -> float:
        """Product of split ratios dated after `date`: converts a share count stated
        on `date` into today's share units, which is what the adjusted close is quoted in."""
        if not hasattr(self, "_split_index"):
            self._split_index = {t: list(zip(g["date"], g["split"])) for t, g in self.splits.groupby("ticker")}
        factor = 1.0
        for when, ratio in self._split_index.get(ticker, ()):
            if when > date:
                factor *= ratio
        return factor


def frazzini_pedersen_beta(log_returns: np.ndarray, market: np.ndarray) -> np.ndarray:
    """Beta as in Frazzini and Pedersen (2014): correlation x (stock volatility /
    market volatility), shrunk towards one.

    Volatilities: standard deviation of daily log returns over the last year
    (at least 120 days). Correlation: overlapping three-day log returns over the
    last five years (at least 750 days). `log_returns` is days x stocks, newest
    last, up to five years; `market` is the matching market series.
    The paper uses the CRSP value-weighted index in excess of T-bills; here the
    market is an S&P 500 tracker's total return and returns are not in excess
    of cash (a negligible difference at daily frequency)."""
    def vol(x: np.ndarray) -> np.ndarray:
        year = x[-DAYS["1y"]:]
        count = np.sum(~np.isnan(year), axis=0)
        with np.errstate(invalid="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            sd = np.nanstd(year, axis=0, ddof=1)
        return np.where(count >= MIN_VOL_DAYS, sd, np.nan)

    r3 = log_returns[2:] + log_returns[1:-1] + log_returns[:-2]
    m3 = (market[2:] + market[1:-1] + market[:-2])[:, None]
    ok = ~np.isnan(r3) & ~np.isnan(m3)
    n = ok.sum(axis=0)
    x = np.where(ok, r3, 0.0)
    y = np.where(ok, m3, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mx, my = x.sum(0) / n, y.sum(0) / n
        cov = (x * y).sum(0) / n - mx * my
        corr = cov / np.sqrt(((x * x).sum(0) / n - mx ** 2) * ((y * y).sum(0) / n - my ** 2))
        corr = np.where(n >= MIN_CORR_DAYS, corr, np.nan)
        beta_ts = corr * vol(log_returns) / vol(market[:, None])
    return BETA_SHRINK * beta_ts + (1 - BETA_SHRINK) * 1.0


def price_measures(px: PriceData, date: str) -> pd.DataFrame:
    """One row per ticker with a price on the last trading day on or before `date`."""
    i = px.position(date)
    if i < 0:
        return pd.DataFrame()
    lo = max(0, i - DAYS["5y"])
    adj = px.adj.values[lo:i + 1]
    close = px.close.values[lo:i + 1]
    n = len(adj)
    last = adj[-1]
    out: dict[str, np.ndarray] = {"price": close[-1]}

    def back(k: int) -> np.ndarray:
        return adj[-1 - k] if n > k else np.full(adj.shape[1], np.nan)

    for name, k in DAYS.items():
        out[f"ret_{name}"] = last / back(k) - 1
    # Momentum: return from 12 months ago to 1 month ago, skipping the latest month.
    out["mom_12_1"] = back(DAYS["1m"]) / back(DAYS["1y"]) - 1

    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        logr = np.diff(np.log(adj), axis=0)
        year = logr[-DAYS["1y"]:]
        count = np.sum(~np.isnan(year), axis=0)
        out["vol_1y"] = np.where(count >= MIN_VOL_DAYS, np.nanstd(year, axis=0, ddof=1) * np.sqrt(252), np.nan)
        if MARKET_PROXY in px.adj.columns:
            market = logr[:, px.adj.columns.get_loc(MARKET_PROXY)]
            out["beta"] = frazzini_pedersen_beta(logr, market)
        else:
            out["beta"] = np.full(adj.shape[1], np.nan)
        window = pd.DataFrame(adj[-(DAYS["1y"] + 1):])
        out["max_drawdown_1y"] = (window / window.cummax() - 1).min().values
        year_close = close[-DAYS["1y"]:]
        out["dist_52w_high"] = close[-1] / np.nanmax(year_close, axis=0) - 1
        enough = lambda k: np.sum(~np.isnan(close[-k:]), axis=0) >= k * 0.9 if n >= k else False
        ma50 = np.where(enough(50), np.nanmean(close[-50:], axis=0), np.nan)
        ma200 = np.where(enough(200), np.nanmean(close[-200:], axis=0), np.nan)
    out["ma50_gap"] = close[-1] / ma50 - 1
    out["ma200_gap"] = close[-1] / ma200 - 1
    out["trend_up"] = np.where(np.isnan(ma50) | np.isnan(ma200), np.nan, (ma50 > ma200).astype(float))
    frame = pd.DataFrame(out, index=px.adj.columns)
    frame.insert(0, "price_date", px.adj.index[i])
    frame = frame[frame["price"].notna()]
    return frame
