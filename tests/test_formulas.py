"""Each formula against values worked out by hand from Apple's statements.

Inputs are Apple's reported figures in USD millions for fiscal 2026, 2025 and
2024 (10-K filed 2026-11-03, accession 0000320193-26-000026, and its
predecessors). Expected values are written out as plain arithmetic on those
figures, independently of the code under test.
"""

import math

import pytest

from screener.analysis import formulas as f

FY26 = dict(revenue=478_834, gross_profit=233_602, sga=29_774, depreciation_amortization=13_423,
            ebit=158_063, net_income=132_175, total_assets=404_548, current_assets=173_857,
            cash_and_short_term=56_722, receivables=43_817, ppe_net=52_084, total_liabilities=292_455,
            current_liabilities=169_915, taxes_payable=5_287, debt_current=11_903,
            debt_noncurrent=68_208, total_debt=80_111, retained_earnings=13_700, equity=112_093,
            shares_outstanding=14_532, cfo=145_097, capex=9_041, working_capital=3_942,
            free_cash_flow=136_056)
FY25 = dict(revenue=416_161, gross_profit=195_201, sga=27_601, depreciation_amortization=11_698,
            ebit=133_050, net_income=112_010, total_assets=359_241, current_assets=147_957,
            cash_and_short_term=54_697, receivables=39_777, ppe_net=49_834, total_liabilities=285_508,
            current_liabilities=165_631, taxes_payable=13_016, debt_current=20_329,
            debt_noncurrent=78_328, total_debt=98_657, retained_earnings=-14_264, equity=73_733,
            shares_outstanding=14_773, cfo=111_482, capex=12_715, working_capital=-17_674)
FY24 = dict(revenue=391_035, gross_profit=180_683, net_income=93_736, total_assets=364_980,
            current_assets=152_987, current_liabilities=176_392, debt_noncurrent=85_750,
            cash_and_short_term=65_171, taxes_payable=26_601, debt_current=20_879,
            depreciation_amortization=11_445, capex=9_447, equity=56_950)
MARKET_CAP = 5_064_611        # USD millions, Yahoo, 2026-11-10


def close(a, b, tol=1e-9):
    return a == pytest.approx(b, rel=tol, abs=tol)


def test_piotroski_f_score_apple_fy2026():
    r = f.piotroski(FY26, FY25, FY24)
    # 1 ROA = NI / beginning assets = 132,175 / 359,241 = 0.3679 > 0
    assert close(r["f_v_roa"], 132_175 / 359_241) and r["f_roa"] == 1
    # 2 CFO = 145,097 / 359,241 = 0.4039 > 0
    assert close(r["f_v_cfo"], 145_097 / 359_241) and r["f_cfo"] == 1
    # 3 prior ROA = 112,010 / 364,980 = 0.3069 ; 0.3679 > 0.3069
    assert close(r["f_v_roa_prev"], 112_010 / 364_980) and r["f_droa"] == 1
    # 4 CFO 0.4039 > ROA 0.3679
    assert r["f_accrual"] == 1
    # 5 leverage = LT debt / average assets: 68,208 / 381,894.5 = 0.1786 vs 78,328 / 362,110.5 = 0.2163 -> fell
    assert close(r["f_v_lever"], 68_208 / ((404_548 + 359_241) / 2))
    assert close(r["f_v_lever_prev"], 78_328 / ((359_241 + 364_980) / 2)) and r["f_dlever"] == 1
    # 6 current ratio 173,857 / 169,915 = 1.0232 vs 147,957 / 165,631 = 0.8933 -> improved
    assert close(r["f_v_liquid"], 173_857 / 169_915) and r["f_dliquid"] == 1
    # 7 shares 14,532m vs 14,773m -> no net issuance
    assert r["f_eq_offer"] == 1
    # 8 gross margin 233,602 / 478,834 = 0.4879 vs 195,201 / 416,161 = 0.4691 -> improved
    assert close(r["f_v_margin"], 233_602 / 478_834) and r["f_dmargin"] == 1
    # 9 turnover 478,834 / 359,241 = 1.3329 vs 416,161 / 364,980 = 1.1402 -> improved
    assert close(r["f_v_turn"], 478_834 / 359_241) and r["f_dturn"] == 1
    assert r["f_score"] == 9 and r["f_signals_known"] == 9


