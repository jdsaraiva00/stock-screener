# Changelog

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
