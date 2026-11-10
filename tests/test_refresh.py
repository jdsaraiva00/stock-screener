import pandas as pd
import pytest

from screener import db
from screener.config import Config, ConfigError
from screener.providers.base import DataProvider, FilerInfo, Member, Profile, ProviderError
from screener.providers.edgar import parse_company_facts
from screener.providers.base import Fact
from screener.refresh import Refresher, adjustment_changed, merge_histories

from conftest import APPLE_CIK


def bars(rows):
    return pd.DataFrame(rows, columns=["date", "close", "adj_close", "dividend", "split"]).assign(
        open=1.0, high=1.0, low=1.0, volume=10)


STORED = pd.DataFrame({"date": ["2026-11-04", "2026-11-05", "2026-11-06"],
                       "close": [100.0, 101.0, 102.0], "adj_close": [99.0, 100.0, 101.0]})


def test_unchanged_history_is_appended():
    fresh = bars([("2026-11-04", 100.0, 99.0, 0, 0), ("2026-11-05", 101.0, 100.0, 0, 0),
                  ("2026-11-06", 102.5, 101.5, 0, 0),       # last stored day may differ (mid-session)
                  ("2026-11-09", 103.0, 102.0, 0, 0)])
    assert not adjustment_changed(STORED, fresh)


def test_dividend_or_split_forces_full_reload():
    paid = bars([("2026-11-04", 100.0, 99.0, 0, 0), ("2026-11-05", 101.0, 100.0, 0, 0),
                 ("2026-11-09", 103.0, 103.0, 0.5, 0)])
    assert adjustment_changed(STORED, paid)
    readjusted = bars([("2026-11-04", 100.0, 98.5, 0, 0), ("2026-11-05", 101.0, 99.5, 0, 0)])
    assert adjustment_changed(STORED, readjusted)
    split = bars([("2026-11-04", 50.0, 49.5, 0, 0), ("2026-11-05", 50.5, 50.0, 0, 0)])
    assert adjustment_changed(STORED, split)
    no_overlap = bars([("2026-11-09", 103.0, 102.0, 0, 0)])
    assert adjustment_changed(STORED, no_overlap)


class FakeSource(DataProvider):
    name = "fake"

    def __init__(self, apple_doc):
        self.doc = apple_doc
        self.facts_calls = 0
        self.accession = "A1"

    def universe_members(self, universe):
        return [Member("AAPL", "Apple", APPLE_CIK, "Tech", "Hardware", "1982-11-30"),
                Member("BAD", "Broken Co", 111, "Tech", "Hardware", None),
                Member("GOOD", "Fine Co", 222, "Energy", "Oil", None)]

    def profile(self, ticker):
        if ticker == "BAD":
            raise ProviderError("source is down for this one")
        return Profile(ticker, f"{ticker} Inc", "Tech", "Hardware", None, 1e9, "USD", "NMS", "EQUITY")

    def prices(self, tickers, start):
        frame = bars([("2026-11-06", 10.0, 9.0, 0, 0), ("2026-11-09", 11.0, 10.0, 0, 0)])
        return {t: frame for t in tickers if t != "BAD"}

    def filer_info(self, cik):
        return FilerInfo(cik, "x", "3571", "Electronic Computers", "0926", "2026-11-03", self.accession)

    def fundamentals(self, cik, offline=False):
        if cik != APPLE_CIK:
            raise ProviderError("HTTP 404")
        self.facts_calls += 1
        return parse_company_facts(self.doc)


@pytest.fixture
def job(cfg, conn, apple_doc):
    cfg.benchmarks = []
    source = FakeSource(apple_doc)
    roles = ["universe", "prices", "profile", "fundamentals"]
    return Refresher(cfg, conn, providers={r: source for r in roles}), source


def test_failed_tickers_are_logged_and_the_rest_continue(job, conn):
    refresher, _ = job
    results = refresher.run(["universe", "prices", "profile", "fundamentals"])
    assert (results["profile"].ok, results["profile"].failed) == (2, 1)
    assert (results["prices"].ok, results["prices"].failed) == (2, 1)
    assert (results["fundamentals"].ok, results["fundamentals"].failed) == (1, 2)
    errors = {(r["step"], r["key"]): r["error"] for r in
              conn.execute("SELECT step, key, error FROM refresh_log WHERE status='error'")}
    assert set(errors) == {("profile", "BAD"), ("prices", "BAD"), ("fundamentals", "BAD"),
                           ("fundamentals", "GOOD")}
    assert "source is down" in errors["profile", "BAD"]
    # nothing was invented for the failed ticker, and an unknown value stays NULL
    assert conn.execute("SELECT COUNT(*) FROM company_profile WHERE ticker='BAD'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM prices_daily WHERE ticker='BAD'").fetchone()[0] == 0
    assert conn.execute("SELECT market_cap FROM company_profile WHERE ticker='GOOD'").fetchone()[0] is None


