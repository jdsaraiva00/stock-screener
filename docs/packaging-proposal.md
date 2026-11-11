# Proposal: packaging as a double-click desktop app

Status: proposal only. Nothing here is built yet.

## What already makes this cheap

- One process: the Python backend serves the built frontend itself.
- One command: `screener serve` picks a free port and opens the browser.
- No absolute paths: everything is found relative to `config.toml`, or to the
  file named by the `SCREENER_CONFIG` environment variable.
- The data update runs inside the app (the "Update data now" button), in a
  thread, not as a separate command-line process.
- Scores are computed by the same process; nothing needs a terminal.

## Recommended: PyInstaller, one-folder app, browser as the window

Build a `Stock Screener.app` (macOS) or `Stock Screener.exe` (Windows) with
PyInstaller. Double-clicking starts the server and opens the default browser at
the local address. A small menu-bar or tray icon offers "Open" and "Quit".

Why this option:

- It reuses the app exactly as it is. No second UI technology to maintain.
- The browser is already the best renderer for the charts and tables.
- Build time is minutes and the result is one folder of roughly 150-250 MB
  (pandas and numpy are most of it; this is an estimate, not measured).

Work needed, in order:

1. **Data location.** When running as a packaged app, keep `config.toml`, the
   cache and saved screens in the per-user data folder
   (`~/Library/Application Support/StockScreener` on macOS,
   `%APPDATA%\StockScreener` on Windows) instead of next to the code. This is a
   small change in `config.find_config`.
2. **First-run screen.** A page that asks for the EDGAR contact line, writes
   `config.toml`, and starts the first data load with a progress display. Today
   that step needs a text editor and a terminal.
3. **Entry point.** A `desktop.py` that starts the server on a free port, opens
   the browser, and shows the tray icon (the `pystray` package).
4. **Build script.** A PyInstaller spec that includes `src/screener/web` and
   `src/screener/reference`, plus a one-line build command in the README.
5. **Quit handling.** Stop cleanly if a data update is running (finish the
   current ticker, then exit).

Rough effort: one working session, plus testing on each operating system the
app should run on. A build made on macOS runs only on macOS; a Windows build
has to be made on Windows.

Known friction:

- **macOS Gatekeeper.** An unsigned app shows a warning on first launch
  (right-click, Open, once). Removing the warning needs an Apple Developer
  account (99 USD a year) for signing and notarisation. For personal use on
  your own machine, the right-click step is enough.
- **yfinance** uses `curl_cffi`, which ships native libraries. PyInstaller
  usually collects them, but this is the dependency most likely to need a
  manual hook.

## Alternative: a native window instead of a browser tab

Wrap the same server in a native window with `pywebview` (uses the system's
built-in web view: WebKit on macOS, WebView2 on Windows). It feels like a
desktop program, with its own window and dock icon, and adds about 5 MB.

Costs: file downloads (CSV export) and new-tab links need small adapters, and
the system web view on older Windows versions may be missing. Worth doing only
if a separate window matters to you; it can be added later on top of the
recommended option without redoing anything.

## Not recommended

- **Electron or Tauri.** They would bundle or drive a browser shell around a
  Python process that still has to be packaged with PyInstaller anyway: two
  build systems for no functional gain here.
- **Rewriting the backend for the browser (Pyodide).** The data fetching
  cannot run in a browser sandbox, and the cache is several hundred megabytes.

## Decision needed from you

1. Which operating systems should the packaged app run on?
2. Browser tab (recommended) or native window?
3. Is the one-time "right-click, Open" step on macOS acceptable, or do you want
   signing set up?
