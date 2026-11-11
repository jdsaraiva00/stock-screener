"""The published formulas, as pure functions of statement lines.

Each function takes one fiscal year's lines (`cur`) and earlier years where
needed, as mappings of name -> number, and returns the result together with
every component. A missing input makes the affected component NaN; nothing is
substituted. Line names are those produced by analysis.statements.derive.

Sources were checked against the papers (see CITATIONS and each docstring).
"""

from __future__ import annotations

import math
from typing import Mapping

NAN = float("nan")
Lines = Mapping[str, float]

CITATIONS = {
    "piotroski": "Piotroski, J. (2000). Value Investing: The Use of Historical Financial Statement "
                 "Information to Separate Winners from Losers. Journal of Accounting Research 38.",
    "altman": "Altman, E. (1968). Financial Ratios, Discriminant Analysis and the Prediction of "
              "Corporate Bankruptcy. Journal of Finance 23(4).",
    "beneish": "Beneish, M. (1999). The Detection of Earnings Manipulation. Financial Analysts Journal 55(5).",
    "sloan": "Sloan, R. (1996). Do Stock Prices Fully Reflect Information in Accruals and Cash Flows "
             "about Future Earnings? The Accounting Review 71(3).",
    "novy_marx": "Novy-Marx, R. (2013). The Other Side of Value: The Gross Profitability Premium. "
                 "Journal of Financial Economics 108(1).",
    "cooper": "Cooper, M., Gulen, H. and Schill, M. (2008). Asset Growth and the Cross-Section of "
              "Stock Returns. Journal of Finance 63(4).",
    "fama_french": "Fama, E. and French, K. (1992). The Cross-Section of Expected Stock Returns. "
                   "Journal of Finance 47(2).",
    "jegadeesh_titman": "Jegadeesh, N. and Titman, S. (1993). Returns to Buying Winners and Selling "
                        "Losers. Journal of Finance 48(1).",
    "qmj": "Asness, C., Frazzini, A. and Pedersen, L. (2019). Quality Minus Junk. Review of "
           "Accounting Studies 24(1).",
    "bab": "Frazzini, A. and Pedersen, L. (2014). Betting Against Beta. Journal of Financial Economics 111(1).",
    "mclean_pontiff": "McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock "
                      "Return Predictability? Journal of Finance 71(1).",
}

ALTMAN_DISTRESS, ALTMAN_SAFE = 1.81, 2.99
BENEISH_THRESHOLD = -1.78


def g(lines: Lines | None, name: str) -> float:
    """A line's value, NaN if the year or the line is missing."""
    if lines is None:
        return NAN
    value = lines.get(name, NAN)
    return NAN if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)


def div(a: float, b: float) -> float:
    return NAN if math.isnan(a) or math.isnan(b) or b == 0 else a / b


def _flag(condition_inputs: tuple[float, ...], condition: bool) -> float:
    return NAN if any(math.isnan(x) for x in condition_inputs) else float(condition)