def test_fresh_keys_are_skipped_and_failures_retried(job):
    refresher, _ = job
    refresher.run(["universe", "profile"])
    again = refresher.run(["universe", "profile"])
    assert (again["universe"].skipped, again["profile"].skipped, again["profile"].failed) == (1, 2, 1)
    forced = refresher.run(["profile"], force=True)
    assert (forced["profile"].ok, forced["profile"].failed) == (2, 1)


def test_fundamentals_downloaded_again_only_after_a_new_filing(job, cfg):
    refresher, source = job
    cfg.max_age_hours["fundamentals"] = 0          # always due for a check
    refresher.run(["universe", "fundamentals"], tickers=["AAPL"])
    refresher.run(["fundamentals"], tickers=["AAPL"])
    assert source.facts_calls == 1                 # same latest filing: no second download
    source.accession = "A2"
    refresher.run(["fundamentals"], tickers=["AAPL"])
    assert source.facts_calls == 2


def test_only_mapped_tags_are_stored(apple):
    tags = {r[0] for r in apple.execute("SELECT DISTINCT tag FROM fundamentals_facts")}
    assert "NetIncomeLoss" in tags and "EntityCommonStockSharesOutstanding" in tags
    meta = apple.execute("SELECT facts_total, facts_stored FROM fundamentals_meta").fetchone()
    assert meta["facts_stored"] == apple.execute("SELECT COUNT(*) FROM fundamentals_facts").fetchone()[0]


def test_removed_member_is_closed_not_deleted(job, conn):
    refresher, source = job
    refresher.run(["universe"])
    source.universe_members = lambda universe: [Member("AAPL", "Apple", APPLE_CIK, "Tech", "Hardware", None)]
    refresher.run(["universe"], force=True)
    rows = {r["ticker"]: r["removed_on"] for r in conn.execute("SELECT ticker, removed_on FROM universe_membership")}
    assert rows["AAPL"] is None and rows["GOOD"] is not None and rows["BAD"] is not None
    assert [r["ticker"] for r in refresher.members()] == ["AAPL"]


def test_edgar_refuses_to_run_without_contact_details(tmp_path):
    for bad in ("", "  ", "Jane Doe jane.doe@example.com"):
        with pytest.raises(ConfigError):
            Config(root=tmp_path, edgar_user_agent=bad).require_edgar_user_agent()
    assert Config(root=tmp_path, edgar_user_agent="Ana Silva ana@silva.pt").require_edgar_user_agent()


def test_freshness_window(conn):
    db.log_ok(conn, "prices", "AAPL")
    assert db.is_fresh(conn, "prices", "AAPL", 12)
    assert not db.is_fresh(conn, "prices", "AAPL", 0)
    assert not db.is_fresh(conn, "prices", "MSFT", 12)
    db.log_error(conn, "prices", "AAPL", "boom")
    assert not db.is_fresh(conn, "prices", "AAPL", 12)


def test_predecessor_registrant_history_is_merged(job, conn, monkeypatch):
    """A company that moved to a new SEC registrant keeps its earlier filings."""
    refresher, source = job
    monkeypatch.setattr("screener.refresh.predecessors", lambda cik: (APPLE_CIK,) if cik == 222 else ())
    asked = []
    original = source.fundamentals

    def fundamentals(cik, offline=False):
        asked.append(cik)
        if cik == 222:
            return iter(())               # the new registrant has filed nothing yet
        return original(cik, offline)

    source.fundamentals = fundamentals
    refresher.run(["universe", "fundamentals"], tickers=["GOOD"])
    assert asked == [222, APPLE_CIK]
    assert conn.execute("SELECT COUNT(*) FROM fundamentals_facts WHERE cik=222").fetchone()[0] > 100


def test_shipped_predecessor_table_loads():
    from screener.concepts import predecessors
    assert predecessors(2115436) == (34088,)       # ExxonMobil Holdings <- Exxon Mobil Corp
    assert predecessors(320193) == ()


def _fact(filed, form, value):
    return Fact("us-gaap", "Assets", "USD", "", "2018-12-31", value, None, None, form, filed, f"a-{filed}", None)


def test_predecessor_filings_after_the_handover_are_ignored():
    successor = [_fact("2019-01-10", "8-K", 1), _fact("2019-05-08", "10-Q", 2)]
    predecessor = [_fact("2018-11-20", "10-K", 3),
                   _fact("2019-02-01", "10-Q", 4),      # before the successor's first report: kept
                   _fact("2019-08-01", "10-Q", 5)]      # still filing as a subsidiary: dropped
    oldest = [_fact("2015-02-01", "10-K", 6), _fact("2018-12-01", "10-K", 7)]
    merged = merge_histories([successor, predecessor, oldest])
    assert sorted(f.value for f in merged) == [1, 2, 3, 4, 6]
    assert merge_histories([[], predecessor]) == predecessor
