"""The refresh job: the only code that calls providers and writes the cache.

Each step works key by key (a ticker, a company, a factor file). A key that was
refreshed recently is skipped, a key that fails is logged in refresh_log and
the job carries on with the rest.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from screener import db
from screener.concepts import STORED_TAGS, predecessors
from screener.config import Config
from screener.fundamentals import STATEMENT_FORMS
from screener.providers import get_provider
from screener.providers.base import DataProvider, NotSupported

log = logging.getLogger("screener.refresh")

STEPS = ["universe", "factors", "fundamentals", "prices", "profile", "statements"]
PRICE_OVERLAP_DAYS = 10
ADJUSTMENT_TOLERANCE = 1e-4
REUSE_LEAD_DAYS = 30          # a former member's prices must begin this long before it left the index
REUSE_GAP_DAYS = 60           # a longer gap after the removal means the symbol now belongs to another company


def trim_former(frame: pd.DataFrame, removed_on: str) -> pd.DataFrame | None:
    """Prices of a company that left the index on `removed_on`, guarded against
    ticker reuse. None if the series begins after the removal (the symbol belongs
    to another company now); rows after the first long gap following the removal
    are dropped for the same reason. Nothing is filled in."""
    if frame.empty:
        return None
    dates = pd.to_datetime(frame["date"])
    removed = pd.Timestamp(removed_on)
    if dates.min() > removed - pd.Timedelta(days=REUSE_LEAD_DAYS):
        return None
    after = dates[dates >= removed]
    if len(after) > 1:
        breaks = after[after.diff().dt.days > REUSE_GAP_DAYS]
        if len(breaks):
            return frame[dates < breaks.iloc[0]].reset_index(drop=True)
    return frame


@dataclass
class StepResult:
    ok: int = 0
    skipped: int = 0
    failed: int = 0

    def __str__(self) -> str:
        return f"{self.ok} updated, {self.skipped} fresh/skipped, {self.failed} failed"


def adjustment_changed(stored: pd.DataFrame, fresh: pd.DataFrame) -> bool:
    """True if history already in the cache no longer matches the source.

    Yahoo rewrites adjusted prices after each dividend and split, so appending
    new days to old adjusted history would corrupt returns. `stored` and `fresh`
    hold date, close, adj_close (fresh also dividend, split). The newest stored
    day is not compared because it may have been captured mid-session.
    """
    if stored.empty:
        return False
    last = stored["date"].max()
    newer = fresh[fresh["date"] > last]
    if ((newer["dividend"].fillna(0) != 0) | (newer["split"].fillna(0) != 0)).any():
        return True
    both = stored[stored["date"] < last].merge(fresh, on="date", suffixes=("_old", "_new"))
    if both.empty:
        return True     # nothing to compare against: reload rather than assume
    for column in ("close", "adj_close"):
        old, new = both[f"{column}_old"], both[f"{column}_new"]
        if ((old - new).abs() > ADJUSTMENT_TOLERANCE * old.abs()).any():
            return True
    return False


def merge_histories(histories: list[list]) -> list:
    """Join a company's filed facts with those of its predecessor registrants.

    histories[0] belongs to the current registrant, the rest to predecessors,
    newest first. A predecessor often keeps filing as a subsidiary after the
    hand-over, with different figures for the same periods, so only what it
    filed before the successor's first periodic report is taken.
    """
    merged = list(histories[0])
    for older in histories[1:]:
        reports = [f.filed for f in merged if f.form in STATEMENT_FORMS]
        cutoff = min(reports) if reports else None
        merged += [f for f in older if cutoff is None or f.filed < cutoff]
    return merged


def _cell(value):
    return None if pd.isna(value) else value


class Refresher:
    def __init__(self, cfg: Config, conn: sqlite3.Connection,
                 providers: dict[str, DataProvider] | None = None):
        self.cfg = cfg
        self.conn = conn
        self._by_role = dict(providers or {})
        self._by_name: dict[str, DataProvider] = {}

    def provider(self, role: str) -> DataProvider:
        if role not in self._by_role:
            name = self.cfg.sources.get(role)
            if name not in self._by_name:
                self._by_name[name] = get_provider(self.cfg, role)
            self._by_role[role] = self._by_name[name]
        return self._by_role[role]

    # ------------------------------------------------------------------ helpers
    def _fresh(self, step: str, key: str, force: bool) -> bool:
        return not force and db.is_fresh(self.conn, step, key, self.cfg.max_age_hours[step])

    def _fail(self, step: str, key: str, exc: Exception, result: StepResult) -> None:
        message = f"{type(exc).__name__}: {exc}"
        log.warning("%s %s failed: %s", step, key, message)
        db.log_error(self.conn, step, key, message)
        result.failed += 1

    def members(self, tickers: list[str] | None = None, former: bool = False) -> list[sqlite3.Row]:
        """Current members; with `former`, also companies that left the index since
        price_start (the backtest wants their prices and filed fundamentals)."""
        sql = ("SELECT ticker, cik, removed_on FROM universe_membership WHERE universe=? "
               "AND (removed_on IS NULL" + (" OR removed_on>=?" if former else "") + ") ORDER BY ticker")
        args = (self.cfg.universe, self.cfg.price_start) if former else (self.cfg.universe,)
        rows = self.conn.execute(sql, args).fetchall()
        if tickers is not None:
            wanted = set(tickers)
            rows = [r for r in rows if r["ticker"] in wanted]
        return rows

    def run(self, steps: list[str], tickers: list[str] | None = None,
            force: bool = False) -> dict[str, StepResult]:
        results = {}
        for step in STEPS:
            if step not in steps:
                continue
            log.info("step %s: starting", step)
            try:
                results[step] = getattr(self, f"step_{step}")(tickers, force)
            except Exception as exc:  # e.g. provider cannot be set up
                results[step] = StepResult()
                self._fail(step, "(step)", exc, results[step])
            else:
                self.conn.execute("DELETE FROM refresh_log WHERE step=? AND key='(step)'", (step,))
                self.conn.commit()
            log.info("step %s: %s", step, results[step])
        return results

    # ----------------------------------------------------------------- universe
    def step_universe(self, tickers, force) -> StepResult:
        result = StepResult()
        universe = self.cfg.universe
        if self._fresh("universe", universe, force):
            result.skipped += 1
            return result
        provider = self.provider("universe")
        try:
            members = provider.universe_members(universe)
            now, today = db.now_utc(), date.today().isoformat()
            self.conn.executemany(
                "INSERT INTO universe_membership(universe,ticker,cik,name,gics_sector,"
                "gics_sub_industry,date_added,first_seen,removed_on,source,fetched_at) "
                "VALUES(?,?,?,?,?,?,?,?,NULL,?,?) ON CONFLICT(universe,ticker) DO UPDATE SET "
                "cik=excluded.cik,name=excluded.name,gics_sector=excluded.gics_sector,"
                "gics_sub_industry=excluded.gics_sub_industry,date_added=excluded.date_added,"
                "removed_on=NULL,source=excluded.source,fetched_at=excluded.fetched_at",
                [(universe, m.ticker, m.cik, m.name, m.sector, m.sub_industry, m.date_added,
                  today, provider.name, now) for m in members])
            current = {m.ticker for m in members}
            gone = [r["ticker"] for r in self.conn.execute(
                "SELECT ticker FROM universe_membership WHERE universe=? AND removed_on IS NULL",
                (universe,)) if r["ticker"] not in current]
            self.conn.executemany(
                "UPDATE universe_membership SET removed_on=? WHERE universe=? AND ticker=?",
                [(today, universe, t) for t in gone])
            recorded = self._store_changes(universe, provider, current, today)
            db.log_ok(self.conn, "universe", universe,
                      f"{len(members)} members, {len(gone)} newly removed, {recorded} recorded changes")
            result.ok += 1
        except Exception as exc:
            self._fail("universe", universe, exc, result)
        return result

    def _store_changes(self, universe: str, provider: DataProvider, current: set[str], today: str) -> int:
        """Keep the source's record of additions and removals, and give every company
        that left the index since price_start a membership row with its removal date,
        so the other steps fetch its prices and (if the SEC still lists it) its filings."""
        try:
            changes = provider.universe_changes(universe)
        except NotSupported:
            return 0
        now = db.now_utc()
        self.conn.execute("DELETE FROM universe_changes WHERE universe=?", (universe,))
        self.conn.executemany(
            "INSERT OR REPLACE INTO universe_changes(universe,date,action,ticker,name,reason,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [(universe, c.date, c.action, c.ticker, c.name, c.reason, provider.name, now) for c in changes])
        by_ticker: dict[str, list] = {}
        for c in changes:
            by_ticker.setdefault(c.ticker, []).append(c)
        ciks = self._ticker_ciks()
        rows = []
        for ticker, events in by_ticker.items():
            removals = [e for e in events if e.action == "removed"]
            if ticker in current or not removals:
                continue
            last = max(removals, key=lambda e: e.date)
            if last.date < self.cfg.price_start:
                continue
            added = [e.date for e in events if e.action == "added" and e.date < last.date]
            rows.append((universe, ticker, ciks.get(ticker), last.name, max(added) if added else None,
                         today, last.date, provider.name, now))
        self.conn.executemany(
            "INSERT INTO universe_membership(universe,ticker,cik,name,gics_sector,gics_sub_industry,"
            "date_added,first_seen,removed_on,source,fetched_at) VALUES(?,?,?,?,NULL,NULL,?,?,?,?,?) "
            "ON CONFLICT(universe,ticker) DO UPDATE SET "
            "cik=COALESCE(universe_membership.cik,excluded.cik),name=COALESCE(universe_membership.name,excluded.name),"
            "date_added=COALESCE(universe_membership.date_added,excluded.date_added),"
            "removed_on=excluded.removed_on,fetched_at=excluded.fetched_at "
            "WHERE universe_membership.removed_on IS NOT NULL", rows)
        return len(changes)

    def _ticker_ciks(self) -> dict[str, int]:
        try:
            return self.provider("fundamentals").ticker_ciks()
        except NotSupported:
            return {}
        except Exception as exc:          # e.g. no EDGAR contact line configured, or the SEC is down
            log.warning("ticker to CIK lookup unavailable, former members get no filings: %s", exc)
            return {}

    # ------------------------------------------------------------------ factors
    def step_factors(self, tickers, force) -> StepResult:
        result = StepResult()
        provider = self.provider("factors")
        for dataset, freq in provider.factor_datasets():
            key = f"{dataset}/{freq}"
            if self._fresh("factors", key, force):
                result.skipped += 1
                continue
            try:
                series = provider.factor_returns(dataset, freq)
                dates = [r[0] for r in series.rows]
                self.conn.execute("DELETE FROM factor_returns WHERE dataset=? AND freq=?", (dataset, freq))
                self.conn.executemany(
                    "INSERT INTO factor_returns(dataset,freq,date,factor,value_pct) VALUES(?,?,?,?,?)",
                    [(dataset, freq, *r) for r in series.rows])
                self.conn.execute(
                    "INSERT OR REPLACE INTO factor_meta(dataset,freq,source,fetched_at,first_date,"
                    "last_date,rows) VALUES(?,?,?,?,?,?,?)",
                    (dataset, freq, provider.name, db.now_utc(), min(dates), max(dates), len(dates)))
                db.log_ok(self.conn, "factors", key, f"{len(dates)} values to {max(dates)}")
                result.ok += 1
            except Exception as exc:
                self._fail("factors", key, exc, result)
        return result

    # ------------------------------------------------------------- fundamentals
    def store_facts(self, cik: int, facts, source: str) -> tuple[int, int]:
        total, rows = 0, []
        for f in facts:
            total += 1
            if (f.taxonomy, f.tag) in STORED_TAGS:
                rows.append((cik, f.taxonomy, f.tag, f.unit, f.period_start, f.period_end, f.value,
                             f.fy, f.fp, f.form, f.filed, f.accession, f.frame))
        self.conn.execute("DELETE FROM fundamentals_facts WHERE cik=?", (cik,))
        self.conn.executemany(
            "INSERT OR REPLACE INTO fundamentals_facts(cik,taxonomy,tag,unit,period_start,"
            "period_end,value,fy,fp,form,filed,accession,frame) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.conn.execute(
            "INSERT OR REPLACE INTO fundamentals_meta(cik,source,fetched_at,facts_total,facts_stored) "
            "VALUES(?,?,?,?,?)", (cik, source, db.now_utc(), total, len(rows)))
        return total, len(rows)

    def step_fundamentals(self, tickers, force) -> StepResult:
        result = StepResult()
        provider = self.provider("fundamentals")
        companies: dict[int, str] = {}
        for row in self.members(tickers, former=True):
            if row["cik"] is None:
                if row["removed_on"]:
                    result.skipped += 1          # left the index and the SEC no longer lists it: nothing to fetch
                else:
                    self._fail("fundamentals", row["ticker"], ValueError("no CIK known for ticker"), result)
            else:
                companies.setdefault(row["cik"], row["ticker"])
        for n, (cik, key) in enumerate(companies.items(), 1):
            if n % 50 == 0:
                log.info("fundamentals: %d of %d companies", n, len(companies))
            if self._fresh("fundamentals", key, force):
                result.skipped += 1
                continue
            try:
                before = self.conn.execute(
                    "SELECT f.latest_report_accession AS accn, l.status FROM filer_info f "
                    "JOIN fundamentals_meta m ON m.cik=f.cik "
                    "LEFT JOIN refresh_log l ON l.step='fundamentals' AND l.key=? WHERE f.cik=?",
                    (key, cik)).fetchone()
                info = provider.filer_info(cik)
                self.conn.execute(
                    "INSERT OR REPLACE INTO filer_info(cik,name,sic,sic_description,fiscal_year_end,"
                    "latest_report_filed,latest_report_accession,source,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (cik, info.name, info.sic, info.sic_description, info.fiscal_year_end,
                     info.latest_report_filed, info.latest_report_accession, provider.name, db.now_utc()))
                unchanged = (not force and before is not None and before["status"] == "ok"
                             and before["accn"] == info.latest_report_accession)
                if unchanged:
                    db.log_ok(self.conn, "fundamentals", key,
                              f"no new report since {info.latest_report_filed}")
                    result.skipped += 1
                    continue
                facts = merge_histories([list(provider.fundamentals(c)) for c in (cik, *predecessors(cik))])
                total, stored = self.store_facts(cik, facts, provider.name)
                db.log_ok(self.conn, "fundamentals", key,
                          f"{stored} of {total} facts kept; latest report {info.latest_report_filed}")
                result.ok += 1
            except Exception as exc:
                self._fail("fundamentals", key, exc, result)
        return result

    def rebuild_facts(self, provider: DataProvider) -> StepResult:
        """Re-apply the tag mapping to the raw files on disk, without any download."""
        result = StepResult()
        for row in self.conn.execute("SELECT cik FROM fundamentals_meta").fetchall():
            try:
                cik = row["cik"]
                facts = merge_histories([list(provider.fundamentals(c, offline=True))
                                         for c in (cik, *predecessors(cik))])
                self.store_facts(cik, facts, provider.name)
                self.conn.commit()
                result.ok += 1
            except Exception as exc:
                self.conn.rollback()
                log.warning("rebuild CIK %s failed: %s", row["cik"], exc)
                result.failed += 1
        return result

    # ------------------------------------------------------------------- prices
    def _write_prices(self, ticker: str, frame: pd.DataFrame, source: str, replace: bool) -> None:
        if replace:
            self.conn.execute("DELETE FROM prices_daily WHERE ticker=?", (ticker,))
        self.conn.executemany(
            "INSERT OR REPLACE INTO prices_daily(ticker,date,open,high,low,close,adj_close,volume,"
            "dividend,split) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(ticker, r.date, _cell(r.open), _cell(r.high), _cell(r.low), _cell(r.close),
              _cell(r.adj_close), None if pd.isna(r.volume) else int(r.volume),
              _cell(r.dividend), _cell(r.split)) for r in frame.itertuples(index=False)])
        self.conn.execute(
            "INSERT INTO price_series_meta(ticker,source,fetched_at,first_date,last_date,rows,full_refetches) "
            "SELECT ?,?,?,MIN(date),MAX(date),COUNT(*),0 FROM prices_daily WHERE ticker=? "
            "ON CONFLICT(ticker) DO UPDATE SET source=excluded.source,fetched_at=excluded.fetched_at,"
            "first_date=excluded.first_date,last_date=excluded.last_date,rows=excluded.rows,"
            "full_refetches=full_refetches+?",
            (ticker, source, db.now_utc(), ticker, 1 if replace else 0))

    def _price_batches(self, tickers: list[str], start: str, result: StepResult, former: dict[str, str]):
        """Yield (ticker, frame) for each ticker with data; log the ones without. A
        former member with no data at the source is expected (delisted), not a failure."""
        provider = self.provider("prices")
        size = self.cfg.yahoo_price_batch
        for i in range(0, len(tickers), size):
            batch = tickers[i:i + size]
            log.info("prices: tickers %d-%d of %d from %s", i + 1, i + len(batch), len(tickers), start)
            try:
                frames = provider.prices(batch, start)
            except Exception as exc:
                for ticker in batch:
                    self._fail("prices", ticker, exc, result)
                continue
            for ticker in batch:
                if ticker in frames:
                    yield ticker, frames[ticker]
                elif ticker in former:
                    db.log_ok(self.conn, "prices", ticker,
                              f"no price data at source; left the index on {former[ticker]}, probably delisted")
                    result.skipped += 1
                else:
                    self._fail("prices", ticker, ValueError("source returned no price rows"), result)

    def step_prices(self, tickers, force) -> StepResult:
        result = StepResult()
        source = self.provider("prices").name
        rows = self.members(tickers, former=True)
        former = {r["ticker"]: r["removed_on"] for r in rows if r["removed_on"]}
        wanted = [r["ticker"] for r in rows]
        wanted += [b for b in self.cfg.benchmarks if tickers is None or b in tickers]
        due = []
        for ticker in wanted:
            if self._fresh("prices", ticker, force):
                result.skipped += 1
            else:
                due.append(ticker)
        last = {r["ticker"]: r["last_date"] for r in self.conn.execute(
            "SELECT ticker, last_date FROM price_series_meta WHERE last_date IS NOT NULL")}
        full = [t for t in due if t not in last or force]
        incremental = [t for t in due if t not in full]

        if incremental:
            oldest = min(last[t] for t in incremental)
            start = (date.fromisoformat(oldest) - timedelta(days=PRICE_OVERLAP_DAYS)).isoformat()
            for ticker, frame in self._price_batches(incremental, start, result, former):
                try:
                    stored = pd.read_sql_query(
                        "SELECT date, close, adj_close FROM prices_daily WHERE ticker=? AND date>=?",
                        self.conn, params=(ticker, start))
                    if ticker in former and stored.empty:
                        # Nothing stored in the overlap window: the data resumed after a gap,
                        # which for a company that left the index means the symbol was reused.
                        db.log_ok(self.conn, "prices", ticker, f"no new data since {last[ticker]}; "
                                  "later rows belong to another company (symbol reused)")
                        result.skipped += 1
                        continue
                    if adjustment_changed(stored, frame):
                        log.info("prices: %s history was re-adjusted at source, reloading in full", ticker)
                        full.append(ticker)
                        continue
                    self._write_prices(ticker, frame, source, replace=False)
                    db.log_ok(self.conn, "prices", ticker, f"appended to {frame['date'].max()}")
                    result.ok += 1
                except Exception as exc:
                    self._fail("prices", ticker, exc, result)

        for ticker, frame in self._price_batches(full, self.cfg.price_start, result, former):
            try:
                if ticker in former:
                    frame = trim_former(frame, former[ticker])
                    if frame is None:
                        db.log_ok(self.conn, "prices", ticker, f"price history at source does not predate its removal "
                                  f"on {former[ticker]} (a stale quote after delisting, or the symbol reused by "
                                  f"another company); not stored")
                        result.skipped += 1
                        continue
                self._write_prices(ticker, frame, source, replace=True)
                db.log_ok(self.conn, "prices", ticker,
                          f"full history {frame['date'].min()} to {frame['date'].max()}")
                result.ok += 1
            except Exception as exc:
                self._fail("prices", ticker, exc, result)
        return result

    # ------------------------------------------------------- profile, statements
    def step_profile(self, tickers, force) -> StepResult:
        result = StepResult()
        provider = self.provider("profile")
        rows = self.members(tickers)
        for n, row in enumerate(rows, 1):
            ticker = row["ticker"]
            if n % 50 == 0:
                log.info("profile: %d of %d", n, len(rows))
            if self._fresh("profile", ticker, force):
                result.skipped += 1
                continue
            try:
                p = provider.profile(ticker)
                self.conn.execute(
                    "INSERT OR REPLACE INTO company_profile(ticker,name,sector,industry,market_cap,"
                    "shares_outstanding,currency,exchange,quote_type,source,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (ticker, p.name, p.sector, p.industry, p.market_cap, p.shares_outstanding,
                     p.currency, p.exchange, p.quote_type, provider.name, db.now_utc()))
                db.log_ok(self.conn, "profile", ticker)
                result.ok += 1
            except Exception as exc:
                self._fail("profile", ticker, exc, result)
        return result

    def step_statements(self, tickers, force) -> StepResult:
        result = StepResult()
        provider = self.provider("statements")
        rows = self.members(tickers)
        for n, row in enumerate(rows, 1):
            ticker = row["ticker"]
            if n % 25 == 0:
                log.info("statements: %d of %d", n, len(rows))
            if self._fresh("statements", ticker, force):
                result.skipped += 1
                continue
            try:
                items = provider.statements(ticker)
                now = db.now_utc()
                self.conn.execute("DELETE FROM statement_items WHERE ticker=?", (ticker,))
                self.conn.executemany(
                    "INSERT OR REPLACE INTO statement_items(ticker,statement,freq,period_end,item,"
                    "value,source,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
                    [(ticker, i.statement, i.freq, i.period_end, i.item, i.value, provider.name, now)
                     for i in items])
                db.log_ok(self.conn, "statements", ticker, f"{len(items)} values")
                result.ok += 1
            except Exception as exc:
                self._fail("statements", ticker, exc, result)
        return result
