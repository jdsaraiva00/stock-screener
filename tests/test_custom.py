"""Custom measures: the formula language accepts only what it should, missing
stays missing, ranks follow the direction, and the API and backtest use them."""

import math

import numpy as np
import pandas as pd
import pytest

from screener.analysis import custom
from screener.analysis.backtest import BacktestConfig, Backtester
from screener.analysis.custom import CustomMeasure

from test_backtest import NO_FACTORS
from test_engine import _universe
from test_server import client  # noqa: F401  (fixture)


def test_formula_language_is_small_and_names_are_checked():
    assert custom.names_used("total_debt / market_cap") == ["total_debt", "market_cap"]
    assert custom.names_used("(cash_and_short_term - total_debt) / pretax_income * 1.5") == [
        "cash_and_short_term", "total_debt", "pretax_income"]
    assert custom.names_used("-beta") == ["beta"]                      # built-in measures may be used
    for bad, message in [
        ("", "Enter a formula"),
        ("2 + 2", "at least one line"),
        ("total_debt / nothing", "Unknown name 'nothing'"),
        ("__import__('os')", "are allowed"),
        ("total_debt.real", "are allowed"),
        ("total_debt ** 2", "are allowed"),
        ("total_debt if 1 else 0", "are allowed"),
        ("total_debt /", "Could not read"),
        ("trend_up * 2", "Unknown name"),                              # flags are not usable
    ]:
        with pytest.raises(ValueError, match=message):
            custom.names_used(bad)


def test_evaluation_keeps_missing_missing_and_never_divides_by_zero():
    frame = pd.DataFrame({"total_debt": [100.0, 50.0, np.nan, 10.0], "market_cap": [200.0, 0.0, 300.0, np.nan],
                          "sector": ["A", "A", "B", "B"]}, index=list("wxyz"))
    out = custom.evaluate("total_debt / market_cap", frame)
    assert out["w"] == 0.5
    assert math.isnan(out["x"]) and math.isnan(out["y"]) and math.isnan(out["z"])
    assert custom.evaluate("total_debt / 0", frame).isna().all()
    assert custom.evaluate("revenue + 1", frame).isna().all()           # a line absent from the frame
    assert custom.evaluate("total_debt * 0 + 3", frame).tolist()[:2] == [3.0, 3.0]


def test_apply_adds_values_and_ranks_in_the_favourable_direction():
    frame = pd.DataFrame({"total_debt": [100.0, 50.0, 10.0, np.nan], "market_cap": [100.0] * 4,
                          "sector": ["A"] * 4}, index=list("wxyz"))
    low_is_good = CustomMeasure("c_debt_to_cap", "Debt to cap", "total_debt / market_cap", better=-1)
    out = custom.apply(frame, [low_is_good])
    assert out.loc["w", "c_debt_to_cap"] == 1.0
    assert out.loc["y", "c_debt_to_cap__pct"] == 100 and out.loc["w", "c_debt_to_cap__pct"] == 0
    assert math.isnan(out.loc["z", "c_debt_to_cap__pct"])
    assert out["c_debt_to_cap__spct"].isna().all()                      # only three valued: sector too small
    plain = custom.apply(frame, [CustomMeasure("c_x", "X", "total_debt", better=0)])
    assert "c_x" in plain and "c_x__pct" not in plain                   # no direction: not ranked


def test_validate_and_key_derivation():
    m = custom.validate("Debt / Mkt Cap", "total_debt / market_cap", -1, "ratio")
    assert m.key == "c_debt_mkt_cap" and m.as_measure()["group"] == "Custom"
    with pytest.raises(ValueError, match="name"):
        custom.validate("   ", "total_debt", 1, "ratio")
    with pytest.raises(ValueError, match="Direction"):
        custom.validate("X", "total_debt", 2, "ratio")
    with pytest.raises(ValueError, match="Format"):
        custom.validate("X", "total_debt", 1, "bananas")
    with pytest.raises(ValueError, match="letter or a digit"):
        custom.key_for("???")


