"""Index membership over time: intervals from the change record, and the rule
that a wrong company is never counted as a member."""

import pandas as pd

from screener.analysis.membership import UNKNOWN, intervals, members_on


def _changes(rows):
    return pd.DataFrame(rows, columns=["date", "action", "ticker"])


def test_intervals_follow_the_record_and_the_current_list():
    changes = _changes([
        ("2015-03-01", "added", "NEW"),                         # joined, still in
        ("2012-06-01", "removed", "OLD"),                       # left, never seen joining
        ("2010-01-15", "added", "BRIEF"), ("2013-09-30", "removed", "BRIEF"),
        ("2016-01-01", "added", "BACK"), ("2018-01-01", "removed", "BACK"), ("2021-01-01", "added", "BACK"),
        ("2019-05-05", "added", "RENAMED"),                     # added, never removed, not current
        ("2020-02-02", "removed", "GLITCH"),                    # current, but the record shows a removal last
    ])
    table = intervals(["ALWAYS", "NEW", "BACK", "GLITCH"], changes)
    by = {(r.ticker, r.start): r.end for r in table.itertuples()}
    assert by[("ALWAYS", UNKNOWN)] == UNKNOWN
    assert by[("NEW", "2015-03-01")] == UNKNOWN
    assert by[("OLD", UNKNOWN)] == "2012-06-01"
    assert by[("BRIEF", "2010-01-15")] == "2013-09-30"
    assert by[("BACK", "2016-01-01")] == "2018-01-01" and by[("BACK", "2021-01-01")] == UNKNOWN
    assert by[("RENAMED", "2019-05-05")] == "2019-05-05"       # empty interval: never eligible
    assert by[("GLITCH", "2020-02-02")] == UNKNOWN              # member again from the odd removal

    assert members_on(table, "2011-01-01") == {"ALWAYS", "OLD", "BRIEF", "GLITCH"}
    assert members_on(table, "2012-06-01") == {"ALWAYS", "BRIEF", "GLITCH"}        # removal date exclusive
    assert members_on(table, "2017-01-01") == {"ALWAYS", "NEW", "BACK", "GLITCH"}
    assert members_on(table, "2019-06-01") == {"ALWAYS", "NEW", "GLITCH"}          # BACK out, RENAMED never in
    assert members_on(table, "2026-01-01") == {"ALWAYS", "NEW", "BACK", "GLITCH"}


def test_no_record_means_today_s_members_throughout():
    table = intervals(["B", "A"], _changes([]))
    assert table["ticker"].tolist() == ["A", "B"] and (table["start"] == UNKNOWN).all()
    assert members_on(table, "2001-01-01") == {"A", "B"}
