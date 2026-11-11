"""Backtest of a screen: equal-weighted top-N portfolio, rebalanced monthly or quarterly.

What it does on each rebalance date (the last trading day of the period):
  1. builds the same cross-section the screener shows, using only annual reports
     already filed with the SEC by that date and prices up to that date;
  2. applies the screen's filters, ranks by the composite, takes the top N;
  3. trades at the NEXT trading day's close, so the signal never uses the price
     it trades at; holdings then drift until the next rebalance;
  4. charges the cost setting on every dollar bought or sold.

What it cannot do with free data, and says so in its notes: the universe is
today's index members, so companies that failed or were dropped are missing and
results are biased upward. The "all current members, equal-weighted" line shows
how much of a result is that bias and equal weighting rather than the screen.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from screener.analysis import engine
from screener.analysis.catalog import DEFAULT_WEIGHTS, MEASURES
from screener.analysis.prices import PriceData

BENCHMARKS = ["^SP500TR", "SPY"]          # first one with prices is used
MIN_REGRESSION_MONTHS = 24
FACTOR_MODELS = [
    ("Fama-French 3 factors", [("ff3", "Mkt-RF"), ("ff3", "SMB"), ("ff3", "HML")]),
    ("3 factors + momentum", [("ff3", "Mkt-RF"), ("ff3", "SMB"), ("ff3", "HML"), ("mom", "Mom")]),
    ("Fama-French 5 factors", [("ff5", "Mkt-RF"), ("ff5", "SMB"), ("ff5", "HML"), ("ff5", "RMW"), ("ff5", "CMA")]),
    ("5 factors + momentum", [("ff5", "Mkt-RF"), ("ff5", "SMB"), ("ff5", "HML"), ("ff5", "RMW"), ("ff5", "CMA"),
                              ("mom", "Mom")]),
]


@dataclass
class BacktestConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    filters: list[dict] = field(default_factory=list)      # {key, basis: value|pct|spct, lo, hi}
    sectors: list[str] = field(default_factory=list)       # empty = all
    exclude_financials: bool = False
    top_n: int = 30
    rebalance: str = "monthly"                             # monthly | quarterly
    start: str | None = None
    end: str | None = None
    cost_bps: float = 10.0                                 # per dollar traded, each way


@dataclass
class Factors:
    daily_rf: pd.Series                 # date -> percent per day
    monthly: pd.DataFrame               # index YYYY-MM, columns (dataset, factor) in percent, plus ("ff3","RF")
    through: str | None

    @classmethod
    def load(cls, conn: sqlite3.Connection) -> "Factors":
        daily = pd.read_sql_query(
            "SELECT date, value_pct FROM factor_returns WHERE dataset='ff3' AND freq='daily' AND factor='RF'", conn)
        monthly = pd.read_sql_query(
            "SELECT dataset, date, factor, value_pct FROM factor_returns WHERE freq='monthly'", conn)
        table = pd.DataFrame()
        if not monthly.empty:
            monthly["month"] = monthly["date"].str[:7]
            table = monthly.pivot(index="month", columns=["dataset", "factor"], values="value_pct").sort_index()
        rf = daily.set_index("date")["value_pct"].sort_index() if not daily.empty else pd.Series(dtype=float)
        return cls(rf, table, rf.index.max() if len(rf) else None)


def rebalance_positions(dates: np.ndarray, frequency: str) -> list[int]:
    """Index of the last trading day of each completed month or quarter. The final
    period in the data is treated as still in progress and is not used."""
    months = pd.Series([d[:7] for d in dates])
    if frequency == "quarterly":
        keys = months.str[:4] + "Q" + ((months.str[5:7].astype(int) - 1) // 3 + 1).astype(str)
    elif frequency == "monthly":
        keys = months
    else:
        raise ValueError("rebalance must be 'monthly' or 'quarterly'")
    last = keys.groupby(keys).apply(lambda s: s.index[-1]).sort_values().tolist()
    return last[:-1]


def simulate(adj: np.ndarray, columns: list[str], schedule: list[tuple[int, list[str]]],
             cost_bps: float, end: int) -> tuple[np.ndarray, int, list[float], list[float]]:
    """Daily value of an equal-weighted portfolio.

    schedule: (signal position, tickers chosen) per rebalance. Trades happen at
    the close one trading day after the signal. Returns (values from the first
    trade day to `end`, position of that first day, and per rebalance: the traded
    fraction, i.e. the sum of absolute weight changes on which costs are charged,
    and the bought fraction, i.e. one-way turnover, the share of the portfolio replaced).
    An empty selection means the portfolio sits in cash, earning nothing.
    """
    col = {t: i for i, t in enumerate(columns)}
    trades = [(pos + 1, [col[t] for t in tickers]) for pos, tickers in schedule if pos + 1 <= end]
    if not trades:
        return np.array([]), -1, [], []
    start = trades[0][0]
    values = np.ones(end - start + 1)
    value, weights, traded, bought = 1.0, {}, [], []
    for k, (day, picks) in enumerate(trades):
        target = {c: 1.0 / len(picks) for c in picks} if picks else {}
        change = sum(abs(target.get(c, 0.0) - weights.get(c, 0.0)) for c in set(target) | set(weights))
        traded.append(change)
        bought.append(sum(max(target.get(c, 0.0) - weights.get(c, 0.0), 0.0) for c in target))
        value *= 1.0 - change * cost_bps / 1e4
        stop = trades[k + 1][0] if k + 1 < len(trades) else end
        if picks:
            rel = adj[day:stop + 1, picks] / adj[day, picks]
            w = np.array([target[c] for c in picks])
            path = rel @ w
            values[day - start:stop - start + 1] = value * path
            drift = w * rel[-1]
            weights = dict(zip(picks, drift / drift.sum()))
            value *= path[-1]
        else:
            values[day - start:stop - start + 1] = value
            weights = {}
    return values, start, traded, bought


def performance(values: pd.Series, daily_rf: pd.Series) -> dict:
    """values: date -> portfolio value. Sharpe uses only the days for which the
    risk-free rate has been published."""
    if len(values) < 2:
        return {}
    returns = values.pct_change().dropna()
    years = (pd.Timestamp(values.index[-1]) - pd.Timestamp(values.index[0])).days / 365.25
    total = values.iloc[-1] / values.iloc[0] - 1
    excess = (returns - daily_rf.reindex(returns.index) / 100).dropna()
    sharpe = excess.mean() / excess.std() * math.sqrt(252) if len(excess) > 20 and excess.std() > 0 else float("nan")
    return {
        "total_return": total,
        "cagr": (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else float("nan"),
        "volatility": returns.std() * math.sqrt(252),
        "sharpe": sharpe,
        "max_drawdown": (values / values.cummax() - 1).min(),
    }


def monthly_returns(values: pd.Series) -> pd.Series:
    """Calendar-month returns in percent, index YYYY-MM, whole months only."""
    month = pd.Series(values.index.str[:7], index=values.index)
    ends = values.groupby(month).last()
    returns = (ends.pct_change() * 100).dropna()
    last_day = pd.Timestamp(values.index[-1])
    if (last_day + pd.offsets.BMonthEnd(0)).date() != last_day.date() and len(returns):
        returns = returns.iloc[:-1]          # the final month is incomplete
    return returns


def ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Ordinary least squares with an intercept: (coefficients, t-statistics, R squared)."""
    design = np.column_stack([np.ones(len(y)), x])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ coef
    dof = len(y) - design.shape[1]
    sigma2 = resid @ resid / dof if dof > 0 else float("nan")
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(design.T @ design)))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = coef / se
    centred = y - y.mean()
    r2 = 1 - (resid @ resid) / (centred @ centred) if centred @ centred > 0 else float("nan")
    return coef, t, r2


