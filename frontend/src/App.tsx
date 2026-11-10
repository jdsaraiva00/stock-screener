import { useEffect, useMemo, useState } from "react";
import { api, type Measure, type Meta, type Row } from "./api";
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

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem("theme") as Theme) || "system"; } catch { return "system"; }
  });
  useEffect(() => {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch { /* private window */ }
  }, [theme]);
  const next = () => setTheme(theme === "system" ? "dark" : theme === "dark" ? "light" : "system");
  return [theme, next];
}

function FreshnessPanel({ meta }: { meta: Meta }) {
  const [open, setOpen] = useState(false);
  const failing = meta.freshness.reduce((n, f) => n + f.failing, 0);
  const prices = meta.freshness.find((f) => f.step === "prices");
  return (
    <div className="fresh">
      <button type="button" onClick={() => setOpen(!open)} title="Data freshness">
        <span className={`dot ${failing ? "warn" : ""}`} />
        Prices to {shortDate(prices?.data_through)} · fetched {ageLabel(prices?.newest_fetch)}
        {failing ? ` · ${failing} failing` : ""}
      </button>
      {open && (
        <div className="popover right wide">
          <strong>Data freshness</strong>
          <span className="muted">
            The app reads only from the local cache. Update it with <code>screener refresh</code>.
            Scores computed {ageLabel(meta.computed_at)} for {shortDate(meta.as_of)}.
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
          {meta.failures.length > 0 && (
            <>
              <strong>Failing</strong>
              <div className="menu-body">
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
  const [screen, setScreen] = useState<ScreenDef | null>(null);

  useEffect(() => {
    Promise.all([api.meta(), api.screen()])
      .then(([m, r]) => { setMeta(m); setRows(r); setScreen(defaultScreen(m.catalog)); })
      .catch((e: Error) => setError(e.message));
  }, []);

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
  if (error) body = <div className="error">Could not load data: {error}</div>;
  else if (meta && rows && screen) {
    const shared: Shared = { meta, rows, byKey, screen, setScreen };
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
        {meta && <FreshnessPanel meta={meta} />}
        <button type="button" onClick={nextTheme} title="Switch theme">Theme: {theme}</button>
      </header>
      <main className="main">{body}</main>
    </div>
  );
}
