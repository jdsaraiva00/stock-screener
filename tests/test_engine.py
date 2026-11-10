"""The engine end to end: Apple's filed facts through to scores, point-in-time
behaviour, ranking, the composite, and the rule-based insights."""

import math

import numpy as np
import pandas as pd
import pytest

from screener.analysis import engine
from screener.analysis.insights import insights_for
from screener.analysis.prices import DAYS, PriceData, frazzini_pedersen_beta, price_measures
from screener.analysis.statements import annual_view, derive, load_facts

from conftest import APPLE_CIK

M = 1_000_000


@pytest.fixture
def apple_facts(apple):
    return load_facts(apple, APPLE_CIK)


def test_apple_history_matches_the_hand_worked_scores(apple_facts):
    history, sources = engine.company_history(apple_facts)
    fy26 = history.set_index("period_end").loc["2026-09-26"]
    assert fy26["available"] == "2026-11-03"
    assert fy26["f_score"] == 9
    assert fy26["beneish_m"] == pytest.approx(-2.5158, abs=5e-4)          # see test_formulas
    assert fy26["accruals_sloan"] == pytest.approx(-0.02615, abs=5e-5)
    assert fy26["accruals_cf"] == pytest.approx(-0.03384, abs=5e-5)
    assert fy26["gross_profitability"] == pytest.approx(233_602 / 404_548)
    assert fy26["asset_growth"] == pytest.approx(404_548 / 359_241 - 1)
    assert fy26["total_debt"] == 80_111 * M                               # 9,906 + 1,997 + 68,208
    assert sources["period_end"] == "2026-09-26"
    assert sources["tags"]["revenue"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert "cash_and_short_term" in sources["derived"]


def test_each_year_uses_only_what_its_own_annual_report_showed(apple, apple_facts):
    before = engine.company_history(apple_facts)[0].set_index("period_end").loc["2025-09-27"]
    assert before["available"] == "2025-10-31" and before["net_income"] == 112_010 * M
    # A later filing restates fiscal 2025 net income. The fiscal 2025 row must not move.
    apple.execute(
        "INSERT INTO fundamentals_facts(cik,taxonomy,tag,unit,period_start,period_end,value,form,filed,accession) "
        "VALUES(?, 'us-gaap', 'NetIncomeLoss', 'USD', '2024-09-29', '2025-09-27', 1, '10-K', '2026-11-03', 'restated')",
        (APPLE_CIK,))
    facts = load_facts(apple, APPLE_CIK)
    after = engine.company_history(facts)[0].set_index("period_end")
    assert after.loc["2025-09-27", "net_income"] == 112_010 * M
    assert after.loc["2025-09-27", "f_score"] == before["f_score"] or (
        math.isnan(after.loc["2025-09-27", "f_score"]) and math.isnan(before["f_score"]))
    latest_view = derive(annual_view(facts)[0])[0]
    assert latest_view.loc["2025-09-27", "net_income"] == 1          # the current view does show it


def test_derived_lines_are_flagged_and_never_invented():
    raw = pd.DataFrame({"revenue": [100.0, 100.0], "cost_of_revenue": [60.0, np.nan],
                        "total_assets": [500.0, 500.0], "equity": [200.0, 200.0],
                        "profit_incl_minority": [30.0, np.nan], "minority_income": [5.0, np.nan],
                        "long_term_debt_total": [80.0, np.nan], "long_term_debt_current": [10.0, np.nan]},
                       index=["2024-12-31", "2025-12-31"])
    v, derived = derive(raw)
    assert v.loc["2024-12-31", "gross_profit"] == 40 and derived.loc["2024-12-31", "gross_profit"]
    assert math.isnan(v.loc["2025-12-31", "gross_profit"]) and not derived.loc["2025-12-31", "gross_profit"]
    assert v.loc["2024-12-31", "net_income"] == 25                       # 30 less the minority share of 5
    assert v.loc["2024-12-31", "total_liabilities"] == 300               # assets 500 - equity 200
    assert (v.loc["2024-12-31", "debt_noncurrent"], v.loc["2024-12-31", "debt_current"]) == (70, 10)
    assert math.isnan(v.loc["2025-12-31", "total_debt"])                 # no debt line tagged: unknown, not zero


def test_percentiles_point_the_favourable_way():
    x = pd.Series([1.0, 2.0, 3.0, np.nan, 5.0], index=list("abcde"))
    assert engine.percentile(x, +1).tolist()[:3] == [0.0, pytest.approx(100 / 3), pytest.approx(200 / 3)]
    assert engine.percentile(x, +1)["e"] == 100 and math.isnan(engine.percentile(x, +1)["d"])
    assert engine.percentile(x, -1)["a"] == 100 and engine.percentile(x, -1)["e"] == 0
    z = engine.rank_z(x)
    assert z.mean() == pytest.approx(0) and z.std() == pytest.approx(1) and math.isnan(z["d"])


def test_composite_needs_half_the_weight():
    frame = pd.DataFrame({"a__pct": [80.0, 80.0, np.nan], "b__pct": [40.0, np.nan, np.nan],
                          "c__pct": [10.0, np.nan, 50.0]}, index=["full", "one_of_three", "light"])
    score = engine.composite(frame, {"a": 2, "b": 1, "c": 1})
    assert score["full"] == pytest.approx((2 * 80 + 40 + 10) / 4)
    assert score["one_of_three"] == 80            # weight 2 of 4 present: exactly half, allowed
    assert math.isnan(score["light"])             # weight 1 of 4 present
    assert engine.composite(frame, {"a": 0}).isna().all()


def test_financial_classification():
    assert engine.is_financial("Financials", "7389")            # card networks sit in GICS Financials
    assert engine.is_financial("Industrials", "6021")           # a bank by SEC code
    assert not engine.is_financial("Real Estate", "6798")       # REITs are not excluded
    assert not engine.is_financial("Information Technology", "3571")
    assert not engine.is_financial(None, None)


def _prices(columns: dict[str, np.ndarray]) -> PriceData:
    n = len(next(iter(columns.values())))
    dates = pd.bdate_range("2019-01-01", periods=n).strftime("%Y-%m-%d")
    frame = pd.DataFrame(columns, index=dates)
    frame.columns.name = "ticker"
    return PriceData(frame, frame.copy(), pd.DataFrame(columns=["ticker", "date", "split"]))


def test_momentum_skips_the_latest_month_and_returns_use_trading_days():
    n = 1300
    price = np.full(n, 100.0)
    price[-(DAYS["1y"] + 1)] = 50.0        # 252 trading days ago
    price[-(DAYS["1m"] + 1)] = 80.0        # 21 trading days ago
    price[-1] = 120.0
    px = _prices({"X": price, "SPY": np.linspace(100, 200, n)})
    m = price_measures(px, px.adj.index[-1]).loc["X"]
    assert m["mom_12_1"] == pytest.approx(80 / 50 - 1)          # month -12 to month -1
    assert m["ret_1m"] == pytest.approx(120 / 80 - 1)
    assert m["ret_1y"] == pytest.approx(120 / 50 - 1)
    assert m["dist_52w_high"] == pytest.approx(0.0)
    assert price_measures(px, "2000-01-01").empty


def test_frazzini_pedersen_beta_and_its_data_requirements():
    rng = np.random.default_rng(7)
    market = rng.normal(0, 0.01, 1260)
    stocks = np.column_stack([market, 2 * market, np.where(np.arange(1260) < 900, np.nan, market)])
    beta = frazzini_pedersen_beta(stocks, market)
    assert beta[0] == pytest.approx(1.0)                         # the market itself
    assert beta[1] == pytest.approx(0.6 * 2 + 0.4)               # raw beta 2, shrunk towards 1
    assert math.isnan(beta[2])                                   # under 750 days of history


YEAR_END, FILED = "2023-06-30", "2023-08-15"      # inside the synthetic price history


def _universe():
    n = 12
    tickers = [f"T{i}" for i in range(n)]
    members = pd.DataFrame({"ticker": tickers, "cik": range(1, n + 1), "name": tickers,
                            "sector": ["Financials"] * 2 + ["Energy"] * 5 + ["Health Care"] * 5,
                            "sub_industry": None, "sic": ["6021", "6311"] + ["1311"] * 10})
    rows = []
    for i in range(n):
        rows.append({"cik": i + 1, "period_end": YEAR_END, "available": FILED,
                     "revenue": 1000.0, "ebit": 100.0 + 10 * i, "net_income": 50.0 + 5 * i, "equity": 400.0,
                     "total_assets": 1000.0, "total_liabilities": 600.0, "working_capital": 100.0,
                     "retained_earnings": 200.0, "total_debt": 200.0, "cash_and_short_term": 50.0,
                     "free_cash_flow": 40.0, "shares": 10.0, "f_score": float(i % 10), "beneish_m": -2.0,
                     "accruals_cf": 0.01 * i, "gross_profitability": 0.1 + 0.02 * i, "asset_growth": 0.05,
                     "q_gpoa": 0.1 + 0.02 * i, "q_roe": 0.1, "q_roa": 0.05 + 0.005 * i, "q_lev": 0.2})
    history = pd.DataFrame(rows)
    rng = np.random.default_rng(1)
    days = 1300
    market = np.exp(np.cumsum(rng.normal(0.0003, 0.01, days))) * 100
    cols = {t: np.exp(np.cumsum(rng.normal(0.0003 + 0.0001 * i, 0.012, days))) * 50 for i, t in enumerate(tickers)}
    cols["SPY"] = market
    return members, history, _prices(cols)


def test_cross_section_rules():
    members, history, px = _universe()
    date = px.adj.index[-1]
    caps = pd.Series({"T5": 9_999.0})
    snap = engine.cross_section(members, history, px, date, market_caps=caps)
    assert len(snap) == 12 and snap["as_of"].eq(date).all()
    # Financials: Altman Z and Beneish M are not applicable, everything else still is.
    assert snap.loc[["T0", "T1"], ["altman_z", "beneish_m", "z_x4"]].isna().all().all()
    assert snap.loc["T0", "f_score"] == 0 and not math.isnan(snap.loc["T0", "book_to_market"])
    assert not math.isnan(snap.loc["T2", "altman_z"]) and snap.loc["T2", "beneish_m"] == -2.0
    # Market cap: the provider's figure where given, otherwise price x filed shares.
    assert snap.loc["T5", "market_cap"] == 9_999 and snap.loc["T5", "market_cap_source"] == "provider"
    assert snap.loc["T6", "market_cap"] == pytest.approx(snap.loc["T6", "price"] * 10)
    assert snap.loc["T6", "book_to_market"] == pytest.approx(400 / (snap.loc["T6", "price"] * 10))
    # Ranks: favourable direction, universe and sector.
    assert snap.loc["T11", "gross_profitability__pct"] == 100 and snap.loc["T0", "gross_profitability__pct"] == 0
    assert snap.loc["T11", "accruals_cf__pct"] == 0                       # highest accruals = least favourable
    assert snap.loc["T6", "gross_profitability__spct"] == 100             # best of the five Energy names
    assert math.isnan(snap.loc["T0", "gross_profitability__spct"])        # only two Financials: no sector rank
    assert snap["quality"].notna().all() and snap["composite"].between(0, 100).all()


def test_cross_section_uses_only_reports_filed_by_the_date_and_drops_stale_years():
    members, history, px = _universe()
    early = engine.cross_section(members, history, px, "2023-08-01")       # before the reports were filed
    assert early["net_income"].isna().all() and early["f_score"].isna().all()
    assert early["mom_12_1"].notna().any()                                 # prices do not depend on filings
    history = history.assign(period_end="2020-12-31", available="2021-02-15")
    stale = engine.cross_section(members, history, px, px.adj.index[-1])
    assert stale["net_income"].isna().all()


def test_insights_follow_the_rules_and_cite_their_measures():
    row = {"f_score": 8.0, "financial": False, "beneish_m": -1.2, "altman_z": 1.5,
           "value_score__pct": 91.0, "mom_12_1__pct": 4.0, "mom_12_1": -0.31, "quality__pct": 12.0,
           "accruals_cf": 0.12, "accruals_cf__pct": 3.0, "dist_52w_high": -0.45, "max_drawdown_1y": -0.5,
           "ma200_gap": -0.2, "trend_up": 0.0}
    items = insights_for(row, {"f_score": 4.0})
    texts = " | ".join(i["text"] for i in items)
    assert "F-Score rose from 4 to 8 over the past fiscal year." in texts
    assert "M-Score of -1.20 is above -1.78" in texts
    assert "Altman Z of 1.50 is below 1.81" in texts
    assert "Cheap on value (91st percentile) but in the bottom momentum decile" in texts
    assert "possible value trap" in texts and "-45.0% below its 52-week high" in texts
    assert all(i["measures"] and i["tone"] in ("good", "bad", "neutral") for i in items)
    quiet = insights_for({"f_score": 6.0, "financial": False, "beneish_m": -2.6, "altman_z": 4.0}, {"f_score": 6.0})
    assert quiet == []
    bank = insights_for({"financial": True, "beneish_m": -1.0, "altman_z": 0.5})
    assert len(bank) == 1 and "not meaningful for financial companies" in bank[0]["text"]
    assert insights_for({}) == []                                          # nothing known, nothing said
