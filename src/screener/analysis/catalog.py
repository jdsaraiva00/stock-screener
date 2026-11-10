"""Every measure the app shows: label, group, which direction is favourable,
how to format it, what it means and where it comes from. The UI is driven by this."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from screener.analysis.formulas import CITATIONS


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    group: str
    better: int          # +1 higher is favourable, -1 lower is favourable, 0 neither
    fmt: str             # int | ratio | pct | money | multiple | flag
    about: str
    cite: str = ""       # key into CITATIONS
    components: tuple[str, ...] = ()


M = Measure
MEASURES: list[Measure] = [
    # Fundamental scores
    M("f_score", "F-Score", "Fundamental scores", +1, "int",
      "Nine yes/no tests of profitability, balance-sheet strength and efficiency, summed (0 to 9). "
      "Shown only when all nine can be computed.", "piotroski",
      ("f_roa", "f_cfo", "f_droa", "f_accrual", "f_dlever", "f_dliquid", "f_eq_offer", "f_dmargin", "f_dturn")),
    M("altman_z", "Altman Z", "Fundamental scores", +1, "ratio",
      "Bankruptcy-risk score. Below 1.81 distress zone, above 2.99 safe zone. Not applicable to financial companies.",
      "altman", ("z_x1", "z_x2", "z_x3", "z_x4", "z_x5")),
    M("beneish_m", "Beneish M", "Fundamental scores", -1, "ratio",
      "Earnings-manipulation score from eight ratios. Above -1.78 is the level Beneish associates with "
      "possible manipulation. Not applicable to financial companies.", "beneish",
      ("m_dsri", "m_gmi", "m_aqi", "m_sgi", "m_depi", "m_sgai", "m_tata", "m_lvgi")),
    M("accruals_cf", "Accruals (cash flow)", "Fundamental scores", -1, "pct",
      "Net income minus operating cash flow, over average total assets. High accruals mean earnings "
      "are less backed by cash.", "sloan"),
    M("accruals_sloan", "Accruals (Sloan)", "Fundamental scores", -1, "pct",
      "Sloan's balance-sheet accruals over average total assets: change in non-cash working capital "
      "less depreciation. Needs taxes payable and current debt to be reported.", "sloan"),
    M("gross_profitability", "Gross profitability", "Fundamental scores", +1, "pct",
      "Gross profit over total assets.", "novy_marx"),
    M("asset_growth", "Asset growth", "Fundamental scores", -1, "pct",
      "Year-on-year growth in total assets. Fast asset growth has preceded lower returns.", "cooper"),
    # Value
    M("book_to_market", "Book-to-market", "Value", +1, "ratio",
      "Book equity (shareholders' equity less preferred stock) over market capitalisation.", "fama_french"),
    M("earnings_yield", "Earnings yield", "Value", +1, "pct", "Net income over market capitalisation."),
    M("ebit_ev", "EBIT / EV", "Value", +1, "pct",
      "Operating profit over enterprise value (the inverse of EV/EBIT, so that higher is cheaper)."),
    M("ev_ebit", "EV / EBIT", "Value", 0, "multiple",
      "Enterprise value over operating profit. Shown only when both are positive."),
    M("fcf_yield", "Free cash flow yield", "Value", +1, "pct",
      "Operating cash flow less capital expenditure, over market capitalisation."),
    M("value_score", "Value score", "Value", +1, "pctile",
      "Average of the percentile ranks of book-to-market, earnings yield, EBIT/EV and free cash flow yield."),
    # Momentum
    M("mom_12_1", "Momentum 12-1", "Momentum", +1, "pct",
      "Total return from 12 months ago to 1 month ago, skipping the latest month.", "jegadeesh_titman"),
    # Quality
    M("quality", "Quality", "Quality", +1, "ratio",
      "Standardised sum of profitability, growth and safety scores. A simplified version of the paper's "
      "measure: growth uses totals not per-share residual income, and Ohlson's O-Score is left out.", "qmj",
      ("q_profitability", "q_growth", "q_safety")),
    M("q_profitability", "Profitability score", "Quality", +1, "ratio",
      "Average z-score of gross profit/assets, ROE, ROA, cash flow/assets, gross margin and low accruals.", "qmj",
      ("q_gpoa", "q_roe", "q_roa", "q_cfoa", "q_gmar", "q_acc")),
    M("q_growth", "Growth score", "Quality", +1, "ratio",
      "Average z-score of the five-year change in each profitability measure.", "qmj",
      ("q_d_gpoa", "q_d_roe", "q_d_roa", "q_d_cfoa", "q_d_gmar")),
    M("q_safety", "Safety score", "Quality", +1, "ratio",
      "Average z-score of low beta, low leverage, high Altman Z and low five-year ROE volatility.", "qmj",
      ("beta", "q_lev", "altman_z", "q_evol")),
    M("q_roe", "Return on equity", "Quality", +1, "pct", "Net income over book equity."),
    M("q_roa", "Return on assets", "Quality", +1, "pct", "Net income over total assets."),
    M("q_gmar", "Gross margin", "Quality", +1, "pct", "Gross profit over revenue."),
    M("q_lev", "Leverage", "Quality", -1, "pct", "Debt, minority interests and preferred stock over total assets."),
    # Low risk
    M("beta", "Beta", "Low risk", -1, "ratio",
      "Market beta: five-year correlation of three-day returns times the ratio of one-year daily "
      "volatilities, shrunk 40% towards 1. Market is an S&P 500 tracker.", "bab"),
    M("vol_1y", "Volatility 1y", "Low risk", -1, "pct", "Annualised standard deviation of daily returns over one year.", "bab"),
    M("low_risk_score", "Low-risk score", "Low risk", +1, "pctile",
      "Average of the percentile ranks of low beta and low volatility."),
    # Size and description
    M("market_cap", "Market cap", "Size", 0, "money", "Share price times shares outstanding."),
    M("ret_1m", "Return 1m", "Price", 0, "pct", "Total return over the last 21 trading days."),
    M("ret_3m", "Return 3m", "Price", 0, "pct", "Total return over the last 63 trading days."),
    M("ret_6m", "Return 6m", "Price", 0, "pct", "Total return over the last 126 trading days."),
    M("ret_1y", "Return 1y", "Price", 0, "pct", "Total return over the last 252 trading days."),
    M("ret_3y", "Return 3y", "Price", 0, "pct", "Total return over the last 756 trading days."),
    M("ret_5y", "Return 5y", "Price", 0, "pct", "Total return over the last 1,260 trading days."),
    M("max_drawdown_1y", "Max drawdown 1y", "Price", +1, "pct", "Largest peak-to-trough fall over the last year."),
    M("dist_52w_high", "From 52-week high", "Price", 0, "pct", "Price relative to its highest close in the last year."),
    M("ma50_gap", "Vs 50-day average", "Price", 0, "pct", "Price relative to its 50-day moving average."),
    M("ma200_gap", "Vs 200-day average", "Price", 0, "pct", "Price relative to its 200-day moving average."),
    M("trend_up", "50d above 200d", "Price", 0, "flag", "Whether the 50-day average is above the 200-day average."),
    M("composite", "Composite", "Composite", +1, "pctile",
      "Weighted average of percentile ranks, using the weights you choose. Needs at least half the weight to be available."),
]

# Components shown in score breakdowns (not ranked on their own).
COMPONENTS: dict[str, tuple[str, str, str]] = {
    # key: (label, fmt, explanation)
    "f_roa": ("Positive return on assets", "flag", "Net income / beginning total assets > 0"),
    "f_cfo": ("Positive operating cash flow", "flag", "Operating cash flow / beginning total assets > 0"),
    "f_droa": ("Return on assets improved", "flag", "ROA higher than a year earlier"),
    "f_accrual": ("Cash flow exceeds earnings", "flag", "Operating cash flow > net income"),
    "f_dlever": ("Leverage did not rise", "flag", "Long-term debt / average assets no higher than a year earlier"),
    "f_dliquid": ("Liquidity improved", "flag", "Current ratio higher than a year earlier"),
    "f_eq_offer": ("No new shares", "flag", "Shares outstanding no higher than a year earlier"),
    "f_dmargin": ("Gross margin improved", "flag", "Gross margin higher than a year earlier"),
    "f_dturn": ("Asset turnover improved", "flag", "Revenue / beginning assets higher than a year earlier"),
    "z_x1": ("X1 working capital / assets", "ratio", "Weight 1.2"),
    "z_x2": ("X2 retained earnings / assets", "ratio", "Weight 1.4"),
    "z_x3": ("X3 EBIT / assets", "ratio", "Weight 3.3"),
    "z_x4": ("X4 market cap / liabilities", "ratio", "Weight 0.6"),
    "z_x5": ("X5 revenue / assets", "ratio", "Weight 1.0"),
    "m_dsri": ("DSRI days sales in receivables", "ratio", "Weight +0.920. Receivables/sales vs a year earlier"),
    "m_gmi": ("GMI gross margin index", "ratio", "Weight +0.528. Prior gross margin / current"),
    "m_aqi": ("AQI asset quality index", "ratio", "Weight +0.404. Share of assets other than current assets and PP&E vs a year earlier"),
    "m_sgi": ("SGI sales growth index", "ratio", "Weight +0.892. Sales / prior sales"),
    "m_depi": ("DEPI depreciation index", "ratio", "Weight +0.115. Prior depreciation rate / current"),
    "m_sgai": ("SGAI SG&A index", "ratio", "Weight -0.172. SG&A/sales vs a year earlier"),
    "m_tata": ("TATA total accruals / assets", "ratio", "Weight +4.679. (Income - operating cash flow) / assets"),
    "m_lvgi": ("LVGI leverage index", "ratio", "Weight -0.327. (Current liabilities + long-term debt)/assets vs a year earlier"),
    "q_gpoa": ("Gross profit / assets", "pct", ""),
    "q_cfoa": ("Cash flow / assets", "pct", "(Net income + depreciation - change in working capital - capex) / assets"),
    "q_acc": ("Low accruals", "pct", "-(change in working capital - depreciation) / assets"),
    "q_d_gpoa": ("5y change, gross profit / assets", "pct", ""),
    "q_d_roe": ("5y change, net income / equity", "pct", ""),
    "q_d_roa": ("5y change, net income / assets", "pct", ""),
    "q_d_cfoa": ("5y change, cash flow / assets", "pct", ""),
    "q_d_gmar": ("5y change, gross profit / sales", "pct", ""),
    "q_evol": ("ROE volatility (5y)", "pct", "Standard deviation of annual return on equity over five years"),
}

BY_KEY = {m.key: m for m in MEASURES}
RANKED = [m.key for m in MEASURES if m.better != 0 and m.key != "composite"]
NOT_FOR_FINANCIALS = ("altman_z", "beneish_m", "z_x1", "z_x2", "z_x3", "z_x4", "z_x5",
                      "m_dsri", "m_gmi", "m_aqi", "m_sgi", "m_depi", "m_sgai", "m_tata", "m_lvgi")
DEFAULT_WEIGHTS = {"value_score": 1.0, "mom_12_1": 1.0, "quality": 1.0, "low_risk_score": 1.0}


def catalog_json() -> dict:
    return {
        "measures": [dict(asdict(m), citation=CITATIONS.get(m.cite, "")) for m in MEASURES],
        "components": {k: {"label": v[0], "fmt": v[1], "about": v[2]} for k, v in COMPONENTS.items()},
        "default_weights": DEFAULT_WEIGHTS,
        "not_for_financials": list(NOT_FOR_FINANCIALS),
    }