def piotroski(cur: Lines, prev: Lines | None, prev2: Lines | None) -> dict:
    """Piotroski (2000) F-Score: nine yes/no signals, summed.

    Paper definitions: ROA and CFO are net income (before extraordinary items)
    and operating cash flow over beginning-of-year total assets; leverage is
    long-term debt over average total assets; turnover is sales over
    beginning-of-year total assets. Two choices here: unchanged leverage counts
    as "did not rise" (1); and "no equity issued" is measured as shares
    outstanding not higher than a year earlier, the usual proxy, because
    issuance itself is not reliably tagged.
    """
    ta0, ta1, ta2 = g(cur, "total_assets"), g(prev, "total_assets"), g(prev2, "total_assets")
    roa = div(g(cur, "net_income"), ta1)
    roa_prev = div(g(prev, "net_income"), ta2)
    cfo = div(g(cur, "cfo"), ta1)
    lever = div(g(cur, "debt_noncurrent"), (ta0 + ta1) / 2)
    lever_prev = div(g(prev, "debt_noncurrent"), (ta1 + ta2) / 2)
    liquid = div(g(cur, "current_assets"), g(cur, "current_liabilities"))
    liquid_prev = div(g(prev, "current_assets"), g(prev, "current_liabilities"))
    shares = g(cur, "shares_outstanding") if not math.isnan(g(cur, "shares_outstanding")) else g(cur, "shares")
    shares_prev = g(prev, "shares_outstanding") if not math.isnan(g(prev, "shares_outstanding")) else g(prev, "shares")
    margin = div(g(cur, "gross_profit"), g(cur, "revenue"))
    margin_prev = div(g(prev, "gross_profit"), g(prev, "revenue"))
    turn = div(g(cur, "revenue"), ta1)
    turn_prev = div(g(prev, "revenue"), ta2)
    values = {"roa": roa, "cfo": cfo, "roa_prev": roa_prev, "lever": lever, "lever_prev": lever_prev,
              "liquid": liquid, "liquid_prev": liquid_prev, "shares": shares, "shares_prev": shares_prev,
              "margin": margin, "margin_prev": margin_prev, "turn": turn, "turn_prev": turn_prev}
    signals = {
        "f_roa": _flag((roa,), roa > 0),
        "f_cfo": _flag((cfo,), cfo > 0),
        "f_droa": _flag((roa, roa_prev), roa > roa_prev),
        "f_accrual": _flag((cfo, roa), cfo > roa),
        "f_dlever": _flag((lever, lever_prev), lever <= lever_prev),
        "f_dliquid": _flag((liquid, liquid_prev), liquid > liquid_prev),
        "f_eq_offer": _flag((shares, shares_prev), shares <= shares_prev),
        "f_dmargin": _flag((margin, margin_prev), margin > margin_prev),
        "f_dturn": _flag((turn, turn_prev), turn > turn_prev),
    }
    known = [s for s in signals.values() if not math.isnan(s)]
    return {"f_score": sum(known) if len(known) == 9 else NAN, "f_signals_known": len(known),
            **signals, **{f"f_v_{k}": v for k, v in values.items()}}


def altman_z(cur: Lines, market_cap: float) -> dict:
    """Altman (1968) Z-Score for listed manufacturers:
    Z = 1.2 X1 + 1.4 X2 + 3.3 X3 + 0.6 X4 + 1.0 X5 (ratios as decimals), where
    X1 working capital / total assets, X2 retained earnings / total assets,
    X3 EBIT / total assets, X4 market value of equity / total liabilities,
    X5 sales / total assets. Below 1.81 distress, above 2.99 safe.
    Not meaningful for financial companies."""
    ta = g(cur, "total_assets")
    x1 = div(g(cur, "working_capital"), ta)
    x2 = div(g(cur, "retained_earnings"), ta)
    x3 = div(g(cur, "ebit"), ta)
    x4 = div(market_cap, g(cur, "total_liabilities"))
    x5 = div(g(cur, "revenue"), ta)
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
    return {"altman_z": z, "z_x1": x1, "z_x2": x2, "z_x3": x3, "z_x4": x4, "z_x5": x5}


