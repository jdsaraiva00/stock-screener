import httpx
import pandas as pd
import pytest

from screener.providers.base import ProviderError
from screener.providers.edgar import parse_company_facts, parse_submissions
from screener.providers.french import parse_french_csv
from screener.providers.http import ThrottledClient
from screener.providers.wikipedia import parse_constituents
from screener.providers.yahoo import tidy_prices

# First and last lines of the real F-F_Research_Data_Factors.csv (202609 vintage).
FRENCH_MONTHLY = """This file was created using the 202609 CRSP database.
The 1-month TBill rate data until 202405 are from Ibbotson Associates.

,Mkt-RF,SMB,HML,RF
192607,   2.89,  -2.42,  -2.75,   0.22
192608,   2.64,  -1.44,   4.13,   0.25
192609,   0.38,  -1.36,   0.05,   0.23

 Annual Factors: January-December
,Mkt-RF,SMB,HML,RF
  2024,  19.76, -11.31,  -8.43,   5.26
  2025,  13.30, -10.79,   8.71,   4.25
"""
FRENCH_DAILY = """notes

,Mkt-RF,SMB,HML,RMW,CMA,RF
20260929,   -0.21,   -0.03,   -0.50,   -0.26,   -0.43,    0.01
20260930,   -0.26,    0.10,   -0.88,   -99.99,    0.19,    0.01

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""


def test_french_monthly_block_only_and_month_end_dates():
    rows = parse_french_csv(FRENCH_MONTHLY)
    assert len(rows) == 12                                   # 3 months x 4 factors, no annual rows
    assert rows[0] == ("1926-07-31", "Mkt-RF", 2.89)
    assert ("1926-08-31", "HML", 4.13) in rows
    assert rows[-1] == ("1926-09-30", "RF", 0.23)


def test_french_daily_and_missing_marker_is_dropped():
    rows = parse_french_csv(FRENCH_DAILY)
    assert ("2026-09-30", "SMB", 0.10) in rows
    assert not [r for r in rows if r[0] == "2026-09-30" and r[1] == "RMW"]
    assert len(rows) == 11


def test_french_garbage_raises():
    with pytest.raises(ProviderError):
        parse_french_csv("<html>moved</html>")


def test_edgar_facts_parse(apple_doc):
    facts = list(parse_company_facts(apple_doc))
    fy = [f for f in facts if f.tag == "NetIncomeLoss" and f.period_end == "2026-09-26"
          and f.period_start == "2025-09-28"]
    assert len(fy) == 1
    assert (fy[0].value, fy[0].filed, fy[0].form, fy[0].unit) == (132_175_000_000, "2026-11-03", "10-K", "USD")
    assets = [f for f in facts if f.tag == "Assets"]
    assert assets and all(f.period_start == "" for f in assets)
    assert {f.taxonomy for f in facts} == {"us-gaap", "dei"}


def test_edgar_skips_entries_that_cannot_be_dated():
    doc = {"facts": {"us-gaap": {"Assets": {"units": {"USD": [
        {"end": "2025-12-31", "val": 5, "accn": "a", "filed": "2026-02-01"},
        {"end": "2025-12-31", "val": None, "accn": "b", "filed": "2026-02-01"},
        {"end": "2025-12-31", "val": 7, "accn": "c"},
    ]}}}}}
    assert [f.value for f in parse_company_facts(doc)] == [5.0]


def test_edgar_submissions_latest_report_ignores_other_forms():
    doc = {"cik": "0000320193", "name": "Apple Inc.", "sic": "3571", "sicDescription": "Electronic Computers",
           "fiscalYearEnd": "0926", "filings": {"recent": {
               "form": ["8-K", "4", "10-K", "10-Q"],
               "filingDate": ["2026-11-09", "2026-11-05", "2026-11-03", "2026-07-31"],
               "accessionNumber": ["x1", "x2", "0000320193-26-000026", "0000320193-26-000020"]}}}
    info = parse_submissions(doc)
    assert (info.cik, info.sic, info.fiscal_year_end) == (320193, "3571", "0926")
    assert (info.latest_report_filed, info.latest_report_accession) == ("2026-11-03", "0000320193-26-000026")


WIKI = """<html><body><table id="constituents"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>
<th>GICS Sub-Industry</th><th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
<tr><td>MMM</td><td>3M</td><td>Industrials</td><td>Industrial Conglomerates</td><td>Saint Paul</td><td>1957-03-04</td><td>0000066740</td><td>1902</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td><td>Multi-Sector Holdings</td><td>Omaha</td><td>2010-02-16</td><td>0001067983</td><td>1839</td></tr>
<tr><td>XYZ</td><td>No Date Co</td><td>Energy</td><td>Oil</td><td>Texas</td><td></td><td>0000000123</td><td>1999</td></tr>
</table></body></html>"""


def test_wikipedia_constituents():
    members = parse_constituents(WIKI, min_rows=1)
    assert [m.ticker for m in members] == ["MMM", "BRK-B", "XYZ"]      # dot becomes dash
    assert (members[0].cik, members[0].sector, members[0].date_added) == (66740, "Industrials", "1957-03-04")
    assert members[2].date_added is None


def test_wikipedia_refuses_a_shrunken_or_changed_table():
    with pytest.raises(ProviderError, match="about 500"):
        parse_constituents(WIKI)
    with pytest.raises(ProviderError):
        parse_constituents(WIKI.replace('id="constituents"', 'id="other"'))
    with pytest.raises(ProviderError, match="missing columns"):
        parse_constituents(WIKI.replace("<th>CIK</th>", "<th>Code</th>"), min_rows=1)


def test_yahoo_price_frame_is_tidied_and_empty_days_dropped():
    raw = pd.DataFrame(
        {"Open": [1.0, None], "High": [2.0, None], "Low": [0.5, None], "Close": [1.5, None],
         "Adj Close": [1.4, None], "Volume": [100, None], "Dividends": [0.0, None], "Stock Splits": [0.0, None]},
        index=pd.to_datetime(["2026-11-09", "2026-11-10"]))
    out = tidy_prices(raw)
    assert out.to_dict("records") == [{"date": "2026-11-09", "open": 1.0, "high": 2.0, "low": 0.5,
                                       "close": 1.5, "adj_close": 1.4, "volume": 100.0,
                                       "dividend": 0.0, "split": 0.0}]


def _client(handler, retries=3):
    return ThrottledClient(1000, "test", retries=retries, backoff=0, transport=httpx.MockTransport(handler))


def test_http_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503 if len(calls) < 3 else 200, text="ok")

    assert _client(handler).get("https://example.test/x").text == "ok"
    assert len(calls) == 3


def test_http_gives_up_and_does_not_retry_a_refusal():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403)

    with pytest.raises(ProviderError, match="HTTP 403"):
        _client(handler).get("https://example.test/x")
    assert len(calls) == 1

    with pytest.raises(ProviderError, match="HTTP 500"):
        _client(lambda r: httpx.Response(500), retries=2).get("https://example.test/x")


def test_wikipedia_changes_table():
    from pathlib import Path

    from screener.providers.wikipedia import parse_changes

    html = (Path(__file__).parent / "fixtures" / "sp500_changes_trimmed.html").read_text()
    changes = parse_changes(html, min_rows=40)
    assert changes[0].__dict__ == {"date": "2026-10-30", "action": "added", "ticker": "OKTA", "name": "Okta, Inc.",
                                   "reason": "S&P 500 constituent Kimberly-Clark acquired Kenvue."}
    assert changes[1].ticker == "KVUE" and changes[1].action == "removed"
    only_removed = [c for c in changes if c.date == "2026-10-06" and c.ticker == "CTVA"]
    assert len(only_removed) == 1 and only_removed[0].action == "removed"
    assert all(c.action in ("added", "removed") and c.date[:4] >= "1976" for c in changes)
    with pytest.raises(ProviderError, match="at least 300"):
        parse_changes(html)
    with pytest.raises(ProviderError, match="not found"):
        parse_changes(html.replace('id="changes"', 'id="other"'), min_rows=1)
    from screener.providers.wikipedia import _ticker
    assert _ticker("CT.VA |") == "CT-VA" and _ticker(" BRK.B ") == "BRK-B"      # page artefacts, symbol style
    assert _ticker(float("nan")) is None and _ticker("|") is None
