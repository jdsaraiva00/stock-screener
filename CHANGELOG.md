# Changelog

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
