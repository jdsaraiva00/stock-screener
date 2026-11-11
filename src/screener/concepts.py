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
        "CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
        # Cost of sales shown without depreciation, which is also how Compustat defines COGS.
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization")),
    Concept("gross_profit", "Gross profit", "duration", ("GrossProfit",)),
    Concept("sga", "Selling, general and administrative", "duration", (
        "SellingGeneralAndAdministrativeExpense",)),
    Concept("rd", "Research and development", "duration", ("ResearchAndDevelopmentExpense",)),
    Concept("general_admin", "General and administrative", "duration", (
        "GeneralAndAdministrativeExpense",)),
    Concept("selling_marketing", "Selling and marketing", "duration", (
        "SellingAndMarketingExpense",)),
    Concept("depreciation_amortization", "Depreciation and amortization", "duration", (
        "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization", "Depreciation")),
    Concept("operating_income", "Operating income", "duration", ("OperatingIncomeLoss",)),
    Concept("interest_expense", "Interest expense", "duration", (
        "InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense", "InterestExpenseDebt")),
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
    Concept("income_continuing", "Income from continuing operations", "duration", (
        "IncomeLossFromContinuingOperations",)),
    Concept("profit_incl_minority", "Net income including minority interests", "duration", (
        "ProfitLoss",)),
    Concept("minority_income", "Net income attributable to minority interests", "duration", (
        "NetIncomeLossAttributableToNoncontrollingInterest",)),
    Concept("eps_diluted", "Diluted EPS", "duration", ("EarningsPerShareDiluted",), unit="USD/shares"),
    Concept("shares_diluted", "Diluted weighted average shares", "duration", (
        "WeightedAverageNumberOfDilutedSharesOutstanding",), unit="shares"),
    # Balance sheet
    Concept("total_assets", "Total assets", "instant", ("Assets",)),
    Concept("current_assets", "Current assets", "instant", ("AssetsCurrent",)),
    Concept("cash", "Cash and equivalents", "instant", ("CashAndCashEquivalentsAtCarryingValue",)),
    Concept("cash_and_short_term", "Cash and short-term investments", "instant", (
        "CashCashEquivalentsAndShortTermInvestments",)),
    Concept("short_term_investments", "Short-term investments", "instant", (
        "ShortTermInvestments", "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "DebtSecuritiesAvailableForSaleExcludingAccruedInterestCurrent")),
    Concept("receivables", "Accounts receivable", "instant", (
        "AccountsReceivableNetCurrent", "ReceivablesNetCurrent")),
    Concept("inventory", "Inventory", "instant", ("InventoryNet",)),
    Concept("ppe_net", "Property, plant and equipment, net", "instant", (
        "PropertyPlantAndEquipmentNet",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization")),
    Concept("total_liabilities", "Total liabilities", "instant", ("Liabilities",)),
    Concept("current_liabilities", "Current liabilities", "instant", ("LiabilitiesCurrent",)),
    Concept("taxes_payable", "Income taxes payable", "instant", (
        "AccruedIncomeTaxesCurrent", "TaxesPayableCurrent")),
    # Debt is tagged in many ways; analysis.statements combines these lines.
    Concept("debt_current_total", "Debt due within a year, total", "instant", ("DebtCurrent",)),
    Concept("long_term_debt_current", "Current portion of long-term debt", "instant", (
        "LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent")),
    Concept("short_term_borrowings", "Short-term borrowings", "instant", ("ShortTermBorrowings",)),
    Concept("commercial_paper", "Commercial paper", "instant", ("CommercialPaper",)),
    Concept("long_term_debt", "Long-term debt, non-current", "instant", (
        "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations")),
    Concept("long_term_debt_total", "Long-term debt including current portion", "instant", (
        "LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities")),
    Concept("debt_all", "Total debt as one line", "instant", (
        "DebtLongtermAndShorttermCombinedAmount", "DebtAndCapitalLeaseObligations")),
    Concept("retained_earnings", "Retained earnings", "instant", (
        "RetainedEarningsAccumulatedDeficit",)),
    Concept("equity", "Shareholders' equity", "instant", ("StockholdersEquity",)),
    Concept("equity_incl_minority", "Total equity including minority interests", "instant", (
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",)),
    Concept("minority_interest", "Minority interests", "instant", ("MinorityInterest",)),
    Concept("redeemable_minority", "Redeemable minority interests", "instant", (
        "RedeemableNoncontrollingInterestEquityCarryingAmount",)),
    Concept("temporary_equity", "Temporary equity", "instant", (
        "TemporaryEquityCarryingAmountAttributableToParent",)),
    Concept("preferred_stock", "Preferred stock", "instant", ("PreferredStockValue",)),
    Concept("shares_outstanding", "Shares outstanding (balance sheet)", "instant", (
        "CommonStockSharesOutstanding",), unit="shares"),
    Concept("shares_outstanding_cover", "Shares outstanding (filing cover page)", "instant", (
        "EntityCommonStockSharesOutstanding",), unit="shares", taxonomy=DEI),
    # Cash flow statement
    Concept("cfo", "Cash flow from operations", "duration", (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
    Concept("capex", "Capital expenditure", "duration", (
        "PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
        "PaymentsForCapitalImprovements")),
    Concept("dividends_paid", "Dividends paid", "duration", (
        "PaymentsOfDividends", "PaymentsOfDividendsCommonStock")),
]

CONCEPTS: dict[str, Concept] = {c.key: c for c in _CONCEPTS}
_all_tags = [(c.taxonomy, t) for c in _CONCEPTS for t in c.tags]
assert len(_all_tags) == len(set(_all_tags)), "a tag may belong to one concept only"
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
