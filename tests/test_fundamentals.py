"""Filed-fundamentals queries, checked against Apple's actual 10-K and 10-Q figures
(fiscal 2026 10-K, accession 0000320193-26-000026, filed 2026-11-03)."""

import pytest

from screener.fundamentals import annual_series, fiscal_year_ends, instant_series, quarterly_series

from conftest import APPLE_CIK

M = 1_000_000


def test_annual_flow_with_filing_reference(apple):
    row = annual_series(apple, APPLE_CIK, "net_income").iloc[-1]
    assert (row.period_end, row.value) == ("2026-09-26", 132_175 * M)
    assert (row.tag, row.form, row.filed) == ("NetIncomeLoss", "10-K", "2026-11-03")
    assert row.accession == "0000320193-26-000026"
    assert not row.derived


def test_as_of_hides_figures_not_yet_filed(apple):
    # On 1 August 2026 the fiscal 2026 annual report did not exist yet.
    row = annual_series(apple, APPLE_CIK, "net_income", as_of="2026-08-01").iloc[-1]
    assert (row.period_end, row.value, row.filed) == ("2025-09-27", 112_010 * M, "2025-10-31")
    # The day before the fiscal 2025 10-K was filed, fiscal 2024 was the latest.
    row = annual_series(apple, APPLE_CIK, "net_income", as_of="2025-10-30").iloc[-1]
    assert row.period_end == "2024-09-28"


def test_fourth_quarter_is_derived_and_flagged(apple):
    q = quarterly_series(apple, APPLE_CIK, "net_income").set_index("period_end")
    assert q.loc["2026-06-27", "value"] == 29_789 * M and not q.loc["2026-06-27", "derived"]
    # Q4 = fiscal year 132,175 - nine months 101,464
    assert q.loc["2026-09-26", "value"] == 30_711 * M and q.loc["2026-09-26", "derived"]
    assert q.loc["2026-09-26", "first_filed"] == "2026-11-03"


def test_year_to_date_cash_flow_is_split_into_quarters(apple):
    q = quarterly_series(apple, APPLE_CIK, "cfo").set_index("period_end")
    assert q.loc["2025-12-27", "value"] == 53_925 * M and not q.loc["2025-12-27", "derived"]
    assert q.loc["2026-03-28", "value"] == (82_627 - 53_925) * M and q.loc["2026-03-28", "derived"]
    assert q.loc["2026-09-26", "value"] == (145_097 - 116_996) * M
    # four quarters add back to the reported fiscal year
    year = ["2025-12-27", "2026-03-28", "2026-06-27", "2026-09-26"]
    assert q.loc[year, "value"].sum() == 145_097 * M


def test_balance_sheet_annual_uses_fiscal_year_ends_only(apple):
    assert fiscal_year_ends(apple, APPLE_CIK)[-2:] == ["2025-09-27", "2026-09-26"]
    annual = annual_series(apple, APPLE_CIK, "total_assets")
    assert annual.iloc[-1].value == 404_548 * M
    assert "2026-06-27" not in set(annual.period_end)
    assert "2026-06-27" in set(instant_series(apple, APPLE_CIK, "total_assets").period_end)


def test_tag_change_keeps_original_filing_date(apple):
    """Apple reported fiscal 2017 revenue as SalesRevenueNet in November 2017 and
    re-tagged it as Revenues a year later. The value shown uses the preferred
    tag, but 'first filed' must stay November 2017."""
    rev = annual_series(apple, APPLE_CIK, "revenue").set_index("period_end")
    assert rev.loc["2017-09-30", "value"] == 229_234 * M
    assert rev.loc["2017-09-30", "tag"] == "Revenues"
    assert rev.loc["2017-09-30", "first_filed"] == "2017-11-03"
    assert rev.loc["2026-09-26", "value"] == 478_834 * M
    assert rev.loc["2026-09-26", "tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    early = annual_series(apple, APPLE_CIK, "revenue", as_of="2017-12-31").iloc[-1]
    assert (early.period_end, early.value, early.tag) == ("2017-09-30", 229_234 * M, "SalesRevenueNet")


def test_unmapped_or_absent_concept_is_empty_not_zero(apple):
    assert annual_series(apple, APPLE_CIK, "redeemable_minority").empty   # Apple reports none
    assert annual_series(apple, 999, "net_income").empty
    with pytest.raises(ValueError):
        quarterly_series(apple, APPLE_CIK, "total_assets")


def test_proxy_statement_figures_do_not_override_the_annual_report(apple):
    """Proxy statements (DEF 14A) repeat net income in XBRL, sometimes rounded, and are
    filed after the 10-K (seen with JPMorgan: 57,000 in the proxy against 57,048 audited).
    They are kept in the cache but never used in a series. The proxy row here is
    made up for the test; Apple's own proxy carries no such figure."""
    apple.execute(
        "INSERT INTO fundamentals_facts(cik,taxonomy,tag,unit,period_start,period_end,value,form,filed,accession) "
        "VALUES(?, 'us-gaap', 'NetIncomeLoss', 'USD', '2024-09-29', '2025-09-27', 112000000000, "
        "'DEF 14A', '2026-01-08', 'proxy-test')", (APPLE_CIK,))
    row = annual_series(apple, APPLE_CIK, "net_income", as_of="2026-08-01").iloc[-1]
    assert (row.value, row.form, row.filed) == (112_010 * M, "10-K", "2025-10-31")
