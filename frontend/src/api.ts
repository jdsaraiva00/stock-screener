// Types and calls for the local API. Every value may be null: a missing value stays missing.

export type Fmt = "int" | "ratio" | "pct" | "money" | "multiple" | "flag" | "pctile";

export interface Measure {
  key: string; label: string; group: string; better: number; fmt: Fmt;
  about: string; cite: string; citation: string; components: string[];
}
export interface Catalog {
  measures: Measure[];
  components: Record<string, { label: string; fmt: Fmt; about: string }>;
  default_weights: Record<string, number>;
  not_for_financials: string[];
  lines: { key: string; label: string }[];      // names a custom formula may use
}
/** A user-defined measure: a formula over statement lines and market values. */
export interface CustomMeasure { key: string; label: string; formula: string; better: number; fmt: Fmt }
export type CustomMeasureInput = Omit<CustomMeasure, "key">;
export interface Freshness {
  data: string; step: string; series: number; oldest_fetch: string | null;
  newest_fetch: string | null; data_through: string | null; failing: number;
}
export interface Meta {
  universe: string; as_of: string | null; computed_at: string | null;
  freshness: Freshness[]; catalog: Catalog;
  failures: { step: string; key: string; last_attempt: string; last_success: string | null; error: string }[];
}
export type Row = Record<string, number | string | null>;
export interface Split { columns: string[]; data: (number | string | null)[][] }
export interface Insight { tone: "good" | "bad" | "neutral"; text: string; measures: string[] }
export interface StockDetail {
  row: Row; profile: Row | null; filer: Row | null;
  fetched: { prices: string | null; fundamentals: string | null; profile: string | null };
  history: Row[]; prices: Split; insights: Insight[];
  sources: { period_end: string; available: string; derived: Record<string, string>; tags: Record<string, string> } | null;
  peers: Split;
}
export interface SavedScreen { name: string; definition: unknown; updated_at: string }

export interface BacktestConfig {
  weights: Record<string, number>;
  filters: { key: string; basis: string; lo: number | null; hi: number | null }[];
  sectors: string[];
  exclude_financials: boolean;
  top_n: number;
  rebalance: "monthly" | "quarterly";
  start: string | null;
  end: string | null;
  cost_bps: number;
}
export interface BacktestResult {
  config: BacktestConfig;
  coverage: {
    first_rebalance: string; first_day: string; last_date: string; rebalances: number;
    factor_data_through: string | null; benchmark: string | null;
    membership: boolean; members_today?: number; former_members?: number;
    former_with_prices?: number; former_with_fundamentals?: number; record_from?: string | null;
  };
  curve: { dates: string[]; portfolio: number[]; universe: number[]; benchmark: number[] | null };
  stats: Record<"portfolio" | "universe" | "benchmark", Record<string, number | null> | undefined>;
  regression: {
    model: string; months: number; r_squared: number | null; alpha_annual_pct: number | null;
    first_month: string; last_month: string;
    terms: { name: string; coef: number | null; t: number | null }[];
  }[];
  holdings: { date: string; tickers: string[]; scores: (number | null)[]; turnover: number | null; eligible: number }[];
  notes: string[];
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function toRows(split: Split): Row[] {
  return split.data.map((values) => {
    const row: Row = {};
    split.columns.forEach((c, i) => { row[c] = values[i]; });
    return row;
  });
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export interface RefreshStatus {
  running: boolean; started_at: string | null; finished_at: string | null;
  result: string | null; error: string | null; log?: string[];
}

export const api = {
  refreshStatus: () => call<RefreshStatus>("/api/refresh"),
  startRefresh: () => call<RefreshStatus>("/api/refresh", { method: "POST" }),
  meta: () => call<Meta>("/api/meta"),
  screen: async () => toRows(await call<Split>("/api/screen")),
  stock: (ticker: string) => call<StockDetail>(`/api/stock/${encodeURIComponent(ticker)}`),
  screens: () => call<SavedScreen[]>("/api/screens"),
  saveScreen: (name: string, definition: unknown) => call(`/api/screens/${encodeURIComponent(name)}`, json("PUT", definition)),
  deleteScreen: (name: string) => call(`/api/screens/${encodeURIComponent(name)}`, { method: "DELETE" }),
  measures: () => call<CustomMeasure[]>("/api/measures"),
  createMeasure: (m: CustomMeasureInput) => call<CustomMeasure>("/api/measures", json("POST", m)),
  updateMeasure: (key: string, m: CustomMeasureInput) => call<CustomMeasure>(`/api/measures/${encodeURIComponent(key)}`, json("PUT", m)),
  deleteMeasure: (key: string) => call(`/api/measures/${encodeURIComponent(key)}`, { method: "DELETE" }),
  backtest: (config: BacktestConfig) => call<BacktestResult>("/api/backtest", json("POST", config)),
};