def test_backtest_can_rank_and_filter_on_a_custom_measure():
    members, history, px = _universe()
    bt = Backtester(members, history, px, NO_FACTORS)
    # ebit rises with the ticker number and the market cap is price x 10 shares, so
    # "ebit / market_cap" ranks like EBIT/EV did and must be usable as the only weight.
    measure = CustomMeasure("c_ebit_yield", "EBIT yield", "ebit / market_cap", better=1).as_dict()
    cfg = BacktestConfig(weights={"c_ebit_yield": 1}, top_n=3, rebalance="monthly", cost_bps=0, custom=[measure])
    result = bt.run(cfg)
    assert len(result["holdings"][0]["tickers"]) == 3
    filtered = BacktestConfig(weights={"c_ebit_yield": 1}, top_n=2, rebalance="monthly", cost_bps=0,
                              custom=[measure], filters=[{"key": "c_ebit_yield", "basis": "pct", "lo": 50}])
    assert len(bt.run(filtered)["holdings"][0]["tickers"]) == 2
    with pytest.raises(ValueError, match="unknown filter measure"):
        bt.run(BacktestConfig(weights={"c_ebit_yield": 1}, top_n=2, custom=[],
                              filters=[{"key": "c_ebit_yield", "basis": "value", "lo": 0}]))


def test_measures_api_round_trip_and_use_in_screen_and_backtest(client):  # noqa: F811
    assert client.get("/api/measures").json() == []
    bad = client.post("/api/measures", json={"label": "Broken", "formula": "total_debt / nope", "better": -1, "fmt": "ratio"})
    assert bad.status_code == 422 and "Unknown name 'nope'" in bad.json()["detail"]
    created = client.post("/api/measures", json={"label": "Debt / Mkt Cap", "formula": "total_debt / market_cap",
                                                 "better": -1, "fmt": "ratio"})
    assert created.status_code == 200 and created.json()["key"] == "c_debt_mkt_cap"
    duplicate = client.post("/api/measures", json={"label": "debt mkt cap", "formula": "1 + total_debt", "better": 0, "fmt": "ratio"})
    assert duplicate.status_code == 409
    taken = client.post("/api/measures", json={"label": "F-Score", "formula": "total_debt", "better": 0, "fmt": "ratio"})
    assert taken.status_code == 200 and taken.json()["key"] == "c_f_score"   # the prefix keeps it clear of built-ins

    catalog = client.get("/api/meta").json()["catalog"]
    mine = [m for m in catalog["measures"] if m["key"] == "c_debt_mkt_cap"][0]
    assert mine["group"] == "Custom" and mine["better"] == -1 and "total_debt / market_cap" in mine["about"]
    assert {"key": "pretax_income", "label": "Pre-tax income (EBT)"} in catalog["lines"]

    screen = client.get("/api/screen").json()
    cols = screen["columns"]
    assert {"c_debt_mkt_cap", "c_debt_mkt_cap__pct", "c_debt_mkt_cap__spct", "c_f_score"} <= set(cols)
    row = dict(zip(cols, screen["data"][0]))
    assert row["c_debt_mkt_cap"] == pytest.approx(200 / row["market_cap"])
    detail = client.get("/api/stock/T2").json()
    assert detail["row"]["c_debt_mkt_cap"] == pytest.approx(200 / detail["row"]["market_cap"])

    updated = client.put("/api/measures/c_debt_mkt_cap", json={"label": "Debt to cap", "formula": "total_debt / market_cap * 100",
                                                               "better": -1, "fmt": "ratio"})
    assert updated.status_code == 200 and updated.json()["label"] == "Debt to cap"
    assert client.put("/api/measures/c_missing", json={"label": "X", "formula": "total_debt", "better": 0, "fmt": "ratio"}).status_code == 404

    body = {"weights": {"c_debt_mkt_cap": 1}, "top_n": 3, "rebalance": "monthly", "cost_bps": 0,
            "filters": [{"key": "c_debt_mkt_cap", "basis": "pct", "lo": 10, "hi": None}],
            "sectors": [], "exclude_financials": False, "start": None, "end": None}
    result = client.post("/api/backtest", json=body)
    assert result.status_code == 200 and len(result.json()["holdings"][0]["tickers"]) == 3
    assert result.json()["config"]["custom"][0]["key"] == "c_debt_mkt_cap"

    assert client.delete("/api/measures/c_debt_mkt_cap").status_code == 200
    assert client.delete("/api/measures/c_debt_mkt_cap").status_code == 404
    assert "c_debt_mkt_cap" not in client.get("/api/screen").json()["columns"]
    assert client.post("/api/backtest", json=body).status_code == 422          # the measure is gone
