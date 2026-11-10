"""Command line: refresh the cache and inspect what is in it."""

from __future__ import annotations

import argparse
import logging
import re
import sys

import pandas as pd

from screener import db
from screener.config import ConfigError, load_config

SHOW_CONCEPTS = ["revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
                 "total_assets", "total_liabilities", "equity", "cfo", "capex"]
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
FILING_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K"


def fmt_amount(value, unit: str = "USD") -> str:
    """Money in millions; per-share and share counts as they are; missing as a dash."""
    if value is None or pd.isna(value):
        return "—"
    if unit == "USD":
        return f"{value / 1e6:,.0f}"
    if unit == "shares":
        return f"{value / 1e6:,.1f}"
    return f"{value:,.2f}"


def fmt_pct(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value * 100:+.2f}%"


def _table(rows: list[list[str]], header: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    numeric = [i > 0 and all(not str(r[i]).strip("—") or str(r[i])[-1].isdigit() or str(r[i])[-1] == "%"
                             for r in rows) and not all(_DATE.match(str(r[i])) for r in rows)
               for i in range(len(header))]
    line = lambda r: "  ".join(str(c).rjust(w) if numeric[i] else str(c).ljust(w)
                               for i, (c, w) in enumerate(zip(r, widths))).rstrip()
    return "\n".join([line(header), "  ".join("-" * w for w in widths), *map(line, rows)])


def _setup_logging(cfg) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger("screener")
    root.setLevel(logging.INFO)
    for handler in (logging.StreamHandler(sys.stderr), logging.FileHandler(cfg.log_dir / "refresh.log")):
        handler.setFormatter(fmt)
        root.addHandler(handler)


# ------------------------------------------------------------------ commands
def cmd_refresh(cfg, args) -> int:
    from screener.refresh import STEPS, Refresher

    steps = args.only.split(",") if args.only else STEPS
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        print(f"Unknown step(s) {unknown}. Choose from: {', '.join(STEPS)}")
        return 2
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else None
    _setup_logging(cfg)
    conn = db.connect(cfg.db_path)
    results = Refresher(cfg, conn).run(steps, tickers, args.force)
    print("\nRefresh finished:")
    for step, result in results.items():
        print(f"  {step:<13}{result}")
    failed = sum(r.failed for r in results.values())
    if failed:
        print(f"\n{failed} failure(s). Run `screener status --failures` to list them.")
    if not args.no_compute:
        from screener.analysis import compute

        summary = compute.run(conn, cfg.universe)
        print(f"Scores recomputed as of {summary['as_of']} ({summary['seconds']}s).")
    return 0


def cmd_compute(cfg, args) -> int:
    from screener.analysis import compute

    _setup_logging(cfg)
    conn = db.connect(cfg.db_path)
    summary = compute.run(conn, cfg.universe)
    print(f"Scores computed for {summary['snapshot_rows']} tickers as of {summary['as_of']} "
          f"({summary['history_rows']:,} company-years, {summary['seconds']}s).")
    return 0


def cmd_rebuild_facts(cfg, args) -> int:
    from screener.providers.edgar import EdgarOfflineProvider
    from screener.refresh import Refresher

    _setup_logging(cfg)
    conn = db.connect(cfg.db_path)
    result = Refresher(cfg, conn).rebuild_facts(EdgarOfflineProvider(cfg))
    print(f"Rebuilt facts from raw files: {result.ok} companies, {result.failed} failed.")
    return 0


def cmd_status(cfg, args) -> int:
    if not cfg.db_path.exists():
        print("The cache is empty. Run `screener refresh` first.")
        return 1
    conn = db.connect(cfg.db_path, read_only=True)
    one = lambda sql, *a: conn.execute(sql, a).fetchone()
    members = one("SELECT COUNT(*) n, COUNT(DISTINCT cik) c, MAX(fetched_at) f FROM universe_membership "
                  "WHERE universe=? AND removed_on IS NULL", cfg.universe)
    print(f"Cache: {cfg.db_path}")
    print(f"Universe {cfg.universe}: {members['n']} tickers, {members['c']} companies "
          f"(list fetched {members['f'] or 'never'})\n")
    rows = []
    for step, table, extra in [
        ("prices", "price_series_meta", "MIN(first_date)||' to '||MAX(last_date)"),
        ("profile", "company_profile", "''"),
        ("statements", "(SELECT ticker, MAX(fetched_at) fetched_at FROM statement_items GROUP BY ticker)", "''"),
        ("fundamentals", "fundamentals_meta", "''"),
        ("factors", "factor_meta", "MIN(first_date)||' to '||MAX(last_date)"),
    ]:
        r = one(f"SELECT COUNT(*) n, MIN(fetched_at) oldest, MAX(fetched_at) newest, {extra} span FROM {table}")
        errors = one("SELECT COUNT(*) n FROM refresh_log WHERE step=? AND status='error'", step)["n"]
        rows.append([step, r["n"], r["oldest"] or "—", r["newest"] or "—", errors, r["span"] or ""])
    print(_table(rows, ["data", "series", "oldest fetch (UTC)", "newest fetch (UTC)", "failing", "covers"]))
    counts = one("SELECT (SELECT COUNT(*) FROM prices_daily) p, (SELECT COUNT(*) FROM fundamentals_facts) f, "
                 "(SELECT COUNT(*) FROM statement_items) s, (SELECT COUNT(*) FROM factor_returns) r")
    print(f"\nRows: {counts['p']:,} daily prices, {counts['f']:,} filed facts, "
          f"{counts['s']:,} provider statement values, {counts['r']:,} factor returns")
    failures = conn.execute("SELECT step, key, last_attempt, last_success, error FROM refresh_log "
                            "WHERE status='error' ORDER BY step, key").fetchall()
    if failures and args.failures:
        print("\nFailures:")
        print(_table([[f["step"], f["key"], f["last_attempt"], f["last_success"] or "never",
                       (f["error"] or "")[:90]] for f in failures],
                     ["step", "key", "last attempt", "last success", "error"]))
    elif failures:
        print(f"\n{len(failures)} key(s) failing; add --failures to list them.")
    return 0


def cmd_show(cfg, args) -> int:
    from screener.checks import compare
    from screener.concepts import CONCEPTS
    from screener.fundamentals import annual_series, quarterly_series

    conn = db.connect(cfg.db_path, read_only=True)
    ticker = args.ticker.upper().replace(".", "-")
    member = conn.execute("SELECT * FROM universe_membership WHERE universe=? AND ticker=?",
                          (cfg.universe, ticker)).fetchone()
    if member is None:
        print(f"{ticker} is not in the cached {cfg.universe} universe.")
        return 1
    cik = member["cik"]
    profile = conn.execute("SELECT * FROM company_profile WHERE ticker=?", (ticker,)).fetchone()
    filer = conn.execute("SELECT * FROM filer_info WHERE cik=?", (cik,)).fetchone()
    val = lambda row, col: "—" if row is None or row[col] is None else row[col]

    print(f"\n{ticker}  {member['name']}   CIK {cik}")
    print(f"  GICS (Wikipedia): {val(member, 'gics_sector')} / {val(member, 'gics_sub_industry')}")
    print(f"  Yahoo:            {val(profile, 'sector')} / {val(profile, 'industry')}"
          f"   [fetched {val(profile, 'fetched_at')}]")
    print(f"  SEC:              SIC {val(filer, 'sic')} {val(filer, 'sic_description')}, fiscal year end "
          f"{val(filer, 'fiscal_year_end')} (MMDD), latest report filed {val(filer, 'latest_report_filed')}")
    if profile is not None:
        cap, shares = profile["market_cap"], profile["shares_outstanding"]
        print(f"  Market cap (Yahoo): {'—' if cap is None else f'${cap / 1e9:,.1f}bn'}"
              f"   shares outstanding: {'—' if shares is None else f'{shares / 1e6:,.1f}m'}")

    meta = conn.execute("SELECT * FROM price_series_meta WHERE ticker=?", (ticker,)).fetchone()
    if meta is None:
        print("\nPrices: none cached")
    else:
        print(f"\nPrices: {meta['rows']:,} days, {meta['first_date']} to {meta['last_date']}"
              f"   [fetched {meta['fetched_at']}]")
        recent = conn.execute("SELECT date, close, adj_close, volume FROM prices_daily WHERE ticker=? "
                              "ORDER BY date DESC LIMIT 3", (ticker,)).fetchall()
        print(_table([[r["date"], f"{r['close']:,.2f}", f"{r['adj_close']:,.2f}", f"{r['volume']:,}"]
                      for r in recent], ["date", "close", "adj close", "volume"]))

    fmeta = conn.execute("SELECT * FROM fundamentals_meta WHERE cik=?", (cik,)).fetchone()
    if fmeta is None:
        print("\nFiled fundamentals: none cached")
        return 0
    print(f"\nFiled fundamentals (SEC EDGAR), fiscal years. USD millions except EPS."
          f"   [fetched {fmeta['fetched_at']}]")
    series = {c: annual_series(conn, cik, c).tail(args.years) for c in SHOW_CONCEPTS}
    ends = sorted({e for s in series.values() for e in s["period_end"]})[-args.years:]
    rows = []
    for c in SHOW_CONCEPTS:
        by_end = series[c].set_index("period_end")["value"]
        rows.append([CONCEPTS[c].label, *[fmt_amount(by_end.get(e), CONCEPTS[c].unit) for e in ends]])
    print(_table(rows, ["fiscal year ending", *ends]))

    print("\nWhere the latest year's figures come from:")
    rows = []
    for c in SHOW_CONCEPTS:
        s = series[c]
        if s.empty:
            rows.append([CONCEPTS[c].label, "—", "no value under any mapped tag", "", "", ""])
            continue
        r = s.iloc[-1]
        rows.append([CONCEPTS[c].label, r["period_end"], r["tag"], r["form"], r["filed"], r["accession"]])
    print(_table(rows, ["concept", "period end", "XBRL tag", "form", "filed", "accession no."]))
    print(f"  Filings: {FILING_URL.format(cik=cik)}")

    q = quarterly_series(conn, cik, "net_income").tail(5)
    if not q.empty:
        print("\nNet income by quarter, USD millions (derived = year-to-date difference, not reported directly):")
        print(_table([[r.period_end, fmt_amount(r.value), "derived" if r.derived else "reported",
                       r.first_filed] for r in q.itertuples(index=False)],
                     ["quarter ending", "net income", "basis", "known since"]))

    cmp = compare(conn, ticker, cik, years=2)
    if cmp["provider"].notna().any():
        print("\nCross-check against Yahoo (latest two fiscal years, USD millions):")
        print(_table([[CONCEPTS[r.concept].label, r.period_end, fmt_amount(r.edgar), fmt_amount(r.provider),
                       fmt_pct(r.diff_pct)] for r in cmp.itertuples(index=False)],
                     ["concept", "period end", "EDGAR", "Yahoo", "difference"]))
    else:
        print("\nCross-check: no Yahoo statements cached for this ticker.")
    return 0


def cmd_crosscheck(cfg, args) -> int:
    from screener.checks import MATCH_TOLERANCE, universe_summary

    conn = db.connect(cfg.db_path, read_only=True)
    summary = universe_summary(conn, cfg.universe)
    print(f"Latest fiscal year, EDGAR vs Yahoo, {cfg.universe}. Match = within {MATCH_TOLERANCE:.1%}.\n")
    print(_table(summary[["concept", "match", "mismatch", "edgar_missing", "provider_missing"]].values.tolist(),
                 ["concept", "match", "mismatch", "missing in EDGAR", "missing in Yahoo"]))
    if args.tickers:
        for r in summary.itertuples(index=False):
            print(f"\n{r.concept}\n  mismatch: {r.mismatch_tickers or '—'}\n  missing in EDGAR: {r.edgar_missing_tickers or '—'}")
    return 0


def cmd_coverage(cfg, args) -> int:
    from screener.checks import concept_gaps, short_histories
    from screener.concepts import predecessors

    conn = db.connect(cfg.db_path, read_only=True)
    late = short_histories(conn, cfg.universe)
    print(f"{len(late)} companies whose filed fundamentals start well after their price history.\n"
          "Earlier filings are probably under a predecessor SEC registrant; see "
          "src/screener/reference/cik_predecessors.toml.\n")
    print(_table([[r.ticker, (r.name or "")[:34], r.cik, "—" if pd.isna(r.price_start) else r.price_start,
                   "none" if pd.isna(r.first_filed) else r.first_filed,
                   "yes" if predecessors(int(r.cik)) else ""] for r in late.itertuples(index=False)],
                 ["ticker", "name", "CIK", "prices from", "filings from", "predecessor mapped"]))

    gaps = concept_gaps(conn, cfg.universe)
    print("\nFiscal-year values per concept under the current tag mapping (companies):")
    print(_table(gaps[["concept", "current", "outdated", "none"]].values.tolist(),
                 ["concept", "current", "outdated", "none"]))
    if args.tickers:
        for r in gaps.itertuples(index=False):
            if r.outdated_tickers or r.none_tickers:
                print(f"\n{r.concept}\n  outdated: {r.outdated_tickers or '—'}\n  none: {r.none_tickers or '—'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="screener", description="Personal stock screener")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("refresh", help="update the local cache from the data sources")
    p.add_argument("--only", help="comma-separated steps: universe,factors,fundamentals,prices,profile,statements")
    p.add_argument("--tickers", help="comma-separated tickers to limit the run to")
    p.add_argument("--force", action="store_true", help="ignore freshness and reload")
    p.add_argument("--no-compute", action="store_true", help="do not recompute scores afterwards")
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser("compute", help="recompute scores and ranks from the cache (no download)")
    p.set_defaults(fn=cmd_compute)

    p = sub.add_parser("status", help="show what is cached and how fresh it is")
    p.add_argument("--failures", action="store_true", help="list every failing key")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("show", help="print cached figures for one company")
    p.add_argument("ticker")
    p.add_argument("--years", type=int, default=4)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("crosscheck", help="compare EDGAR and Yahoo figures across the universe")
    p.add_argument("--tickers", action="store_true", help="list example tickers per category")
    p.set_defaults(fn=cmd_crosscheck)

    p = sub.add_parser("coverage", help="list companies with suspiciously short filing history")
    p.add_argument("--tickers", action="store_true", help="list the tickers behind each gap")
    p.set_defaults(fn=cmd_coverage)

    p = sub.add_parser("rebuild-facts", help="re-apply the tag mapping to raw EDGAR files (no download)")
    p.set_defaults(fn=cmd_rebuild_facts)

    args = parser.parse_args(argv)
    try:
        return args.fn(load_config(), args)
    except ConfigError as exc:
        print(f"Configuration problem: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
