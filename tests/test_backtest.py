"""The backtest: what it selects, when it trades, what it charges, and its statistics."""

import math

import numpy as np
import pandas as pd
import pytest

from screener.analysis.backtest import (BacktestConfig, Backtester, Factors, factor_regressions,
                                        monthly_returns, ols, performance, rebalance_positions, simulate)

from test_engine import FILED, _universe

NO_FACTORS = Factors(pd.Series(dtype=float), pd.DataFrame(), None)


def test_rebalance_dates_are_last_trading_days_of_completed_periods():
    dates = pd.bdate_range("2024-01-01", "2024-07-10").strftime("%Y-%m-%d").values
    monthly = [dates[p] for p in rebalance_positions(dates, "monthly")]
    assert monthly == ["2024-01-31", "2024-02-29", "2024-03-29", "2024-04-30", "2024-05-31", "2024-06-28"]
    assert [dates[p] for p in rebalance_positions(dates, "quarterly")] == ["2024-03-29", "2024-06-28"]
    with pytest.raises(ValueError):
        rebalance_positions(dates, "weekly")


def test_trades_happen_the_day_after_the_signal_and_holdings_drift():
    #            day0  day1  day2  day3  day4
    a = np.array([10.0, 10.0, 20.0, 20.0, 40.0])
    b = np.array([10.0, 50.0, 50.0, 50.0, 50.0])     # B's jump on day 1 must not be earned
    adj = np.column_stack([a, b])
    values, start, traded, bought = simulate(adj, ["A", "B"], [(0, ["A", "B"])], cost_bps=0, end=4)
    assert start == 1 and traded == [1.0] and bought == [1.0]      # bought at the day-1 close
    # day 2: A doubles -> 0.5*2 + 0.5*1 = 1.5 ; day 4: A doubles again -> 0.5*4 + 0.5 = 2.5 (no rebalancing back)
    assert values.tolist() == [1.0, 1.5, 1.5, 2.5]


def test_costs_are_charged_on_every_dollar_traded_and_turnover_is_measured():
    flat = np.ones((6, 2))
    # Switch entirely from A to B at the second rebalance.
    values, _, traded, bought = simulate(flat, ["A", "B"], [(0, ["A"]), (2, ["B"])], cost_bps=100, end=5)
    assert traded == [1.0, 2.0]                       # buy 100%; then sell 100% and buy 100%
    assert bought == [1.0, 1.0]                       # one-way turnover: the whole portfolio, twice
    assert values[0] == pytest.approx(0.99)           # 1% of the initial purchase
    assert values[-1] == pytest.approx(0.99 * (1 - 2 * 0.01))
    free, _, _, _ = simulate(flat, ["A", "B"], [(0, ["A"]), (2, ["B"])], cost_bps=0, end=5)
    assert free.tolist() == [1.0] * 5
    unchanged, _, traded, _ = simulate(flat, ["A", "B"], [(0, ["A", "B"]), (2, ["A", "B"])], cost_bps=100, end=5)
    assert traded[1] == pytest.approx(0.0)            # same holdings, no drift: nothing to trade
    cash, _, _, _ = simulate(flat * [[1], [1], [2], [3], [4], [5]], ["A", "B"], [(0, [])], cost_bps=0, end=5)
    assert cash.tolist() == [1.0] * 5                 # nothing passed the screen: cash, not a guess


def test_performance_statistics_on_a_known_path():
    dates = pd.bdate_range("2023-01-02", "2024-01-02").strftime("%Y-%m-%d")
    values = pd.Series(np.linspace(1.0, 2.0, len(dates)), index=dates)
    values.iloc[100] = values.iloc[99] * 0.8          # one 20% drop from the running peak
    stats = performance(values, pd.Series(dtype=float))
    assert stats["total_return"] == pytest.approx(1.0)
    assert stats["cagr"] == pytest.approx(2 ** (365.25 / 365) - 1)     # doubled in 365 days
    assert stats["max_drawdown"] == pytest.approx(-0.2)
    assert math.isnan(stats["sharpe"])                # no risk-free data: missing, not assumed zero
    rf = pd.Series(0.0, index=dates)
    returns = values.pct_change().dropna()
    assert performance(values, rf)["sharpe"] == pytest.approx(returns.mean() / returns.std() * math.sqrt(252))


def test_regression_recovers_known_loadings():
    rng = np.random.default_rng(3)
    x = rng.normal(0, 4, (120, 3))
    y = 0.25 + x @ np.array([1.1, -0.4, 0.3])
    coef, t, r2 = ols(y, x)
    assert coef == pytest.approx([0.25, 1.1, -0.4, 0.3]) and r2 == pytest.approx(1.0)
    months = pd.period_range("2015-01", periods=120, freq="M").strftime("%Y-%m")
    table = pd.DataFrame(x, index=months, columns=pd.MultiIndex.from_tuples([("ff3", "Mkt-RF"), ("ff3", "SMB"), ("ff3", "HML")]))
    table[("ff3", "RF")] = 0.1
    noise = rng.normal(0, 0.5, 120)
    portfolio = pd.Series(y + noise + 0.1, index=months)        # returns include the risk-free rate
    result = factor_regressions(portfolio, Factors(pd.Series(dtype=float), table, "2024-12-31"))
    assert [m["model"] for m in result] == ["Fama-French 3 factors"]     # other models lack their factors
    terms = {t["name"]: t for t in result[0]["terms"]}
    assert terms["Alpha, % per month"]["coef"] == pytest.approx(0.25, abs=0.15)
    assert terms["Mkt-RF"]["coef"] == pytest.approx(1.1, abs=0.05) and terms["Mkt-RF"]["t"] > 20
    assert result[0]["months"] == 120 and result[0]["alpha_annual_pct"] == pytest.approx(terms["Alpha, % per month"]["coef"] * 12)
    assert factor_regressions(portfolio.iloc[:12], Factors(pd.Series(dtype=float), table, None)) == []


