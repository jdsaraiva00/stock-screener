import type { Fmt } from "./api";

export const MISSING = "—";

export function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const fixed = (v: number, d: number) =>
  v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

export function money(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return `$${fixed(v / 1e12, 2)}T`;
  if (a >= 1e9) return `$${fixed(v / 1e9, 1)}B`;
  if (a >= 1e6) return `$${fixed(v / 1e6, 0)}M`;
  return `$${fixed(v, 0)}`;
}

/** Format a value for display. Missing values are shown as a dash, never as zero. */
export function fmt(value: unknown, kind: Fmt): string {
  const v = num(value);
  if (v === null) return MISSING;
  switch (kind) {
    case "int": return fixed(v, 0);
    case "ratio": return fixed(v, 2);
    case "pct": return `${fixed(v * 100, 1)}%`;
    case "money": return money(v);
    case "multiple": return `${fixed(v, 1)}×`;
    case "flag": return v ? "Yes" : "No";
    case "pctile": return fixed(v, 0);
  }
}

/** Statement amounts in USD millions. */
export function millions(value: unknown): string {
  const v = num(value);
  return v === null ? MISSING : fixed(v / 1e6, 0);
}

export function ordinal(p: number): string {
  const n = Math.round(p);
  const s = n % 100 >= 10 && n % 100 <= 20 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${s}`;
}

/** Filters take percentages as typed (10 means 10%); the data holds fractions. */
export const inputScale = (kind: Fmt) => (kind === "pct" ? 100 : kind === "money" ? 1e9 : 1);
export const inputUnit = (kind: Fmt) => (kind === "pct" ? "%" : kind === "money" ? "$bn" : "");

export function shortDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : MISSING;
}

export function ageLabel(iso: string | null | undefined): string {
  if (!iso) return "never";
  const hours = (Date.now() - new Date(iso).getTime()) / 36e5;
  if (hours < 1) return "under an hour ago";
  if (hours < 48) return `${Math.round(hours)} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
