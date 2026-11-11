# Stock screener

A personal screener for US stocks: price behaviour, fundamentals, research-backed
scores and an honest backtest, on free data, running locally.

**Status: milestone 4 of 6 — data layer, scores, screener, stock detail and market overview.**
See [CHANGELOG.md](CHANGELOG.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) (it installs and pins Python 3.13 for this project).

```sh
uv sync                               # install Python dependencies
cp config.example.toml config.toml    # then edit config.toml
npm --prefix frontend install         # once: frontend dependencies (needs Node 20+)
npm --prefix frontend run build       # build the web app into src/screener/web
```

In `config.toml`, set `[edgar] user_agent` to your name and email, for example
`"Jane Doe jane.doe@example.com"`. The SEC requires automated clients to identify
themselves; the EDGAR refresh refuses to run while the field is empty.
`config.toml` and the `data/` folder are git-ignored.

## Run

```sh
uv run screener serve                 # start the app and open it in the browser
uv run screener refresh               # update the cache (first run: about 40 minutes)
uv run screener compute               # recompute scores from the cache (refresh does this at the end)
uv run screener status                # what is cached, how fresh, what is failing
uv run screener status --failures     # list every failing ticker with its error
uv run screener show AAPL             # cached figures for one company, with filing references
uv run screener crosscheck            # EDGAR vs Yahoo agreement across the universe
uv run screener coverage              # companies whose filed history looks too short
uv run pytest                         # tests (no network needed)
```

Refresh options:

- `--only universe,factors,fundamentals,prices,profile,statements` runs some steps.
- `--tickers AAPL,MSFT` limits the run to some tickers.
- `--force` ignores freshness and reloads.

A refresh is safe to interrupt and rerun: each ticker is committed on its own,
anything refreshed within the windows in `[refresh] max_age_hours` is skipped,
and a ticker that fails is logged and skipped. The log is `data/logs/refresh.log`.

The app listens on 127.0.0.1 only, on any free port unless `[server] port` is set
in `config.toml` or `--port` is given. It reads the cache and never calls a data
source; run `refresh` in another terminal to update it, then reload the page.

When changing the frontend, run `uv run screener serve --port 8765 --no-browser`
and `npm --prefix frontend run dev` side by side; the dev server proxies `/api`.

## Data sources

| Data | Source | Notes |
|---|---|---|
| S&P 500 members, GICS sector | Wikipedia, "List of S&P 500 companies" | Current members only. No free official list exists. |
| Daily prices, dividends, splits | Yahoo Finance via `yfinance` | From 2000. Unofficial; can fail or be rate-limited. |
| Market cap, sector, industry | Yahoo Finance via `yfinance` | Current values only. |
| Recent statements (about 4 years) | Yahoo Finance via `yfinance` | Used as a cross-check on EDGAR. |
| Filed fundamentals with filing dates | SEC EDGAR company-facts API | Starts around 2009-2011. Primary source for fundamentals. |
| SIC code, fiscal year end | SEC EDGAR submissions API | |
| Factor returns, risk-free rate | Ken French Data Library | FF3, FF5, momentum; daily and monthly; lags 1-2 months. |

## How the data layer is organised

```
src/screener/
  config.py          settings from config.toml; no absolute paths or ports
  db.py              SQLite schema (WAL mode) and the refresh log
  providers/
    base.py          the one provider interface and its record types
    wikipedia.py  yahoo.py  edgar.py  french.py
    http.py          throttled GET with retries
  concepts.py        which XBRL tags supply each financial concept
  reference/cik_predecessors.toml   companies whose history spans two SEC registrants
  fundamentals.py    annual / quarterly series from filed facts, point in time
  refresh.py         the refresh job (the only writer of source data)
  analysis/
    statements.py    a company's annual statements as known on a date; derived lines
    formulas.py      the published formulas as pure functions, with citations
    prices.py        momentum, returns, volatility, beta, drawdown, trend
    engine.py        per-year history, the cross-section for a date, ranks, composite
    catalog.py       every measure: label, direction, format, explanation, source
    insights.py      rule-based observations
    compute.py       writes the analysis tables
  checks.py          EDGAR vs Yahoo cross-check
  server.py          FastAPI app: JSON API over the cache, serves the built frontend
  cli.py
frontend/            React + TypeScript (Vite); builds into src/screener/web
```

