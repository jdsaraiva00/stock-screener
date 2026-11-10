"""Plain-language observations, produced by fixed rules (no language model).

Every insight names the measures it rests on, so the UI can point at the same
numbers on the page. Thresholds are the papers' where they give one, otherwise
simple deciles and quintiles of the universe.
"""

from __future__ import annotations

import math

from screener.analysis.formulas import ALTMAN_DISTRESS, ALTMAN_SAFE, BENEISH_THRESHOLD


def _has(*values) -> bool:
    return all(v is not None and not (isinstance(v, float) and math.isnan(v)) for v in values)


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _ordinal(p: float) -> str:
    n = int(round(p))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def insights_for(row: dict, previous_year: dict | None = None) -> list[dict]:
    """row: one cross-section row (measures and their __pct ranks).
    previous_year: the same company's prior fiscal-year history row, if any."""
    out: list[dict] = []

    def add(tone: str, text: str, *measures: str) -> None:
        out.append({"tone": tone, "text": text, "measures": list(measures)})

    g = row.get
    f_now, f_before = g("f_score"), (previous_year or {}).get("f_score")
    if _has(f_now, f_before) and abs(f_now - f_before) >= 2:
        verb, tone = ("rose", "good") if f_now > f_before else ("fell", "bad")
        add(tone, f"F-Score {verb} from {int(f_before)} to {int(f_now)} over the past fiscal year.", "f_score")
    if _has(f_now) and f_now >= 8:
        add("good", f"F-Score of {int(f_now)} out of 9: strong on Piotroski's financial-strength tests.", "f_score")
    elif _has(f_now) and f_now <= 3:
        add("bad", f"F-Score of {int(f_now)} out of 9: weak on Piotroski's financial-strength tests.", "f_score")

    if g("financial"):
        add("neutral", "Altman Z and Beneish M are not shown: they are not meaningful for financial companies.",
            "altman_z", "beneish_m")
    else:
        m = g("beneish_m")
        if _has(m) and m > BENEISH_THRESHOLD:
            add("bad", f"M-Score of {m:.2f} is above {BENEISH_THRESHOLD}, the threshold Beneish associates "
                       "with possible earnings manipulation.", "beneish_m")
        z = g("altman_z")
        if _has(z) and z < ALTMAN_DISTRESS:
            add("bad", f"Altman Z of {z:.2f} is below {ALTMAN_DISTRESS}, Altman's distress zone.", "altman_z")
        elif _has(z) and z < ALTMAN_SAFE:
            add("neutral", f"Altman Z of {z:.2f} is in the grey zone between {ALTMAN_DISTRESS} and {ALTMAN_SAFE}.",
                "altman_z")

    value, mom, quality = g("value_score__pct"), g("mom_12_1__pct"), g("quality__pct")
    if _has(value, mom) and value >= 80 and mom <= 10:
        add("neutral", f"Cheap on value ({_ordinal(value)} percentile) but in the bottom momentum decile "
                       f"(12-1 month return {_pct(g('mom_12_1'))}).", "value_score", "mom_12_1")
    if _has(value, mom) and value <= 20 and mom >= 90:
        add("neutral", f"Expensive on value ({_ordinal(value)} percentile) with top-decile momentum "
                       f"(12-1 month return {_pct(g('mom_12_1'))}).", "value_score", "mom_12_1")
    if _has(value, quality) and value >= 80 and quality >= 80:
        add("good", f"Both cheap ({_ordinal(value)} percentile on value) and high quality "
                    f"({_ordinal(quality)} percentile).", "value_score", "quality")
    if _has(value, quality) and value >= 80 and quality <= 20:
        add("bad", f"Cheap ({_ordinal(value)} percentile on value) but low quality "
                   f"({_ordinal(quality)} percentile): a possible value trap.", "value_score", "quality")

    acc, acc_rank = g("accruals_cf"), g("accruals_cf__pct")
    if _has(acc, acc_rank) and acc_rank <= 10:
        add("bad", f"Accruals of {_pct(acc)} of assets are among the highest tenth of the universe: "
                   "earnings are running ahead of cash flow.", "accruals_cf")
    growth, growth_rank = g("asset_growth"), g("asset_growth__pct")
    if _has(growth, growth_rank) and growth_rank <= 10:
        add("neutral", f"Total assets grew {_pct(growth)} in the last fiscal year, among the fastest tenth "
                       "of the universe; fast asset growth has tended to precede weaker returns.", "asset_growth")
    gp_rank = g("gross_profitability__pct")
    if _has(gp_rank) and gp_rank >= 90:
        add("good", f"Gross profitability of {_pct(g('gross_profitability'))} of assets is in the top tenth "
                    "of the universe.", "gross_profitability")

    high, drawdown = g("dist_52w_high"), g("max_drawdown_1y")
    if _has(high) and high >= -0.03:
        add("neutral", f"Trading within 3% of its 52-week high ({_pct(high)}).", "dist_52w_high")
    if _has(high) and high <= -0.30:
        add("neutral", f"Trading {_pct(high)} below its 52-week high.", "dist_52w_high")
    if _has(drawdown) and drawdown <= -0.40:
        add("bad", f"Largest fall over the past year was {_pct(drawdown)}.", "max_drawdown_1y")
    ma200, trend = g("ma200_gap"), g("trend_up")
    if _has(ma200, trend) and ma200 < 0 and trend == 0:
        add("bad", f"In a downtrend: price is {_pct(ma200)} against its 200-day average and the 50-day "
                   "average is below the 200-day.", "ma200_gap", "trend_up")
    beta_rank = g("beta__pct")
    if _has(beta_rank) and beta_rank <= 10:
        add("neutral", f"Beta of {g('beta'):.2f} is among the highest tenth of the universe.", "beta")
    return out
