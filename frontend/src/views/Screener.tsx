import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Measure, type Row, type SavedScreen } from "../api";
import type { Shared } from "../App";
import { Info, ScaleLegend } from "../components/Info";
import { fmt, inputUnit, num } from "../format";
import { rankClass } from "../scale";
import {
  applyScreen, defaultScreen, download, sortRows, toCsv, withComposite,
  type Basis, type Filter, type Op, type ScreenDef,
} from "../screen";
import { CustomMeasuresMenu } from "./CustomMeasures";

/** A button that opens a small panel below it and closes on outside click or Escape. */
export function Menu({ label, children, wide }: { label: ReactNode; children: ReactNode; wide?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <span className="menu" ref={ref}>
      <button type="button" onClick={() => setOpen(!open)}>{label} ▾</button>
      {open && <div className={`popover ${wide ? "wide" : ""}`}><div className="menu-body">{children}</div></div>}
    </span>
  );
}

function groupBy(measures: Measure[]): [string, Measure[]][] {
  const groups = new Map<string, Measure[]>();
  measures.forEach((m) => groups.set(m.group, [...(groups.get(m.group) ?? []), m]));
  return [...groups.entries()];
}

export function MeasureSelect({ measures, value, onChange }: {
  measures: Measure[]; value: string; onChange: (key: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {groupBy(measures).map(([group, items]) => (
        <optgroup key={group} label={group}>
          {items.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
        </optgroup>
      ))}
    </select>
  );
}

function FilterRow({ filter, measures, byKey, onChange, onRemove }: {
  filter: Filter; measures: Measure[]; byKey: Record<string, Measure>;
  onChange: (f: Filter) => void; onRemove: () => void;
}) {
  const m = byKey[filter.key];                 // undefined if a custom measure was deleted
  const unit = filter.basis === "value" ? inputUnit(m?.fmt ?? "ratio") : "percentile";
  return (
    <div className="filter-row">
      <MeasureSelect measures={measures} value={filter.key} onChange={(key) => onChange({ ...filter, key })} />
      {m ? <Info measure={m} /> : <span className="error">no longer exists</span>}
      <select value={filter.basis} onChange={(e) => onChange({ ...filter, basis: e.target.value as Basis })}
        title="Filter on the value itself, or on its favourability rank (100 = most favourable)">
        <option value="value">value</option>
        <option value="pct">rank in universe</option>
        <option value="spct">rank in sector</option>
      </select>
      <select value={filter.op} onChange={(e) => onChange({ ...filter, op: e.target.value as Op })}>
        <option value=">=">at least</option>
        <option value="<=">at most</option>
        <option value="between">between</option>
      </select>
      <input type="number" value={filter.a} step="any" aria-label="Value"
        onChange={(e) => onChange({ ...filter, a: e.target.value })} />
      {filter.op === "between" && (
        <>
          <span className="muted">and</span>
          <input type="number" value={filter.b} step="any" aria-label="Upper value"
            onChange={(e) => onChange({ ...filter, b: e.target.value })} />
        </>
      )}
      <span className="muted">{unit}</span>
      <button type="button" className="link" onClick={onRemove} aria-label="Remove filter">Remove</button>
    </div>
  );
}

export function WeightsEditor({ weights, measures, onChange, defaults }: {
  weights: Record<string, number>; measures: Measure[]; defaults: Record<string, number>;
  onChange: (w: Record<string, number>) => void;
}) {
  const ranked = measures.filter((m) => m.better !== 0 && m.key !== "composite");
  const used = ranked.filter((m) => m.key in weights);
  const unused = ranked.filter((m) => !(m.key in weights));
  const total = Object.values(weights).reduce((a, b) => a + (b > 0 ? b : 0), 0);
  return (
    <div className="stack">
      <span className="muted">
        The composite is the weighted average of each measure's percentile rank (100 = most favourable).
        A stock missing some measures is scored on the rest if at least half the weight is present.
      </span>
      <div className="weights">
        {used.map((m) => (
          <div key={m.key} style={{ display: "contents" }}>
            <span>{m.label} <span className="muted">{total > 0 ? `${Math.round(((weights[m.key] > 0 ? weights[m.key] : 0) / total) * 100)}%` : ""}</span></span>
            <span className="row">
              <input type="number" min="0" step="0.5" value={weights[m.key]} aria-label={`Weight for ${m.label}`}
                onChange={(e) => onChange({ ...weights, [m.key]: Number(e.target.value) })} />
              <button type="button" className="link" onClick={() => {
                const next = { ...weights }; delete next[m.key]; onChange(next);
              }}>Remove</button>
            </span>
          </div>
        ))}
      </div>
      <div className="row">
        <select value="" onChange={(e) => e.target.value && onChange({ ...weights, [e.target.value]: 1 })}>
          <option value="">Add a measure…</option>
          {groupBy(unused).map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </optgroup>
          ))}
        </select>
        <button type="button" onClick={() => onChange({ ...defaults })}>Reset to equal value, momentum, quality, low risk</button>
      </div>
    </div>
  );
}