def test_piotroski_signals_can_fail_and_missing_inputs_leave_the_score_missing():
    worse = dict(FY26, net_income=-1, cfo=-5, shares_outstanding=15_000)
    r = f.piotroski(worse, FY25, FY24)
    assert (r["f_roa"], r["f_cfo"], r["f_droa"], r["f_accrual"], r["f_eq_offer"]) == (0, 0, 0, 0, 0)
    assert r["f_score"] == 4
    no_margin = {k: v for k, v in FY26.items() if k != "gross_profit"}
    r = f.piotroski(no_margin, FY25, FY24)
    assert math.isnan(r["f_score"]) and math.isnan(r["f_dmargin"]) and r["f_signals_known"] == 8
    assert math.isnan(f.piotroski(FY26, None, None)["f_score"])


def test_altman_z_apple_fy2026():
    r = f.altman_z(FY26, MARKET_CAP)
    x1 = 3_942 / 404_548                # working capital / total assets = 0.00974
    x2 = 13_700 / 404_548               # retained earnings / total assets = 0.03387
    x3 = 158_063 / 404_548              # EBIT / total assets = 0.39072
    x4 = 5_064_611 / 292_455            # market cap / total liabilities = 17.3176
    x5 = 478_834 / 404_548              # sales / total assets = 1.18363
    assert close(r["z_x1"], x1) and close(r["z_x2"], x2) and close(r["z_x3"], x3)
    assert close(r["z_x4"], x4) and close(r["z_x5"], x5)
    assert close(r["altman_z"], 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5)
    assert r["altman_z"] == pytest.approx(12.9228, abs=5e-4)
    assert math.isnan(f.altman_z(FY26, float("nan"))["altman_z"])


def test_beneish_m_score_apple_fy2026():
    r = f.beneish_m(FY26, FY25)
    dsri = (43_817 / 478_834) / (39_777 / 416_161)                                   # 0.95738
    gmi = (195_201 / 416_161) / (233_602 / 478_834)                                  # 0.96146
    aqi = (1 - (173_857 + 52_084) / 404_548) / (1 - (147_957 + 49_834) / 359_241)    # 0.98235
    sgi = 478_834 / 416_161                                                          # 1.15060
    depi = (11_698 / (11_698 + 49_834)) / (13_423 / (13_423 + 52_084))               # 0.92778
    sgai = (29_774 / 478_834) / (27_601 / 416_161)                                   # 0.93753
    lvgi = ((169_915 + 68_208) / 404_548) / ((165_631 + 78_328) / 359_241)           # 0.86677
    tata = (132_175 - 145_097) / 404_548                                             # -0.03194
    for key, expected in dict(m_dsri=dsri, m_gmi=gmi, m_aqi=aqi, m_sgi=sgi, m_depi=depi,
                              m_sgai=sgai, m_lvgi=lvgi, m_tata=tata).items():
        assert close(r[key], expected), key
    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    # -4.84 + 0.8808 + 0.5076 + 0.3969 + 1.0263 + 0.1067 - 0.1613 - 0.1495 - 0.2834 = -2.5158
    assert close(r["beneish_m"], m)
    assert r["beneish_m"] == pytest.approx(-2.5158, abs=5e-4) and r["beneish_m"] < f.BENEISH_THRESHOLD


def test_beneish_uses_continuing_operations_income_when_reported_and_needs_every_input():
    with_cont = f.beneish_m(dict(FY26, income_continuing=140_000), FY25)
    assert close(with_cont["m_tata"], (140_000 - 145_097) / 404_548)
    no_sga = {k: v for k, v in FY26.items() if k != "sga"}
    r = f.beneish_m(no_sga, FY25)
    assert math.isnan(r["m_sgai"]) and math.isnan(r["beneish_m"]) and not math.isnan(r["m_dsri"])