def factor_regressions(portfolio_monthly: pd.Series, factors: Factors) -> list[dict]:
    """Monthly excess returns regressed on the Fama-French factors. The intercept
    (alpha) is the return the factors do not explain; if it is near zero or its
    t-statistic is small, the screen adds nothing beyond known factor exposure."""
    out = []
    table = factors.monthly
    if table.empty or ("ff3", "RF") not in table:
        return out
    for name, columns in FACTOR_MODELS:
        if any(c not in table for c in columns):
            continue
        data = pd.concat([portfolio_monthly.rename("r"), table[[("ff3", "RF"), *columns]]], axis=1, join="inner").dropna()
        if len(data) < MIN_REGRESSION_MONTHS:
            continue
        y = (data["r"] - data[("ff3", "RF")]).values
        coef, t, r2 = ols(y, data[columns].values)
        terms = [{"name": "Alpha, % per month", "coef": coef[0], "t": t[0]}]
        terms += [{"name": factor, "coef": c, "t": tv} for (_, factor), c, tv in zip(columns, coef[1:], t[1:])]
        out.append({"model": name, "months": len(data), "r_squared": r2, "alpha_annual_pct": coef[0] * 12,
                    "first_month": data.index[0], "last_month": data.index[-1], "terms": terms})
    return out