const PAGE = 100;

export function Screener({ shared }: { shared: Shared }) {
  const { meta, rows, byKey, screen, setScreen } = shared;
  const measures = meta.catalog.measures;
  const naKeys = meta.catalog.not_for_financials;
  const [saved, setSaved] = useState<SavedScreen[]>([]);
  const [shown, setShown] = useState(PAGE);
  const [message, setMessage] = useState("");
  const nextId = useRef(1);

  const reload = () => api.screens().then(setSaved).catch(() => setSaved([]));
  useEffect(() => { reload(); }, []);
  useEffect(() => { setShown(PAGE); }, [screen.filters, screen.sectors, screen.search, screen.excludeFinancials]);

  const set = (patch: Partial<ScreenDef>) => setScreen({ ...screen, ...patch });
  const sectors = useMemo(() => [...new Set(rows.map((r) => String(r.sector ?? "")))].filter(Boolean).sort(), [rows]);
  const scored = useMemo(() => withComposite(rows, screen.weights), [rows, screen.weights]);
  const matched = useMemo(() => applyScreen(scored, screen, byKey), [scored, screen, byKey]);
  const sorted = useMemo(() => sortRows(matched, screen.sort.key, screen.sort.dir), [matched, screen.sort]);
  const cols = screen.columns.filter((k) => byKey[k]).map((k) => byKey[k]);

  const sortBy = (key: string) => set({
    sort: screen.sort.key === key ? { key, dir: screen.sort.dir === 1 ? -1 : 1 } : { key, dir: key === "ticker" || key === "name" || key === "sector" ? 1 : -1 },
  });
  const arrow = (key: string) => (screen.sort.key === key ? (screen.sort.dir === 1 ? " ▲" : " ▼") : "");
  const addFilter = () => set({
    filters: [...screen.filters, { id: nextId.current++, key: "f_score", basis: "value", op: ">=", a: "", b: "" }],
  });

  const save = async () => {
    const name = window.prompt("Name for this screen:");
    if (!name) return;
    try { await api.saveScreen(name, screen); setMessage(`Saved "${name}".`); reload(); }
    catch (e) { setMessage(`Could not save: ${(e as Error).message}`); }
  };
  const load = (s: SavedScreen) => {
    const def = { ...defaultScreen(meta.catalog), ...(s.definition as Partial<ScreenDef>) };
    nextId.current = Math.max(0, ...def.filters.map((f) => f.id)) + 1;
    setScreen(def);
    setMessage(`Loaded "${s.name}".`);
  };
  const remove = async (name: string) => { await api.deleteScreen(name); reload(); };

  const exportCsv = () => {
    const columns = [
      { key: "ticker", label: "Ticker" }, { key: "name", label: "Name" }, { key: "sector", label: "Sector" },
      ...cols.flatMap((m) => [
        { key: m.key, label: m.label },
        ...(m.better !== 0 ? [{ key: `${m.key}__pct`, label: `${m.label} (universe percentile)` }] : []),
      ]),
    ];
    download(`screen-${meta.as_of ?? "latest"}.csv`, toCsv(sorted, columns));
  };

  const cell = (r: Row, m: Measure) => {
    const v = num(r[m.key]);
    if (v === null && r.financial && naKeys.includes(m.key)) {
      return <td key={m.key} className="na" title="Not meaningful for financial companies">n/a</td>;
    }
    const pct = m.better !== 0 ? num(r[`${m.key}__${screen.rankBasis}`]) : null;
    const title = pct !== null ? `${m.label}: ${Math.round(pct)}th percentile (${screen.rankBasis === "pct" ? "universe" : "sector"})` : undefined;
    return <td key={m.key} className={`num ${rankClass(pct)}`} title={title}>{fmt(v, m.fmt)}</td>;
  };

  return (
    <div className="stack">
      <div className="panel filters">
        <div className="row">
          <h2>Filters</h2>
          <input type="search" placeholder="Ticker or name" value={screen.search}
            onChange={(e) => set({ search: e.target.value })} style={{ width: 170 }} />
          <Menu label={screen.sectors.length ? `Sectors (${screen.sectors.length})` : "All sectors"}>
            {sectors.map((s) => (
              <label key={s}>
                <input type="checkbox" checked={screen.sectors.includes(s)} onChange={(e) => set({
                  sectors: e.target.checked ? [...screen.sectors, s] : screen.sectors.filter((x) => x !== s),
                })} />{s}
              </label>
            ))}
            <button type="button" className="link" onClick={() => set({ sectors: [] })}>Clear</button>
          </Menu>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={screen.excludeFinancials}
              onChange={(e) => set({ excludeFinancials: e.target.checked })} />Exclude financials
          </label>
          <button type="button" onClick={addFilter}>Add filter</button>
          {screen.filters.length > 0 && <button type="button" className="link" onClick={() => set({ filters: [] })}>Clear filters</button>}
        </div>
        {screen.filters.map((f) => (
          <FilterRow key={f.id} filter={f} measures={measures} byKey={byKey}
            onChange={(next) => set({ filters: screen.filters.map((x) => (x.id === f.id ? next : x)) })}
            onRemove={() => set({ filters: screen.filters.filter((x) => x.id !== f.id) })} />
        ))}
      </div>

      <div>
        <div className="toolbar">
          <strong>{matched.length} of {rows.length} stocks</strong>
          <Menu label="Columns" wide>
            {groupBy(measures).map(([group, items]) => (
              <div key={group} className="menu-group">
                <h3>{group}</h3>
                {items.map((m) => (
                  <label key={m.key}>
                    <input type="checkbox" checked={screen.columns.includes(m.key)} onChange={(e) => set({
                      columns: e.target.checked ? [...screen.columns, m.key] : screen.columns.filter((k) => k !== m.key),
                    })} />{m.label}
                  </label>
                ))}
              </div>
            ))}
          </Menu>
          <Menu label="Composite weights" wide>
            <WeightsEditor weights={screen.weights} measures={measures} defaults={meta.catalog.default_weights}
              onChange={(weights) => set({ weights })} />
          </Menu>
          <CustomMeasuresMenu shared={shared} />
          <span className="tabs" title="Which percentile rank colours the cells">
            <button type="button" className={screen.rankBasis === "pct" ? "on" : ""} onClick={() => set({ rankBasis: "pct" })}>Rank in universe</button>
            <button type="button" className={screen.rankBasis === "spct" ? "on" : ""} onClick={() => set({ rankBasis: "spct" })}>Rank in sector</button>
          </span>
          <ScaleLegend />
          <span className="spacer" />
          <Menu label={`Saved screens (${saved.length})`}>
            {saved.length === 0 && <span className="muted">None saved yet.</span>}
            {saved.map((s) => (
              <div key={s.name} className="row" style={{ justifyContent: "space-between" }}>
                <button type="button" className="link" onClick={() => load(s)}>{s.name}</button>
                <button type="button" className="link" onClick={() => remove(s.name)}>Delete</button>
              </div>
            ))}
          </Menu>
          <button type="button" onClick={save}>Save screen</button>
          <button type="button" onClick={exportCsv}>Export CSV</button>
          <a href="#/backtest"><button type="button" className="primary">Backtest this screen</button></a>
        </div>
        {message && <div className="muted" style={{ marginBottom: 6 }}>{message}</div>}
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 250px)", minHeight: 240 }}>
          <table>
            <thead>
              <tr>
                <th className="sortable sticky" onClick={() => sortBy("ticker")}>Ticker{arrow("ticker")}</th>
                <th className="sortable" onClick={() => sortBy("name")}>Name{arrow("name")}</th>
                <th className="sortable" onClick={() => sortBy("sector")}>Sector{arrow("sector")}</th>
                {cols.map((m) => (
                  <th key={m.key} className="sortable num" onClick={() => sortBy(m.key)}>
                    {m.label}{arrow(m.key)}<Info measure={m} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.slice(0, shown).map((r) => (
                <tr key={String(r.ticker)}>
                  <td className="sticky"><a href={`#/stock/${r.ticker}`}><b>{r.ticker}</b></a></td>
                  <td className="name" title={String(r.name ?? "")}>{r.name}</td>
                  <td className="name">{r.sector}</td>
                  {cols.map((m) => cell(r, m))}
                </tr>
              ))}
              {sorted.length === 0 && (
                <tr><td colSpan={3 + cols.length} className="muted" style={{ padding: 16 }}>
                  No stocks match these filters. A stock with no value for a filtered measure is excluded.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        {sorted.length > shown && (
          <div className="row" style={{ marginTop: 8 }}>
            <button type="button" onClick={() => setShown(shown + PAGE)}>Show {Math.min(PAGE, sorted.length - shown)} more</button>
            <button type="button" onClick={() => setShown(sorted.length)}>Show all {sorted.length}</button>
          </div>
        )}
      </div>
    </div>
  );
}
