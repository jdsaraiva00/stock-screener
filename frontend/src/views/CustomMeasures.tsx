import { useEffect, useState } from "react";
import { api, type CustomMeasure, type Fmt } from "../api";
import type { Shared } from "../App";
import { Menu } from "./Screener";

/** The panel where the user defines measures of their own: a name, a formula over
 * statement lines and market values, a direction and a format. Saved measures come
 * back through the catalog, so columns, filters, weights and the backtest all see them. */

interface Form { key?: string; label: string; formula: string; better: number; fmt: Fmt }
const EMPTY: Form = { label: "", formula: "", better: -1, fmt: "ratio" };
const DIRECTION = (b: number) => (b > 0 ? "higher is better" : b < 0 ? "lower is better" : "no direction");

export function CustomMeasuresMenu({ shared }: { shared: Shared }) {
  const { meta, screen, setScreen, reload } = shared;
  const [mine, setMine] = useState<CustomMeasure[]>([]);
  const [form, setForm] = useState<Form>(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.measures().then(setMine).catch(() => setMine([]));
  useEffect(() => { load(); }, []);
  const lines = meta.catalog.lines ?? [];      // absent when the server predates custom measures
  const builtIn = meta.catalog.measures.filter((m) => m.group !== "Custom" && m.fmt !== "flag" && m.key !== "composite");

  const save = async () => {
    setBusy(true); setError("");
    try {
      const body = { label: form.label, formula: form.formula, better: form.better, fmt: form.fmt };
      const saved = form.key ? await api.updateMeasure(form.key, body) : await api.createMeasure(body);
      setForm(EMPTY);
      await load();
      reload();
      if (!screen.columns.includes(saved.key)) setScreen({ ...screen, columns: [...screen.columns, saved.key] });
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const remove = async (m: CustomMeasure) => {
    if (!window.confirm(`Delete "${m.label}"? Screens that use it will drop it.`)) return;
    try {
      await api.deleteMeasure(m.key);
      const weights = { ...screen.weights };
      delete weights[m.key];
      setScreen({
        ...screen, weights,
        columns: screen.columns.filter((k) => k !== m.key),
        filters: screen.filters.filter((f) => f.key !== m.key),
        sort: screen.sort.key === m.key ? { key: "composite", dir: -1 } : screen.sort,
      });
      if (form.key === m.key) setForm(EMPTY);
      await load();
      reload();
    } catch (e) { setError((e as Error).message); }
  };

  const insert = (key: string) => {
    const gap = form.formula && !/[\s(]$/.test(form.formula) ? " " : "";
    setForm({ ...form, formula: `${form.formula}${gap}${key}` });
  };

  return (
    <Menu label={`Custom measures${mine.length ? ` (${mine.length})` : ""}`} wide>
      <div className="stack">
        <span className="muted">
          A formula over statement lines and market values, for example <code>total_debt / market_cap</code> or{" "}
          <code>cash_and_short_term / pretax_income</code>, with + − × ÷ and parentheses. Statement lines are the
          latest fiscal year as filed; market values are today's, or the rebalance date's in a backtest.
          A missing input or a division by zero gives a missing value. The measure is ranked like the built-in
          ones and can be a column, a filter or a composite weight.
        </span>
        {mine.length > 0 && (
          <table className="plain">
            <tbody>
              {mine.map((m) => (
                <tr key={m.key}>
                  <td><b>{m.label}</b></td>
                  <td><code>{m.formula}</code></td>
                  <td className="muted">{DIRECTION(m.better)}</td>
                  <td className="row" style={{ justifyContent: "flex-end" }}>
                    <button type="button" className="link" onClick={() => { setError(""); setForm({ ...m }); }}>Edit</button>
                    <button type="button" className="link" onClick={() => remove(m)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row">
          <input placeholder="Name, e.g. Debt / Mkt Cap" value={form.label} style={{ width: 200 }} aria-label="Measure name"
            onChange={(e) => setForm({ ...form, label: e.target.value })} />
          <select value={form.better} aria-label="Direction" onChange={(e) => setForm({ ...form, better: Number(e.target.value) })}>
            <option value={1}>higher is better</option>
            <option value={-1}>lower is better</option>
            <option value={0}>no direction (column only, not ranked)</option>
          </select>
          <select value={form.fmt} aria-label="Format" onChange={(e) => setForm({ ...form, fmt: e.target.value as Fmt })}>
            <option value="ratio">number (0.00)</option>
            <option value="pct">percent (value × 100)</option>
            <option value="multiple">multiple (×)</option>
            <option value="money">dollars</option>
          </select>
        </div>
        <div className="row">
          <input placeholder="Formula, e.g. total_debt / market_cap" value={form.formula} aria-label="Formula"
            style={{ flex: 1, minWidth: 260, fontFamily: "ui-monospace, monospace" }}
            onChange={(e) => setForm({ ...form, formula: e.target.value })}
            onKeyDown={(e) => { if (e.key === "Enter" && form.label.trim() && form.formula.trim()) save(); }} />
          <select value="" aria-label="Insert a line" onChange={(e) => { if (e.target.value) insert(e.target.value); }}>
            <option value="">Insert a line…</option>
            <optgroup label="Statement lines and market values">
              {lines.map((l) => <option key={l.key} value={l.key}>{l.label} ({l.key})</option>)}
            </optgroup>
            <optgroup label="Built-in measures">
              {builtIn.map((m) => <option key={m.key} value={m.key}>{m.label} ({m.key})</option>)}
            </optgroup>
          </select>
        </div>
        <div className="row">
          <button type="button" className="primary" onClick={save}
            disabled={busy || !form.label.trim() || !form.formula.trim()}>
            {form.key ? "Save changes" : "Add measure"}
          </button>
          {form.key && <button type="button" className="link" onClick={() => { setForm(EMPTY); setError(""); }}>Cancel</button>}
          {error && <span className="error">{error}</span>}
        </div>
      </div>
    </Menu>
  );
}