class Backtester:
    """Holds the cache-derived inputs and remembers each date's cross-section, so
    trying different weights or filters does not recompute them."""

    def __init__(self, members: pd.DataFrame, history: pd.DataFrame, px: PriceData, factors: Factors):
        self.members, self.history, self.px, self.factors = members, history, px, factors
        self._sections: dict[str, pd.DataFrame] = {}
        keys = [m.key for m in MEASURES if m.key != "composite"]
        self._keep = ["sector", "financial", "price"] + [c for k in keys for c in (k, f"{k}__pct", f"{k}__spct")]

    def section(self, date: str) -> pd.DataFrame:
        if date not in self._sections:
            frame = engine.cross_section(self.members, self.history, self.px, date)
            self._sections[date] = frame[[c for c in self._keep if c in frame]]
        return self._sections[date]

    def select(self, date: str, cfg: BacktestConfig) -> tuple[list[str], list[float], int, int]:
        """Tickers chosen on `date`, their composite scores, how many were eligible,
        and the smallest number of eligible stocks that have any one weighted measure."""
        frame = self.section(date)
        frame = frame[frame["price"].notna()]
        if cfg.sectors:
            frame = frame[frame["sector"].isin(cfg.sectors)]
        if cfg.exclude_financials:
            frame = frame[~frame["financial"].astype(bool)]
        for f in cfg.filters:
            column = f["key"] if f.get("basis", "value") == "value" else f"{f['key']}__{f['basis']}"
            if column not in frame:
                raise ValueError(f"unknown filter measure: {column}")
            values = frame[column]
            keep = values.notna()          # no value: cannot pass a filter on it
            if f.get("lo") is not None:
                keep &= values >= f["lo"]
            if f.get("hi") is not None:
                keep &= values <= f["hi"]
            frame = frame[keep]
        score = engine.composite(frame, cfg.weights).dropna().sort_values(ascending=False, kind="stable")
        top = score.head(cfg.top_n)
        ranked = frame.loc[score.index]
        thinnest = min((int(ranked[f"{k}__pct"].notna().sum()) for k, w in cfg.weights.items()
                        if w > 0 and f"{k}__pct" in ranked), default=0)
        return top.index.tolist(), top.tolist(), len(score), thinnest

    def run(self, cfg: BacktestConfig) -> dict:
        if cfg.top_n < 1:
            raise ValueError("top_n must be at least 1")
        if not any(w > 0 for w in cfg.weights.values()):
            raise ValueError("give at least one measure a positive weight")
        dates = self.px.adj.index.values
        end = self.px.position(cfg.end) if cfg.end else len(dates) - 1
        positions = [p for p in rebalance_positions(dates[:end + 1], cfg.rebalance)
                     if (not cfg.start or dates[p] >= cfg.start)]
        schedule, holdings, everyone = [], [], []
        started = False
        for p in positions:
            date = dates[p]
            tickers, scores, eligible, thinnest = self.select(date, cfg)
            # Start once EVERY weighted measure exists for twice the portfolio size.
            # The composite tolerates missing measures, so without this rule a
            # value-and-quality screen would silently run on price data alone in
            # the years before filed fundamentals exist.
            if not started and thinnest < 2 * cfg.top_n:
                continue
            started = True
            schedule.append((p, tickers))
            holdings.append({"date": date, "tickers": tickers, "scores": scores, "eligible": eligible})
            frame = self.section(date)
            everyone.append((p, frame.index[frame["price"].notna()].tolist()))
        if not schedule:
            raise ValueError("On no rebalance date does every weighted measure exist for at least twice the "
                             "requested number of eligible stocks. Loosen the filters, lower N, or change the weights.")

        adj = self.px.adj.ffill()
        columns = adj.columns.tolist()
        matrix = adj.values
        values, start, _, bought = simulate(matrix, columns, schedule, cfg.cost_bps, end)
        if start < 0:
            raise ValueError("The first rebalance falls on the last day of data; nothing to simulate.")
        index = pd.Index(dates[start:end + 1])
        portfolio = pd.Series(values, index=index)
        universe_values, _, _, _ = simulate(matrix, columns, everyone, cfg.cost_bps, end)
        universe = pd.Series(universe_values, index=index)
        bench_name = next((b for b in BENCHMARKS if b in adj and not np.isnan(adj[b].iloc[start])), None)
        benchmark = adj[bench_name].iloc[start:end + 1] / adj[bench_name].iloc[start] if bench_name else None

        for h, b in zip(holdings, bought):
            h["turnover"] = b                # one-way: the share of the portfolio replaced
        per_year = 12 if cfg.rebalance == "monthly" else 4
        later = bought[1:]
        rf = self.factors.daily_rf
        stats = {"portfolio": performance(portfolio, rf), "universe": performance(universe, rf)}
        stats["portfolio"]["turnover_annual"] = float(np.mean(later)) * per_year if later else float("nan")
        if benchmark is not None:
            stats["benchmark"] = performance(pd.Series(benchmark.values, index=index), rf)

        first, last = holdings[0]["date"], index[-1]
        notes = [
            f"Simulated from {index[0]} to {last}: {len(schedule)} rebalances, the first chosen on {first}. "
            f"The start is the first date on which every weighted measure exists for at least "
            f"{2 * cfg.top_n} eligible stocks; filed fundamentals begin around 2009-2011.",
            f"Universe: the {len(self.members)} tickers in the index today. Companies that went bankrupt, were "
            f"acquired or were dropped from the index are not in the data, so results are biased upward.",
        ]
        if self.factors.through:
            notes.append(f"Sharpe ratios and factor regressions use risk-free and factor data published through "
                         f"{self.factors.through}; later days are left out of those two calculations only.")
        if any(not h["tickers"] for h in holdings):
            notes.append("On some dates no stock passed the screen; the portfolio held cash (earning nothing) then.")
        short = [h["date"] for h in holdings if 0 < len(h["tickers"]) < cfg.top_n]
        if short:
            notes.append(f"On {len(short)} rebalance dates fewer than {cfg.top_n} stocks passed the screen; "
                         f"the portfolio held those that did.")
        return {
            "config": cfg.__dict__,
            "coverage": {"first_rebalance": first, "first_day": index[0], "last_date": last,
                         "rebalances": len(schedule), "factor_data_through": self.factors.through,
                         "benchmark": bench_name},
            "curve": {"dates": index.tolist(), "portfolio": portfolio.tolist(), "universe": universe.tolist(),
                      "benchmark": benchmark.tolist() if benchmark is not None else None},
            "stats": stats,
            "regression": factor_regressions(monthly_returns(portfolio), self.factors),
            "holdings": holdings,
            "notes": notes,
        }