def beneish_m(cur: Lines, prev: Lines | None) -> dict:
    """Beneish (1999) eight-variable M-Score:
    M = -4.84 + 0.920 DSRI + 0.528 GMI + 0.404 AQI + 0.892 SGI + 0.115 DEPI
        - 0.172 SGAI + 4.679 TATA - 0.327 LVGI.
    Above -1.78 suggests possible manipulation.

    Choices: TATA is (income from continuing operations - operating cash flow) /
    total assets, the cash-flow form Beneish uses in later work, with net income
    where continuing-operations income is not tagged. AQI uses current assets and
    net PP&E as in the 1999 paper. Depreciation is depreciation and amortisation
    as reported in the cash flow statement. Not meaningful for financial companies."""
    def ratio(now: float, before: float) -> float:
        return div(now, before)

    rev0, rev1 = g(cur, "revenue"), g(prev, "revenue")
    ta0, ta1 = g(cur, "total_assets"), g(prev, "total_assets")
    dsri = ratio(div(g(cur, "receivables"), rev0), div(g(prev, "receivables"), rev1))
    gmi = ratio(div(g(prev, "gross_profit"), rev1), div(g(cur, "gross_profit"), rev0))
    aqi = ratio(1 - div(g(cur, "current_assets") + g(cur, "ppe_net"), ta0),
                1 - div(g(prev, "current_assets") + g(prev, "ppe_net"), ta1))
    sgi = ratio(rev0, rev1)
    dep0, dep1 = g(cur, "depreciation_amortization"), g(prev, "depreciation_amortization")
    depi = ratio(div(dep1, dep1 + g(prev, "ppe_net")), div(dep0, dep0 + g(cur, "ppe_net")))
    sgai = ratio(div(g(cur, "sga"), rev0), div(g(prev, "sga"), rev1))
    lvgi = ratio(div(g(cur, "current_liabilities") + g(cur, "debt_noncurrent"), ta0),
                 div(g(prev, "current_liabilities") + g(prev, "debt_noncurrent"), ta1))
    income = g(cur, "income_continuing")
    if math.isnan(income):
        income = g(cur, "net_income")
    tata = div(income - g(cur, "cfo"), ta0)
    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi
         - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)
    return {"beneish_m": m, "m_dsri": dsri, "m_gmi": gmi, "m_aqi": aqi, "m_sgi": sgi,
            "m_depi": depi, "m_sgai": sgai, "m_tata": tata, "m_lvgi": lvgi}


def _operating_working_capital(lines: Lines | None) -> float:
    """Current assets - current liabilities - cash and short-term investments
    + debt in current liabilities + income taxes payable."""
    return (g(lines, "current_assets") - g(lines, "current_liabilities") - g(lines, "cash_and_short_term")
            + g(lines, "debt_current") + g(lines, "taxes_payable"))


def _wc_change(cur: Lines | None, prev: Lines | None) -> float:
    """Change in operating working capital. Missing if the two years' cash and
    short-term investments were assembled differently (e.g. a company re-tagged
    its investments), because the difference would then be an artefact."""
    a, b = g(cur, "cash_basis"), g(prev, "cash_basis")
    if not math.isnan(a) and not math.isnan(b) and a != b:
        return NAN
    return _operating_working_capital(cur) - _operating_working_capital(prev)


def accruals(cur: Lines, prev: Lines | None) -> dict:
    """Two accrual measures, both scaled by average total assets. Lower is better.

    accruals_sloan: Sloan (1996), balance-sheet form:
      (change in current assets - change in cash) - (change in current liabilities
      - change in short-term debt - change in taxes payable) - depreciation.
    accruals_cf: net income minus operating cash flow, the cash-flow-statement
      form (Hribar and Collins, 2002), available for far more companies."""
    avg_assets = (g(cur, "total_assets") + g(prev, "total_assets")) / 2
    d_wc = _wc_change(cur, prev)
    sloan = div(d_wc - g(cur, "depreciation_amortization"), avg_assets)
    cash_flow = div(g(cur, "net_income") - g(cur, "cfo"), avg_assets)
    return {"accruals_sloan": sloan, "accruals_cf": cash_flow}


def gross_profitability(cur: Lines) -> float:
    """Novy-Marx (2013): (revenue - cost of goods sold) / total assets."""
    return div(g(cur, "gross_profit"), g(cur, "total_assets"))


def asset_growth(cur: Lines, prev: Lines | None) -> float:
    """Cooper, Gulen and Schill (2008): year-on-year growth in total assets."""
    return div(g(cur, "total_assets"), g(prev, "total_assets")) - 1


def book_equity(lines: Lines | None) -> float:
    """Shareholders' equity less preferred stock where reported. (Fama and French
    also add balance-sheet deferred taxes, which is not done here.)"""
    preferred = g(lines, "preferred_stock")
    return g(lines, "equity") - (0.0 if math.isnan(preferred) else preferred)


