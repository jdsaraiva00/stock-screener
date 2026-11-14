"""User-defined measures: a formula over statement lines and market values.

A custom measure is a name, a formula such as `total_debt / market_cap`, and a
direction. It is computed on the cross-section wherever built-in measures are
(the screener, the stock page, the backtest on every rebalance date) and ranked
the same way, so it can be a filter, a column or a composite weight.

The formula language is deliberately small: + - * / parentheses, numbers, and the
names in NAMES. It is parsed with the `ast` module and only those node types are
accepted, so nothing else can run. Division by zero and any non-finite result
are missing values, never substituted.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from screener.analysis import engine
from screener.analysis.catalog import MEASURES

# Statement lines (from fundamental_history) and market values (from the cross-section)
# that a formula may use. Keys must be columns of the cross-section frame.
LINES: dict[str, str] = {
    "revenue": "Revenue", "gross_profit": "Gross profit", "ebit": "EBIT (operating profit)",
    "pretax_income": "Pre-tax income (EBT)", "income_tax": "Income tax expense", "net_income": "Net income",
    "interest_expense": "Interest expense", "depreciation_amortization": "Depreciation and amortisation",
    "sga": "Selling, general and administrative", "rd": "Research and development",
    "cfo": "Operating cash flow", "capex": "Capital expenditure", "free_cash_flow": "Free cash flow",
    "dividends_paid": "Dividends paid",
    "total_assets": "Total assets", "current_assets": "Current assets", "cash": "Cash and equivalents",
    "cash_and_short_term": "Cash and short-term investments", "receivables": "Accounts receivable",
    "inventory": "Inventory", "ppe_net": "Property, plant and equipment, net",
    "total_liabilities": "Total liabilities", "current_liabilities": "Current liabilities",
    "total_debt": "Total debt", "debt_current": "Debt due within a year", "debt_noncurrent": "Long-term debt",
    "working_capital": "Working capital", "equity": "Shareholders' equity", "retained_earnings": "Retained earnings",
    "minority_interest": "Minority interests", "preferred_stock": "Preferred stock",
    "shares": "Shares (diluted weighted average)", "eps_diluted": "Diluted EPS",
    "market_cap": "Market cap", "enterprise_value": "Enterprise value", "price": "Share price",
}
# Built-in measures may be used too (e.g. `beta * 2`), except yes/no flags and the composite.
MEASURE_NAMES: dict[str, str] = {m.key: m.label for m in MEASURES if m.fmt != "flag" and m.key != "composite"}
NAMES: dict[str, str] = {**LINES, **MEASURE_NAMES}
FORMATS = ("ratio", "pct", "multiple", "money")
KEY_PREFIX = "c_"

_BINARY = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: None}
_UNARY = {ast.USub: lambda a: -a, ast.UAdd: lambda a: a}


@dataclass(frozen=True)
class CustomMeasure:
    key: str
    label: str
    formula: str
    better: int = 0            # +1 higher is favourable, -1 lower, 0 neither (column only, not ranked)
    fmt: str = "ratio"

    def as_measure(self) -> dict:
        """In the shape of a catalog measure, so the UI treats it like a built-in one."""
        return {"key": self.key, "label": self.label, "group": "Custom", "better": self.better, "fmt": self.fmt,
                "about": f"Your formula: {self.formula}", "cite": "", "citation": "", "components": []}

    def as_dict(self) -> dict:
        return asdict(self)


def key_for(label: str) -> str:
    """A column name derived from the label: c_debt_to_market_cap."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40].strip("_")
    if not slug:
        raise ValueError("The name must contain a letter or a digit.")
    return KEY_PREFIX + slug


def validate(label: str, formula: str, better: int, fmt: str) -> CustomMeasure:
    """Check every field and return the measure. Raises ValueError with a message for the user."""
    label = (label or "").strip()
    if not label or len(label) > 60:
        raise ValueError("Give the measure a name of 1 to 60 characters.")
    if better not in (-1, 0, 1):
        raise ValueError("Direction must be higher is better (1), lower is better (-1) or neither (0).")
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of {', '.join(FORMATS)}.")
    formula = (formula or "").strip()
    if len(formula) > 300:
        raise ValueError("The formula is too long (300 characters at most).")
    names_used(formula)
    return CustomMeasure(key_for(label), label, formula, better, fmt)


def names_used(formula: str) -> list[str]:
    """The line names a formula refers to. Raises ValueError if it uses anything
    other than + - * / parentheses, numbers and known names."""
    if not formula.strip():
        raise ValueError("Enter a formula, for example total_debt / market_cap.")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Could not read the formula: {exc.msg}.") from None
    names: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            walk(node.left)
            walk(node.right)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            walk(node.operand)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            pass
        elif isinstance(node, ast.Name):
            if node.id not in NAMES:
                raise ValueError(f"Unknown name '{node.id}'. Pick lines from the list.")
            names.append(node.id)
        else:
            raise ValueError("Only + - * / parentheses, numbers and line names are allowed.")

    walk(tree)
    if not names:
        raise ValueError("The formula must use at least one line.")
    return names


def evaluate(formula: str, frame: pd.DataFrame) -> pd.Series:
    """The formula applied to every row of `frame`. A missing input, a zero divisor
    or an overflow gives a missing value for that row."""
    names_used(formula)
    tree = ast.parse(formula.strip(), mode="eval")
    missing = pd.Series(np.nan, index=frame.index)

    def value(node: ast.AST):
        if isinstance(node, ast.Expression):
            return value(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.Name):
            return pd.to_numeric(frame[node.id], errors="coerce") if node.id in frame else missing
        if isinstance(node, ast.UnaryOp):
            return _UNARY[type(node.op)](value(node.operand))
        left, right = value(node.left), value(node.right)
        if isinstance(node.op, ast.Div):
            if isinstance(right, pd.Series):
                right = right.where(right != 0)
            elif right == 0:
                return missing
            return left / right
        return _BINARY[type(node.op)](left, right)

    with np.errstate(all="ignore"):
        result = value(tree)
    if not isinstance(result, pd.Series):
        result = pd.Series(float(result), index=frame.index)
    return result.astype(float).replace([np.inf, -np.inf], np.nan)


def apply(frame: pd.DataFrame, measures: list[CustomMeasure]) -> pd.DataFrame:
    """Add each measure's values and, where it has a direction, its percentile ranks
    in the universe (__pct) and in the sector (__spct), like the built-in measures."""
    if not measures:
        return frame
    extra: dict[str, pd.Series] = {}
    for m in measures:
        values = evaluate(m.formula, frame)
        extra[m.key] = values
        if m.better:
            extra[f"{m.key}__pct"] = engine.percentile(values, m.better)
            if "sector" in frame:
                by_sector = values.groupby(frame["sector"])
                sized = by_sector.transform(lambda s: s.notna().sum())
                extra[f"{m.key}__spct"] = (by_sector.transform(lambda s: engine.percentile(s, m.better))
                                           .where(sized >= engine.MIN_SECTOR_SIZE))
    out = frame.drop(columns=[c for c in extra if c in frame])
    return pd.concat([out, pd.DataFrame(extra, index=frame.index)], axis=1)
