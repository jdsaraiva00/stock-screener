# Changelog

## Survivorship bias (2026-11-14)

- The refresh keeps Wikipedia's record of S&P 500 additions and removals
  (`universe_changes`) and adds every company that left the index since 2000
  to the universe with its removal date. Their prices and, where the SEC still
  lists the ticker, their filings are fetched like members'. A delisted company
  with no data at the source is noted, not counted as a failure.
- The backtest makes only that date's members eligible on each rebalance date,
  including former members with data, and its universe line is "all members
  at each date". Its notes and the page state how many former members the
  cache covers. Guard against reused symbols: a former member's prices are
  dropped if they begin after the removal and cut at the first long gap after it.
- Run `screener refresh` (or "Update data now") once to fetch the record and
  the former members' data; `screener compute` then includes their filings.

## Custom measures (2026-11-14)

- Define your own measures in the screener ("Custom measures" in the toolbar):
  a formula over statement lines and market values, e.g. `total_debt / market_cap`
  or `cash_and_short_term / pretax_income`, with a direction and a format. They
  are ranked like built-in measures and work as columns, filters, composite
  weights and in the backtest, computed on each rebalance date's cross-section.
- More statement lines are kept per fiscal year for use in formulas: pre-tax
  income, income tax, interest expense, depreciation and amortisation, SG&A,
  R&D, cash, receivables, inventory, PP&E, and debt split current/non-current.
  Run `screener compute` once after updating.
- `Stock Screener.command`: a double-click launcher for macOS.

## Milestone 6 — polish and packaging proposal (2026-11-11)

- "Update data now" in the freshness panel: runs the incremental refresh and the
  score computation in the background while the app stays usable, with live
  progress; one update at a time.
- The freshness indicator turns red when prices are more than four days old or
  any ticker is failing.
- The screen being worked on (filters, columns, weights, sort) survives a page reload.
- Charts show their whole range (the price chart's "All" and the backtest curve
  previously stopped at about nine years).
- `python -m screener` works as well as the `screener` command.
- Packaging proposal: `docs/packaging-proposal.md`.

## Milestone 5 — backtest (2026-11-11)

- Backtest engine: equal-weighted top N by composite, monthly or quarterly,
  trades the day after the signal, transaction cost setting, holdings drift
  between rebalances. Uses the screener's own cross-section code on each date,
  with fundamentals available only from their SEC filing date.
- Results: growth chart against the S&P 500 total return index and against all
  current members equal-weighted; CAGR, volatility, Sharpe, maximum drawdown,
  turnover; regressions on Fama-French 3 and 5 factors with and without momentum;
  holdings at every rebalance.
- Survivorship bias, actual date coverage and the McLean-Pontiff caveat are shown
  on the page next to the results.
- A backtest starts only when every weighted measure exists for at least 2N stocks.
- First run about 5 s (quarterly) to 11 s (monthly); later runs under a second.

## Milestone 4 — stock detail and market overview (2026-11-11)

- Stock detail: price chart (ranges, with or without dividends), rule-based
  insights with the numbers they rest on, a card per score with every component,
  universe and sector percentiles and a strip showing sector peers, multi-year
  fundamentals as charts and a table, and the XBRL tags and derived lines behind
  the latest year.
- Market overview: sector heatmap (median returns and factor ranks), the
  distribution of any measure across the universe, and the stocks at each extreme.
- Fix: year-on-year working-capital changes are no longer computed when a company
  re-tagged its short-term investments between the two years (this had inflated
  Nvidia's Sloan accruals). Such cases now show as missing.

## Milestone 3 — screener view (2026-11-10)

- `screener serve`: local web app (FastAPI) on 127.0.0.1, any free port, serving
  the built React frontend and a JSON API that reads only the cache.
- Screener: filter builder over every measure (by value, or by rank in the
  universe or sector), sector and text filters, sortable table with selectable
  columns, adjustable composite weights, saved screens, CSV export.
- One colour scale throughout: blue favourable, red unfavourable (safe for
  red-green colour blindness); light and dark themes.
- Each measure has an info button with what it measures and its source.
- Data freshness shown in the top bar, with failing tickers listed.
- Altman Z and Beneish M show "n/a" for financial companies; missing values show a dash.
- Saved screens live in `data/user.sqlite`, separate from the rebuildable cache.

## Milestone 2 — scores and factors (2026-11-10)

- Formulas, each checked against its paper and tested against hand-worked values
  from Apple's fiscal 2026 statements: Piotroski F-Score, Altman Z, Beneish M,
  accruals (Sloan and cash-flow forms), gross profitability, asset growth,
  book-to-market, earnings yield, EBIT/EV, free cash flow yield, quality
  composite, Frazzini-Pedersen beta, volatility, 12-1 momentum, price measures.
- Point-in-time history: each fiscal year computed from filings available when
  its annual report was filed.
- Percentile ranks within the universe and within the GICS sector; value,
  low-risk and weighted composite scores.
- Altman Z and Beneish M marked not applicable for 82 financial tickers.
- Rule-based insights that cite the measures they rest on.
- Derived statement lines (gross profit, total liabilities, EBIT, net income
  less minority share), flagged as derived.
- `screener compute`; `refresh` now recomputes scores when it finishes.
- Coverage on the S&P 500 (503 tickers): F-Score 276, Altman Z 372 of 421
  non-financials, Beneish M 204, gross profitability 318, cash-flow accruals,
  book-to-market, earnings yield, momentum and quality 500.

## Milestone 1 — data layer and cache (2026-11-10)

- Project set up with uv on Python 3.13; `screener` command line tool.
- One provider interface with four sources: Wikipedia (S&P 500 members),
  yfinance (prices, profile, recent statements), SEC EDGAR (filed fundamentals,
  filer details), Ken French Data Library (factors, risk-free rate).
- SQLite cache with fetch timestamps; raw EDGAR responses kept on disk.
- Refresh job: incremental, throttled, with retries; failures logged per ticker
  and skipped; price history reloaded when the source re-adjusts it.
- Point-in-time fundamentals queries (`as_of`), annual and quarterly series,
  derived fourth quarters flagged.
- Filed history joined across predecessor SEC registrants for 16 reorganised
  companies (Exxon, Alphabet, Disney and others), cut off at the hand-over.
- Series use periodic reports only, so proxy-statement figures cannot override
  audited ones.
- Commands: `refresh`, `status`, `show`, `crosscheck`, `coverage`, `rebuild-facts`.
- EDGAR vs Yahoo cross-check for nine statement lines.
- Tests against a trimmed real Apple filing record; no network needed.

Not yet built: scores, dashboard, backtest (milestones 2 to 5).
