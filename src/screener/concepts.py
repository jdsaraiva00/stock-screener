"""Which XBRL tags supply each financial concept.

Companies do not all use the same tag for the same line, and many changed tags
over time (revenue most of all, around the 2018 revenue-recognition standard).
Each concept lists candidate tags in priority order. For a given period the
first tag with a reported value wins, and the tag used is kept with the value
so it can be shown. If no listed tag has a value, the concept is missing for
that period; nothing is estimated.

This mapping is provisional until milestone 2 validates it formula by formula.
After editing it run `screener rebuild-facts` (no download needed).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import resources

GAAP = "us-gaap"
DEI = "dei"


@dataclass(frozen=True)
class Concept:
    key: str
    label: str
    kind: str                       # "duration" (flow over a period) or "instant" (balance)
    tags: tuple[str, ...]
    unit: str = "USD"
    taxonomy: str = GAAP


_CONCEPTS = [
    # Income statement
    Concept("revenue", "Revenue", "duration", (
        "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
        "RevenuesNetOfInterestExpense")),
    Concept("cost_of_revenue", "Cost of revenue", "duration", (
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")),
    Concept("gross_profit", "Gross profit", "duration", ("GrossProfit",)),
    Concept("sga", "Selling, general and administrative", "duration", (
        "SellingGeneralAndAdministrativeExpense",)),
    Concept("rd", "Research and development", "duration", ("ResearchAndDevelopmentExpense",)),
    Concept("depreciation_amortization", "Depreciation and amortization", "duration", (
        "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization")),
    Concept("operating_income", "Operating income", "duration", ("OperatingIncomeLoss",)),
    Concept("interest_expense", "Interest expense", "duration", (
        "InterestExpense", "InterestExpenseNonoperating")),
    Concept("pretax_income", "Pre-tax income", "duration", (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments")),
    Concept("income_tax", "Income tax expense", "duration", ("IncomeTaxExpenseBenefit",)),
    # Some companies (Caterpillar, several utilities) do not tag NetIncomeLoss in
    # their reports. The fallback is net income after preferred dividends, which is
    # the same figure unless the company has preferred stock. ProfitLoss is left out
    # because it includes the share of minority owners.
    Concept("net_income", "Net income", "duration", (
        "NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")),
    Concept("eps_diluted", "Diluted EPS", "duration", ("EarningsPerShareDiluted",), unit="USD/shares"),
    Concept("shares_diluted", "Diluted weighted average shares", "duration", (
        "WeightedAverageNumberOfDilutedSharesOutstanding",), unit="shares"),
    # Balance sheet
    Concept("total_assets", "Total assets", "instant", ("Assets",)),
    Concept("current_assets", "Current assets", "instant", ("AssetsCurrent",)),
    Concept("cash", "Cash and equivalents", "instant", ("CashAndCashEquivalentsAtCarryingValue",)),
    Concept("receivables", "Accounts receivable", "instant", ("AccountsReceivableNetCurrent",)),
    Concept("inventory", "Inventory", "instant", ("InventoryNet",)),
    Concept("ppe_net", "Property, plant and equipment, net", "instant", (
        "PropertyPlantAndEquipmentNet",)),
    Concept("total_liabilities", "Total liabilities", "instant", ("Liabilities",)),
    Concept("current_liabilities", "Current liabilities", "instant", ("LiabilitiesCurrent",)),
    Concept("debt_current", "Debt due within a year", "instant", ("LongTermDebtCurrent", "DebtCurrent")),
    Concept("long_term_debt", "Long-term debt, non-current", "instant", ("LongTermDebtNoncurrent",)),
    Concept("retained_earnings", "Retained earnings", "instant", (
        "RetainedEarningsAccumulatedDeficit",)),
    Concept("equity", "Shareholders' equity", "instant", ("StockholdersEquity",)),
    Concept("shares_outstanding", "Shares outstanding (balance sheet)", "instant", (
        "CommonStockSharesOutstanding",), unit="shares"),
    Concept("shares_outstanding_cover", "Shares outstanding (filing cover page)", "instant", (
        "EntityCommonStockSharesOutstanding",), unit="shares", taxonomy=DEI),
    # Cash flow statement
    Concept("cfo", "Cash flow from operations", "duration", (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
    Concept("capex", "Capital expenditure", "duration", (
        "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")),
    Concept("dividends_paid", "Dividends paid", "duration", (
        "PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
]

CONCEPTS: dict[str, Concept] = {c.key: c for c in _CONCEPTS}
# (taxonomy, tag) pairs the cache keeps from each company's filed facts.
STORED_TAGS: frozenset[tuple[str, str]] = frozenset(
    (c.taxonomy, tag) for c in _CONCEPTS for tag in c.tags)


@cache
def _predecessor_table() -> dict[int, tuple[int, ...]]:
    text = resources.files("screener").joinpath("reference/cik_predecessors.toml").read_text()
    return {int(k): tuple(v["ciks"]) for k, v in tomllib.loads(text).get("successor", {}).items()}


def predecessors(cik: int) -> tuple[int, ...]:
    """Earlier SEC registrants whose filings continue this company's history
    (see reference/cik_predecessors.toml)."""
    return _predecessor_table().get(cik, ())