Rules the code follows:

- **Only the refresh job calls a data source.** Everything else reads the cache.
- **Providers are swappable.** Each kind of data is assigned to a provider under
  `[sources]` in `config.toml`. To add one, subclass `DataProvider`, register it in
  `providers/__init__.py`, and name it in the config.
- **Missing stays missing.** A value a source did not supply is stored as NULL or
  not stored. Nothing is filled with zero, estimated, or replaced by sample data.
- **Fundamentals are point in time.** Each filed figure keeps its filing date and
  accession number, and restatements are kept as separate rows. Query functions
  take `as_of` and then use only filings that existed on that date.
- **Raw EDGAR responses are kept** in `data/raw/edgar/`. After changing
  `concepts.py`, run `uv run screener rebuild-facts` to re-apply the mapping
  without downloading again.

### Things to know about the figures

- `close` is split-adjusted; `adj_close` is also dividend-adjusted. Yahoo rewrites
  adjusted history after each dividend or split, so the refresh compares the
  overlap with what is cached and reloads a ticker's full history when it differs.
- Companies do not report the fourth quarter on its own, and cash flow statements
  are year-to-date. `quarterly_series` derives those quarters by subtraction and
  flags them `derived`.
- XBRL tags differ between companies and over time. `concepts.py` lists candidate
  tags per concept in priority order and each value records the tag it came from.
  The mapping is provisional until milestone 2 checks it formula by formula.
- Only periodic reports (10-K, 10-Q and their foreign and amended equivalents) feed
  the series. Proxy statements repeat net income in XBRL, sometimes rounded, and
  are ignored.
- A company that reorganised under a new holding company has a new SEC number
  (CIK) and its older filings stay under the old one. `reference/cik_predecessors.toml`
  joins them; `screener coverage` lists companies that may need an entry. After
  adding one, run `uv run screener refresh --only fundamentals --force --tickers XYZ`.
- Yahoo and EDGAR define some lines differently (bank revenue, revenue including
  other income), so `crosscheck` mismatches are prompts to look, not errors.
- Factor returns are stored in percent, as published (`value_pct`).
- Two share classes of one company (GOOGL/GOOG, FOXA/FOX, NWSA/NWS) share one set
  of filed fundamentals.

## Scores and factors

`uv run screener compute` writes three tables: `fundamental_history` (every company
and fiscal year, computed from what its annual report showed on the filing date),
`snapshot` (one row per ticker for the latest trading day, with percentile ranks in
the universe, `__pct`, and in the GICS sector, `__spct`; 100 is most favourable),
and `insights`.

Formulas follow the papers cited in `analysis/formulas.py`, checked against the
papers' own text, and are tested against values worked out by hand from Apple's
fiscal 2026 statements (`tests/test_formulas.py`). Where the data forced a choice:

| Measure | Choice made |
|---|---|
| F-Score | "No equity issued" is measured as share count not rising. Shown only when all nine signals can be computed. |
| Altman Z, Beneish M | Not computed for financial companies (GICS Financials, or SEC industry codes for banks, brokers, insurers). |
| Beneish M | Total accruals use the cash-flow form (income less operating cash flow). Depreciation includes amortisation. |
| Accruals | Two measures: Sloan's balance-sheet form, and net income less operating cash flow, which far more companies support. |
| Quality | Simplified from Asness, Frazzini and Pedersen: growth uses totals, not per-share residual income; Ohlson's O-Score is left out; ROE volatility uses five annual values. |
| Beta | Frazzini-Pedersen method, with an S&P 500 tracker as the market. |
| Book equity | Shareholders' equity less preferred stock; deferred taxes are not added. |
| Market cap | Yahoo's figure for today's screen; share price times filed diluted shares for past dates. |
| Debt | The sum of the debt lines a company tags. If it tags none, debt is unknown, not zero. |
| Derived lines | Gross profit, total liabilities, EBIT and a few others are computed when not reported, and flagged. |
| Basis | Annual figures as published. Trailing-twelve-month figures are not yet computed. |

A score is missing whenever an input is missing. Coverage of the stricter scores
is therefore partial (see the CHANGELOG for current numbers).
