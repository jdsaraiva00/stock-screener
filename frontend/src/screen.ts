// A screen definition and how it is applied. The backtest sends the same
// definition to the backend, which applies the same rules on each rebalance date.

import type { Catalog, Measure, Row } from "./api";
import { inputScale, num } from "./format";

export type Basis = "value" | "pct" | "spct";
export type Op = ">=" | "<=" | "between";
export interface Filter { id: number; key: string; basis: Basis; op: Op; a: string; b: string }
export interface ScreenDef {
  filters: Filter[];
  sectors: string[];            // empty = all
  excludeFinancials: boolean;
  search: string;
  columns: string[];
  sort: { key: string; dir: 1 | -1 };
  weights: Record<string, number>;
  rankBasis: "pct" | "spct";    // which percentile colours the cells
}

export const DEFAULT_COLUMNS = ["market_cap", "composite", "value_score", "mom_12_1", "quality",
  "low_risk_score", "f_score", "altman_z", "beneish_m", "earnings_yield", "ret_1y"];

export function defaultScreen(catalog: Catalog): ScreenDef {
  return {
    filters: [], sectors: [], excludeFinancials: false, search: "", columns: DEFAULT_COLUMNS,
    sort: { key: "composite", dir: -1 }, weights: { ...catalog.default_weights }, rankBasis: "pct",
  };
}

export const column = (key: string, basis: Basis) => (basis === "value" ? key : `${key}__${basis}`);

/** Weighted average of percentile ranks; needs at least half the weight present. */
export function compositeOf(row: Row, weights: Record<string, number>, basis: "pct" | "spct" = "pct"): number | null {
  let total = 0, present = 0, sum = 0;
  for (const [key, w] of Object.entries(weights)) {
    if (!(w > 0)) continue;
    total += w;
    const p = num(row[`${key}__${basis}`]);
    if (p !== null) { present += w; sum += w * p; }
  }
  return total > 0 && present >= total / 2 ? sum / present : null;
}

/** Rows with the composite recomputed for the chosen weights. */
export function withComposite(rows: Row[], weights: Record<string, number>): Row[] {
  return rows.map((r) => {
    const c = compositeOf(r, weights, "pct");
    return { ...r, composite: c, composite__pct: c, composite__spct: compositeOf(r, weights, "spct") };
  });
}

/** A filter's bounds in the units the data uses (fractions, dollars). */
export function bounds(f: Filter, measure: Measure | undefined): { lo: number | null; hi: number | null } {
  const scale = f.basis === "value" && measure ? inputScale(measure.fmt) : 1;
  const parse = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? null : Number(s) / scale);
  const a = parse(f.a), b = parse(f.b);
  if (f.op === ">=") return { lo: a, hi: null };
  if (f.op === "<=") return { lo: null, hi: a };
  return { lo: a, hi: b };
}

export function applyScreen(rows: Row[], def: ScreenDef, byKey: Record<string, Measure>): Row[] {
  const active = def.filters
    .map((f) => ({ col: column(f.key, f.basis), ...bounds(f, byKey[f.key]) }))
    .filter((f) => f.lo !== null || f.hi !== null);
  const q = def.search.trim().toLowerCase();
  return rows.filter((r) => {
    if (def.sectors.length && !def.sectors.includes(String(r.sector))) return false;
    if (def.excludeFinancials && r.financial) return false;
    if (q && !String(r.ticker).toLowerCase().includes(q) && !String(r.name ?? "").toLowerCase().includes(q)) return false;
    for (const f of active) {
      const v = num(r[f.col]);
      if (v === null) return false;            // a stock with no value cannot pass a filter on it
      if (f.lo !== null && v < f.lo) return false;
      if (f.hi !== null && v > f.hi) return false;
    }
    return true;
  });
}

export function sortRows(rows: Row[], key: string, dir: 1 | -1): Row[] {
  return [...rows].sort((x, y) => {
    const a = x[key], b = y[key];
    const an = a === null || a === undefined, bn = b === null || b === undefined;
    if (an || bn) return an === bn ? 0 : an ? 1 : -1;      // missing values always last
    if (typeof a === "number" && typeof b === "number") return (a - b) * dir;
    return String(a).localeCompare(String(b)) * dir;
  });
}

/** The definition in the form the backtest endpoint expects (data units). */
export function toBacktestFilters(def: ScreenDef, byKey: Record<string, Measure>) {
  return def.filters
    .map((f) => ({ key: f.key, basis: f.basis, ...bounds(f, byKey[f.key]) }))
    .filter((f) => f.lo !== null || f.hi !== null);
}

export function toCsv(rows: Row[], columns: { key: string; label: string }[]): string {
  const cell = (v: unknown) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map((c) => cell(c.label)).join(","),
    ...rows.map((r) => columns.map((c) => cell(r[c.key])).join(","))].join("\n");
}

export function download(filename: string, text: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
