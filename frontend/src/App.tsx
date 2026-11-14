import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Measure, type Meta, type RefreshStatus, type Row } from "./api";
import { ageLabel, shortDate } from "./format";
import { defaultScreen, type ScreenDef } from "./screen";
import { Backtest } from "./views/Backtest";
import { Market } from "./views/Market";
import { Screener } from "./views/Screener";
import { Stock } from "./views/Stock";

export interface Shared {
  meta: Meta;
  rows: Row[];
  byKey: Record<string, Measure>;
  screen: ScreenDef;
  setScreen: (s: ScreenDef) => void;
  reload: () => void;           // refetch the catalog and the rows (after a custom measure changes)
}

function useHashRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

type Theme = "system" | "light" | "dark";

// Per-browser conveniences only; anything that matters (saved screens) is stored by the backend.
function stored<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? (JSON.parse(raw) as T) : fallback; } catch { return fallback; }
}
function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private window */ }
}

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => stored<Theme>("theme", "system"));
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    store("theme", theme);
  }, [theme]);
  const next = () => setTheme(theme === "system" ? "dark" : theme === "dark" ? "light" : "system");
  return [theme, next];
}

const STALE_DAYS = 4;       // covers a long weekend

function FreshnessPanel({ meta, onUpdated }: { meta: Meta; onUpdated: () => void }) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<RefreshStatus | null>(null);
  const wasRunning = useRef(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => { api.refreshStatus().then(setStatus).catch(() => undefined); }, []);
  useEffect(() => {
    if (!status?.running) {
      if (wasRunning.current) { wasRunning.current = false; onUpdated(); }
      return;
    }
    wasRunning.current = true;
    const timer = window.setTimeout(() => api.refreshStatus().then(setStatus).catch(() => undefined), 3000);
    return () => window.clearTimeout(timer);
  }, [status, onUpdated]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const start = () => api.startRefresh().then(setStatus)
    .catch((e: Error) => setStatus({ running: false, started_at: null, finished_at: null, result: null, error: e.message }));
  const failing = meta.freshness.reduce((n, f) => n + f.failing, 0);
  const prices = meta.freshness.find((f) => f.step === "prices");
  const ageDays = prices?.data_through ? (Date.now() - new Date(prices.data_through).getTime()) / 864e5 : Infinity;
  const stale = ageDays > STALE_DAYS;
  return (
    <div className="fresh" ref={ref}>
      <button type="button" onClick={() => setOpen(!open)} title="Data freshness">
        <span className={`dot ${failing || stale ? "warn" : ""}`} />
        {status?.running ? "Updating data… " : ""}
        Prices to {shortDate(prices?.data_through)}{stale ? " (out of date)" : ""} · fetched {ageLabel(prices?.newest_fetch)}
        {failing ? ` · ${failing} failing` : ""}
      </button>
      {open && (
        <div className="popover right wide">
          <strong>Data freshness</strong>
          <span className="muted">
            Pages read only from the local cache. Scores were computed {ageLabel(meta.computed_at)} for {shortDate(meta.as_of)}.
          </span>
          <table className="plain">
            <thead><tr><th>Data</th><th className="num">Series</th><th>Oldest fetch</th><th>Newest fetch</th><th>Data through</th><th className="num">Failing</th></tr></thead>
            <tbody>
              {meta.freshness.map((f) => (
                <tr key={f.step}>
                  <td>{f.data}</td><td className="num">{f.series}</td>
                  <td>{ageLabel(f.oldest_fetch)}</td><td>{ageLabel(f.newest_fetch)}</td>
                  <td>{shortDate(f.data_through)}</td><td className="num">{f.failing}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="row">
            <button type="button" className="primary" onClick={start} disabled={status?.running}>
              {status?.running ? "Updating…" : "Update data now"}
            </button>
            <span className="muted">
              Fetches only what is out of date, then recomputes scores. Usually a few minutes; the app stays usable.
            </span>
          </div>
          {status?.running && <span className="muted">Started {ageLabel(status.started_at)}. This panel refreshes itself.</span>}
          {status?.error && <span className="error">Update failed: {status.error}</span>}
          {status?.result && !status.running && <span>Last update: {status.result} (finished {ageLabel(status.finished_at)}).</span>}
          {status?.running && status.log && status.log.length > 0 && (
            <pre className="muted" style={{ margin: 0, fontSize: 11, whiteSpace: "pre-wrap" }}>{status.log.join("\n")}</pre>
          )}
          {meta.failures.length > 0 && (
            <>
              <strong>Failing</strong>
              <div className="menu-body" style={{ maxHeight: 160 }}>
                {meta.failures.map((f) => (
                  <div key={f.step + f.key}><b>{f.key}</b> ({f.step}): {f.error}</div>
                ))}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function App() {
  const route = useHashRoute();
  const [theme, nextTheme] = useTheme();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [screen, setScreenState] = useState<ScreenDef | null>(null);

  const load = useCallback(() => {
    Promise.all([api.meta(), api.screen()])
      .then(([m, r]) => {
        setMeta(m); setRows(r); setError(null);
        // Keep the screen being worked on across reloads of the page.
        setScreenState((current) => current ?? { ...defaultScreen(m.catalog), ...stored<Partial<ScreenDef>>("screen", {}) });
      })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const setScreen = useCallback((s: ScreenDef) => { setScreenState(s); store("screen", s); }, []);
  const byKey = useMemo(() => {
    const map: Record<string, Measure> = {};
    meta?.catalog.measures.forEach((m) => { map[m.key] = m; });
    return map;
  }, [meta]);

  const view = route[0] ?? "screener";
  const link = (id: string, label: string) => (
    <a href={`#/${id}`} className={view === id || (id === "screener" && view === "stock") ? "active" : ""}>{label}</a>
  );

  let body = <div className="muted">Loading the cache…</div>;
  if (error) {
    body = (
      <div className="error">
        Could not load data: {error}
        <div className="muted">If this is a new installation, run <code>screener refresh</code> once to fill the cache.</div>
      </div>
    );
  } else if (meta && rows && screen) {
    const shared: Shared = { meta, rows, byKey, screen, setScreen, reload: load };
    if (view === "stock" && route[1]) body = <Stock key={route[1]} ticker={route[1]} shared={shared} />;
    else if (view === "market") body = <Market shared={shared} />;
    else if (view === "backtest") body = <Backtest shared={shared} />;
    else body = <Screener shared={shared} />;
  }

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Stock screener</span>
        <nav className="nav">
          {link("screener", "Screener")}
          {link("market", "Market overview")}
          {link("backtest", "Backtest")}
        </nav>
        <span className="spacer" />
        {meta && <span className="chip">{meta.universe === "sp500" ? "S&P 500" : meta.universe}</span>}
        {meta && <FreshnessPanel meta={meta} onUpdated={load} />}
        <button type="button" onClick={nextTheme} title="Switch theme">Theme: {theme}</button>
      </header>
      <main className="main">{body}</main>
    </div>
  );
}