def test_accruals_apple_fy2026():
    r = f.accruals(FY26, FY25)
    # operating working capital = CA - CL - cash and ST investments + current debt + taxes payable
    wc26 = 173_857 - 169_915 - 56_722 + 11_903 + 5_287          # -35,590
    wc25 = 147_957 - 165_631 - 54_697 + 20_329 + 13_016         # -39,026
    avg_assets = (404_548 + 359_241) / 2                        # 381,894.5
    assert close(r["accruals_sloan"], ((wc26 - wc25) - 13_423) / avg_assets)
    assert r["accruals_sloan"] == pytest.approx(-0.02615, abs=5e-5)
    assert close(r["accruals_cf"], (132_175 - 145_097) / avg_assets)
    assert r["accruals_cf"] == pytest.approx(-0.03384, abs=5e-5)
    no_tax = {k: v for k, v in FY26.items() if k != "taxes_payable"}
    partial = f.accruals(no_tax, FY25)
    assert math.isnan(partial["accruals_sloan"]) and not math.isnan(partial["accruals_cf"])


def test_gross_profitability_and_asset_growth_apple_fy2026():
    assert close(f.gross_profitability(FY26), 233_602 / 404_548)              # 0.5774
    assert close(f.asset_growth(FY26, FY25), 404_548 / 359_241 - 1)           # +12.61%
    assert math.isnan(f.asset_growth(FY26, None))


def test_valuation_apple_fy2026():
    r = f.valuation(FY26, MARKET_CAP)
    ev = 5_064_611 + 80_111 - 56_722                                          # 5,088,000
    assert close(r["enterprise_value"], ev)
    assert close(r["book_to_market"], 112_093 / 5_064_611)                    # 0.02213
    assert close(r["earnings_yield"], 132_175 / 5_064_611)                    # 2.61%
    assert close(r["fcf_yield"], 136_056 / 5_064_611)                         # 2.69%
    assert close(r["ebit_ev"], 158_063 / ev) and close(r["ev_ebit"], ev / 158_063)   # 32.19x
    loss = f.valuation(dict(FY26, ebit=-10), MARKET_CAP)
    assert loss["ebit_ev"] < 0 and math.isnan(loss["ev_ebit"])
    with_pref = f.valuation(dict(FY26, preferred_stock=1_000), MARKET_CAP)
    assert close(with_pref["book_to_market"], 111_093 / 5_064_611)
    assert close(with_pref["enterprise_value"], ev + 1_000)


def test_quality_inputs_apple_fy2026():
    roe_history = [0.9, 1.1, 1.2, 1.3, 132_175 / 112_093]
    r = f.quality_inputs(FY26, FY25, None, None, roe_history)
    wc26 = 173_857 - 169_915 - 56_722 + 11_903 + 5_287
    wc25 = 147_957 - 165_631 - 54_697 + 20_329 + 13_016
    assert close(r["q_gpoa"], 233_602 / 404_548)
    assert close(r["q_roe"], 132_175 / 112_093)
    assert close(r["q_roa"], 132_175 / 404_548)
    assert close(r["q_gmar"], 233_602 / 478_834)
    # CFOA = (NI + depreciation - change in working capital - capex) / assets
    assert close(r["q_cfoa"], (132_175 + 13_423 - (wc26 - wc25) - 9_041) / 404_548)
    assert close(r["q_acc"], -((wc26 - wc25) - 13_423) / 404_548)
    assert close(r["q_lev"], 80_111 / 404_548)
    mean = sum(roe_history) / 5
    assert close(r["q_evol"], math.sqrt(sum((x - mean) ** 2 for x in roe_history) / 4))
    assert math.isnan(r["q_d_gpoa"])                       # no five-year-ago figures supplied
    assert math.isnan(f.quality_inputs(FY26, FY25, None, None, [1.0, 1.1])["q_evol"])
    grown = f.quality_inputs(FY26, FY25, FY24, None, roe_history)   # FY24 standing in as the base year
    assert close(grown["q_d_gpoa"], (233_602 - 180_683) / 364_980)
    assert close(grown["q_d_roe"], (132_175 - 93_736) / 56_950)
    assert close(grown["q_d_gmar"], (233_602 - 180_683) / 391_035)
    negative_equity = f.quality_inputs(dict(FY26, equity=-5), FY25, None, None, roe_history)
    assert math.isnan(negative_equity["q_roe"])
