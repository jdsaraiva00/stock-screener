import { useMemo, useState } from "react";
import type { Measure, Row } from "../api";
import type { Shared } from "../App";
import { Info, ScaleLegend } from "../components/Info";
import { Columns, useTip } from "../components/Svg";
import { fmt, num } from "../format";
import { rankClass, signClass } from "../scale";
import { withComposite } from "../screen";
import { MeasureSelect } from "./Screener";

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const values = (rows: Row[], key: string) => rows.map((r) => num(r[key])).filter((v): v is number => v !== null);

const RETURNS = ["ret_1m", "ret_3m", "ret_6m", "ret_1y"];
const FACTORS = ["value_score", "mom_12_1", "quality", "low_risk_score", "f_score", "gross_profitability", "asset_growth", "accruals_cf"];

function SectorHeatmap({ rows, byKey }: { rows: Row[]; byKey: Record<string, Measure> }) {
  const [show, hide, tip] = useTip();
  const sectors = useMemo(() => [...new Set(rows.map((r) => String(r.sector ?? "")))].filter(Boolean).sort(), [rows]);
  const template = `minmax(150px, 1.6fr) 44px repeat(${RETURNS.length + FACTORS.length}, minmax(64px, 1fr))`;
  return (
    <div className="panel stack">
      <div className="row">
        <h2>Sectors</h2>
        <span className="muted">Median stock in each sector. Returns are coloured by sign; factors by the median stock's percentile rank in the universe.</span>
        <span className="spacer" /><ScaleLegend />
      </div>
      <div style={{ overflowX: "auto" }}>
        <div className="heat" style={{ gridTemplateColumns: template, minWidth: 980 }}>
          <span className="heat-head" style={{ textAlign: "left" }}>Sector</span>
          <span className="heat-head">Stocks</span>
          {[...RETURNS, ...FACTORS].map((k) => (
            <span key={k} className="heat-head" title={byKey[k].about}>{byKey[k].label}</span>
          ))}
          {sectors.map((sector) => {
            const members = rows.filter((r) => r.sector === sector);
            return (
              <div key={sector} style={{ display: "contents" }}>
                <span className="heat-label">{sector}</span>
                <span className="heat-cell muted">{members.length}</span>
                {RETURNS.map((k) => {
                  const v = median(values(members, k));
                  return (
                    <span key={k} className={`heat-cell ${signClass(v, k === "ret_1m" ? 0.08 : k === "ret_3m" ? 0.12 : 0.25)}`}
                      onMouseMove={(e) => show(e, <><b>{sector}</b><br />Median {byKey[k].label.toLowerCase()}: {fmt(v, "pct")}<br />{values(members, k).length} stocks</>)}
                      onMouseLeave={hide}>{fmt(v, "pct")}</span>
                  );
                })}
                {FACTORS.map((k) => {
                  const v = median(values(members, k)), p = median(values(members, `${k}__pct`));
                  return (
                    <span key={k} className={`heat-cell ${rankClass(p)}`}
                      onMouseMove={(e) => show(e, <><b>{sector}</b><br />Median {byKey[k].label}: {fmt(v, byKey[k].fmt)}<br />Median percentile in universe: {fmt(p, "pctile")}<br />{values(members, k).length} stocks with a value</>)}
                      onMouseLeave={hide}>{fmt(v, byKey[k].fmt)}</span>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
      {tip}
    </div>
  );
}

const BINS = 30;

function Distribution({ rows, measure }: { rows: Row[]; measure: Measure }) {
  const xs = useMemo(() => values(rows, measure.key).sort((a, b) => a - b), [rows, measure.key]);
  if (xs.length < 5) return <div className="muted">Too few stocks have this measure.</div>;
  const q = (p: number) => xs[Math.round(p * (xs.length - 1))];
  const lo = q(0.01), hi = q(0.99), width = (hi - lo) / BINS || 1;
  const counts = new Array<number>(BINS).fill(0);
  xs.forEach((v) => { counts[Math.max(0, Math.min(BINS - 1, Math.floor((v - lo) / width)))] += 1; });
  const f = (v: number) => fmt(v, measure.fmt);
  const med = median(xs)!;
  const medBin = Math.max(0, Math.min(BINS - 1, Math.floor((med - lo) / width)));
  const bars = counts.map((c, i) => ({
    label: i === 0 || i === BINS - 1 || i === Math.floor(BINS / 2) ? f(lo + (i + 0.5) * width) : "",
    value: c, highlight: i === medBin,
    tip: <>
      <b>{c} stocks</b><br />
      {i === 0 ? `${f(lo + width)} or less` : i === BINS - 1 ? `${f(hi - width)} or more` : `${f(lo + i * width)} to ${f(lo + (i + 1) * width)}`}
      {i === medBin && <><br />Contains the median ({f(med)})</>}
    </>,
  }));
  return (
    <div className="stack" style={{ gap: 4 }}>
      <Columns bars={bars} format={(v) => v.toFixed(0)} height={190} maxBar={40} />
      <div className="row muted" style={{ fontSize: 12, gap: 16 }}>
        <span>{xs.length} of {rows.length} stocks have a value</span>
        <span>10th percentile <b style={{ color: "var(--text)" }}>{f(q(0.1))}</b></span>
        <span>Median <b style={{ color: "var(--text)" }}>{f(med)}</b> (darker bar)</span>
        <span>90th percentile <b style={{ color: "var(--text)" }}>{f(q(0.9))}</b></span>
        <span>The outer bars include everything beyond the 1st and 99th percentiles.</span>
      </div>
    </div>
  );
}

function Extremes({ rows, measure, top }: { rows: Row[]; measure: Measure; top: boolean }) {
  const sorted = rows.filter((r) => num(r[measure.key]) !== null)
    .sort((a, b) => (num(a[measure.key])! - num(b[measure.key])!) * (top ? -1 : 1)).slice(0, 10);
  return (
    <div>
      <h3>{top ? "Highest" : "Lowest"} {measure.label}</h3>
      <table className="plain">
        <tbody>
          {sorted.map((r) => (
            <tr key={String(r.ticker)}>
              <td><a href={`#/stock/${r.ticker}`}><b>{r.ticker}</b></a></td>
              <td className="name">{r.name}</td>
              <td className="name muted">{r.sector}</td>
              <td className={`num ${measure.better !== 0 ? rankClass(num(r[`${measure.key}__pct`])) : ""}`}>{fmt(r[measure.key], measure.fmt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Market({ shared }: { shared: Shared }) {
  const { meta, byKey, screen } = shared;
  const rows = useMemo(() => withComposite(shared.rows, screen.weights), [shared.rows, screen.weights]);
  const [key, setKey] = useState("value_score");
  const measure = byKey[key];
  const choices = meta.catalog.measures.filter((m) => m.fmt !== "flag");
  return (
    <div className="stack">
      <SectorHeatmap rows={rows} byKey={byKey} />
      <div className="panel stack">
        <div className="row">
          <h2>Distribution across the universe</h2>
          <MeasureSelect measures={choices} value={key} onChange={setKey} />
          <Info measure={measure} />
          <span className="muted">{measure.about}</span>
        </div>
        <Distribution rows={rows} measure={measure} />
        <div className="grid2">
          <Extremes rows={rows} measure={measure} top />
          <Extremes rows={rows} measure={measure} top={false} />
        </div>
      </div>
    </div>
  );
}