def quality_inputs(cur: Lines, prev: Lines | None, y5: Lines | None, y6: Lines | None,
                   roe_history: list[float]) -> dict:
    """Raw inputs to the quality composite of Asness, Frazzini and Pedersen (2019).

    Profitability: GPOA, ROE, ROA, CFOA = (net income + depreciation - change in
    working capital - capex) / assets, GMAR, and ACC = -(change in working
    capital - depreciation) / assets.
    Growth: five-year change in each profit measure over its denominator five
    years ago. Simplified from the paper: totals rather than per-share amounts,
    and no risk-free capital charge.
    Safety inputs here: leverage = (debt + minority interests + preferred) /
    assets, and the standard deviation of annual ROE over five years (the
    paper's fallback when quarterly data is unavailable). Beta and Altman Z are
    added by the caller; Ohlson's O-Score is not included."""
    def cash_flow(now: Lines | None, before: Lines | None) -> float:
        d_wc = _wc_change(now, before)
        return g(now, "net_income") + g(now, "depreciation_amortization") - d_wc - g(now, "capex")

    def plus_if_reported(lines: Lines | None, name: str) -> float:
        value = g(lines, name)
        return 0.0 if math.isnan(value) else value

    ta, be = g(cur, "total_assets"), book_equity(cur)
    gp, ni = g(cur, "gross_profit"), g(cur, "net_income")
    d_wc = _wc_change(cur, prev)
    cf = cash_flow(cur, prev)
    ta5, be5 = g(y5, "total_assets"), book_equity(y5)
    evol = NAN
    recent = [r for r in roe_history[-5:] if not math.isnan(r)]
    if len(roe_history) >= 5 and len(recent) == 5:
        mean = sum(recent) / 5
        evol = math.sqrt(sum((r - mean) ** 2 for r in recent) / 4)
    return {
        "q_gpoa": div(gp, ta), "q_roe": div(ni, be) if be > 0 else NAN, "q_roa": div(ni, ta),
        "q_cfoa": div(cf, ta), "q_gmar": div(gp, g(cur, "revenue")),
        "q_acc": -div(d_wc - g(cur, "depreciation_amortization"), ta),
        "q_d_gpoa": div(gp - g(y5, "gross_profit"), ta5),
        "q_d_roe": div(ni - g(y5, "net_income"), be5) if be5 > 0 else NAN,
        "q_d_roa": div(ni - g(y5, "net_income"), ta5),
        "q_d_cfoa": div(cf - cash_flow(y5, y6), ta5),
        "q_d_gmar": div(gp - g(y5, "gross_profit"), g(y5, "revenue")),
        "q_lev": div(g(cur, "total_debt") + plus_if_reported(cur, "minority_interest")
                     + plus_if_reported(cur, "preferred_stock"), ta),
        "q_evol": evol,
    }


def valuation(cur: Lines, market_cap: float) -> dict:
    """Value measures against a market capitalisation.

    book_to_market: Fama and French (1992). earnings_yield: net income / market
    cap. fcf_yield: (operating cash flow - capex) / market cap. Enterprise value
    = market cap + debt + minority interests + preferred - cash and short-term
    investments. ebit_ev is EBIT / EV, which ranks sensibly when EBIT is negative;
    ev_ebit is shown only when EBIT and EV are positive."""
    def or_zero(name: str) -> float:
        value = g(cur, name)
        return 0.0 if math.isnan(value) else value

    ev = (market_cap + g(cur, "total_debt") + or_zero("minority_interest") + or_zero("preferred_stock")
          - g(cur, "cash_and_short_term"))
    ebit = g(cur, "ebit")
    be = book_equity(cur)
    return {
        "book_to_market": div(be, market_cap),
        "earnings_yield": div(g(cur, "net_income"), market_cap),
        "fcf_yield": div(g(cur, "free_cash_flow"), market_cap),
        "enterprise_value": ev,
        "ebit_ev": div(ebit, ev) if ev > 0 else NAN,
        "ev_ebit": div(ev, ebit) if ebit > 0 and ev > 0 else NAN,
    }