def test_monthly_returns_drop_the_incomplete_last_month():
    dates = pd.bdate_range("2024-01-31", "2024-04-10").strftime("%Y-%m-%d")
    values = pd.Series(1.0, index=dates)
    values[dates >= "2024-03-01"] = 1.1
    assert monthly_returns(values).round(6).to_dict() == {"2024-02": 0.0, "2024-03": 10.0}


@pytest.fixture
def backtester():
    members, history, px = _universe()
    return Backtester(members, history, px, NO_FACTORS)


def test_backtest_selects_the_top_ranked_and_never_before_the_reports_were_filed(backtester):
    cfg = BacktestConfig(weights={"gross_profitability": 1}, top_n=3, rebalance="monthly", cost_bps=0)
    result = backtester.run(cfg)
    # Fundamentals were filed on FILED; no earlier month-end may be used.
    assert result["coverage"]["first_rebalance"] > FILED
    assert all(h["date"] > FILED for h in result["holdings"])
    # gross_profitability rises with the ticker number in the synthetic universe.
    assert result["holdings"][0]["tickers"] == ["T11", "T10", "T9"]
    assert result["holdings"][0]["turnover"] == pytest.approx(1.0)
    assert result["holdings"][1]["turnover"] < 0.2                      # same names: only drift to trade
    assert len(result["curve"]["dates"]) == len(result["curve"]["portfolio"]) == len(result["curve"]["universe"])
    assert result["curve"]["portfolio"][0] == 1.0 and result["coverage"]["first_day"] > result["coverage"]["first_rebalance"]
    assert math.isnan(result["stats"]["portfolio"]["sharpe"]) and result["regression"] == []
    assert any("biased upward" in n for n in result["notes"])


def test_backtest_filters_costs_and_errors(backtester):
    base = dict(weights={"gross_profitability": 1}, top_n=2, rebalance="monthly")
    free = backtester.run(BacktestConfig(**base, cost_bps=0))
    costly = backtester.run(BacktestConfig(**base, cost_bps=200))
    assert costly["stats"]["portfolio"]["total_return"] < free["stats"]["portfolio"]["total_return"]
    energy = backtester.run(BacktestConfig(**base, sectors=["Energy"]))
    assert set(energy["holdings"][0]["tickers"]) == {"T6", "T5"}          # best two of T2..T6
    capped = backtester.run(BacktestConfig(**base, filters=[{"key": "gross_profitability", "basis": "value", "hi": 0.25}]))
    assert capped["holdings"][0]["tickers"] == ["T7", "T6"]               # 0.1 + 0.02 i <= 0.25
    no_fin = backtester.run(BacktestConfig(weights={"accruals_cf": 1}, top_n=2, exclude_financials=True))
    assert no_fin["holdings"][0]["tickers"] == ["T2", "T3"]               # lowest accruals outside T0, T1
    with pytest.raises(ValueError, match="twice"):
        backtester.run(BacktestConfig(**{**base, "top_n": 10}))            # 12 stocks cannot fill 2 x 10
    with pytest.raises(ValueError, match="positive weight"):
        backtester.run(BacktestConfig(weights={"quality": 0}))
    with pytest.raises(ValueError, match="unknown filter"):
        backtester.run(BacktestConfig(**base, filters=[{"key": "nonsense", "lo": 1}]))


def test_composite_does_not_start_on_price_data_alone(backtester):
    """Momentum exists from the first year of prices; gross profitability only once
    reports are filed. A screen weighting both must wait for both."""
    both = backtester.run(BacktestConfig(weights={"gross_profitability": 1, "mom_12_1": 1}, top_n=3))
    momentum_only = backtester.run(BacktestConfig(weights={"mom_12_1": 1}, top_n=3))
    assert momentum_only["coverage"]["first_rebalance"] < FILED < both["coverage"]["first_rebalance"]


def test_only_members_on_the_date_are_eligible():
    """With a membership record, a stock joins the eligible universe on its addition
    date, and the equal-weighted universe line follows the same rule."""
    from screener.analysis.backtest import Backtester as BT

    members, history, px = _universe()
    cut = px.adj.index[-45]
    membership = pd.DataFrame({"ticker": members["ticker"], "start": ["" if t != "T11" else cut for t in members["ticker"]],
                               "end": [""] * len(members)})
    bt = BT(members, history, px, NO_FACTORS, membership=membership)
    cfg = BacktestConfig(weights={"gross_profitability": 1}, top_n=3, rebalance="monthly", cost_bps=0)
    result = bt.run(cfg)
    before = [h for h in result["holdings"] if h["date"] < cut]
    after = [h for h in result["holdings"] if h["date"] >= cut]
    assert before and all("T11" not in h["tickers"] for h in before)   # the best stock, but not a member yet
    assert after and all("T11" in h["tickers"] for h in after)
    assert result["coverage"]["membership"] is True and "members at that date" in result["notes"][1]
    plain = BT(members, history, px, NO_FACTORS).run(cfg)
    assert plain["coverage"]["membership"] is False and all("T11" in h["tickers"] for h in plain["holdings"])
