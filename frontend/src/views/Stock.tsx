import { useEffect, useMemo, useState } from "react";
import { api, toRows, type Measure, type Row, type StockDetail } from "../api";
import type { Shared } from "../App";
import { Info } from "../components/Info";
import { Columns, PeerStrip } from "../components/Svg";
import { TimeChart, type Line } from "../components/TimeChart";
import { MISSING, ageLabel, fmt, millions, money, num, ordinal, shortDate } from "../format";
import { rankClass } from "../scale";
import { compositeOf } from "../screen";

interface Part { label: string; value: string; note?: string; cls?: string }

const yesNo = (v: unknown) => (num(v) === null ? MISSING : num(v) ? "Yes" : "No");
const flagClass = (v: unknown) => (num(v) === null ? "" : num(v) ? "rk rk-g2" : "rk rk-b2");
const pct = (v: unknown) => fmt(v, "pct");
const ratio = (v: unknown) => fmt(v, "ratio");

function piotroskiParts(r: Row): Part[] {
  const vs = (a: string, b: string, f: (v: unknown) => string) => `${f(r[`f_v_${a}`])} vs ${f(r[`f_v_${b}`])} a year earlier`;
  const rows: [string, string, string][] = [
    ["f_roa", "Positive return on assets", `Net income / beginning assets: ${pct(r.f_v_roa)}`],
    ["f_cfo", "Positive operating cash flow", `Operating cash flow / beginning assets: ${pct(r.f_v_cfo)}`],
    ["f_droa", "Return on assets improved", vs("roa", "roa_prev", pct)],
    ["f_accrual", "Cash flow exceeds earnings", `Cash flow ${pct(r.f_v_cfo)} vs earnings ${pct(r.f_v_roa)} of assets`],
    ["f_dlever", "Leverage did not rise", `Long-term debt / average assets: ${vs("lever", "lever_prev", pct)}`],
    ["f_dliquid", "Liquidity improved", `Current ratio: ${vs("liquid", "liquid_prev", ratio)}`],
    ["f_eq_offer", "No new shares", `Shares: ${millions(r.f_v_shares)}m vs ${millions(r.f_v_shares_prev)}m a year earlier`],
    ["f_dmargin", "Gross margin improved", vs("margin", "margin_prev", pct)],
    ["f_dturn", "Asset turnover improved", vs("turn", "turn_prev", ratio)],
  ];
  return rows.map(([key, label, note]) => ({ label, value: yesNo(r[key]), note, cls: flagClass(r[key]) }));
}

function weightedParts(r: Row, spec: [string, string, number][]): Part[] {
  return spec.map(([key, label, weight]) => {
    const v = num(r[key]);
    return {
      label, value: ratio(v),
      note: v === null ? `weight ${weight}` : `× ${weight} = ${(v * weight).toFixed(2)}`,
    };
  });
}

function ScoreCard({ m, row, peers, parts, footer }: {
  m: Measure; row: Row; peers: Row[]; parts?: Part[]; footer?: string;
}) {
  const value = num(row[m.key]);
  const universe = num(row[`${m.key}__pct`]), sector = num(row[`${m.key}__spct`]);
  const peerValues = peers.map((p) => ({ ticker: String(p.ticker), value: num(p[m.key]) }))
    .filter((p): p is { ticker: string; value: number } => p.value !== null);
  return (
    <div className="panel stack" style={{ gap: 6 }}>
      <div className="score-head">
        <h2>{m.label}</h2><Info measure={m} />
        <span className="spacer" />
        <span className="score-value">{fmt(value, m.fmt)}</span>
      </div>
      {m.better !== 0 && (
        <div className="row" style={{ gap: 6, fontSize: 12 }}>
          <span className={`chip ${rankClass(universe)}`} style={{ color: "var(--text)" }}>
            Universe: {universe === null ? MISSING : `${ordinal(universe)} percentile`}
          </span>
          <span className={`chip ${rankClass(sector)}`} style={{ color: "var(--text)" }}>
            Sector: {sector === null ? MISSING : `${ordinal(sector)} percentile`}
          </span>
        </div>
      )}
      {value !== null && (
        <div>
          <PeerStrip peers={peerValues} subject={value} format={(v) => fmt(v, m.fmt)} flip={m.better < 0} />
          <div className="row muted" style={{ justifyContent: "space-between", fontSize: 11 }}>
            <span>{m.better === 0 ? "lower" : "less favourable"}</span>
            <span>{peerValues.length} sector peers</span>
            <span>{m.better === 0 ? "higher" : "more favourable"}</span>
          </div>
        </div>
      )}
      {footer && <div className="muted">{footer}</div>}
      {parts && parts.length > 0 && (
        <table className="plain">
          <tbody>
            {parts.map((p) => (
              <tr key={p.label}>
                <td>{p.label}</td>
                <td className={`num ${p.cls ?? ""}`}>{p.value}</td>
                <td className="muted">{p.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const RANGES: [string, number | null][] = [["1Y", 1], ["3Y", 3], ["5Y", 5], ["10Y", 10], ["All", null]];
const usd = (v: number) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function Stock({ ticker, shared }: { ticker: string; shared: Shared }) {
  const { byKey, meta, screen } = shared;
  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<number | null>(5);
  const [total, setTotal] = useState(false);

  useEffect(() => {
    setDetail(null); setError(null);
    api.stock(ticker).then(setDetail).catch((e: Error) => setError(e.message));
  }, [ticker]);

  const prices = useMemo(() => {
    if (!detail) return null;
    const p = toRows(detail.prices);
    return { dates: p.map((r) => String(r.date)), close: p.map((r) => num(r.close)), adj: p.map((r) => num(r.adj_close)) };
  }, [detail]);
  const lines: Line[] = useMemo(() => (prices ? [{
    name: total ? "Total return price (dividends reinvested)" : "Close (split-adjusted)",
    color: "series-1", values: total ? prices.adj : prices.close,
  }] : []), [prices, total]);

  if (error) return <div className="error">Could not load {ticker}: {error} <a href="#/screener">Back to the screener</a></div>;
  if (!detail || !prices) return <div className="muted">Loading {ticker}…</div>;

  const r: Row = { ...detail.row };
  const composite = compositeOf(r, screen.weights);
  r.composite = composite; r.composite__pct = composite; r.composite__spct = compositeOf(r, screen.weights, "spct");
  const peers = toRows(detail.peers);
  const financial = Boolean(r.financial);
  const from = range && prices.dates.length
    ? `${Number(prices.dates[prices.dates.length - 1].slice(0, 4)) - range}${prices.dates[prices.dates.length - 1].slice(4)}` : null;
  const hist = detail.history;
  const years = hist.slice(-12);
  const bar = (key: string, scale = 1) => years.map((h) => ({
    label: `FY${String(h.period_end).slice(2, 4)}`, value: num(h[key]) === null ? null : num(h[key])! / scale,
  }));
  const card = (key: string, parts?: Part[], footer?: string) =>
    byKey[key] && <ScoreCard key={key} m={byKey[key]} row={r} peers={peers} parts={parts} footer={footer} />;
  const sub = (keys: string[]): Part[] => keys.filter((k) => byKey[k] || meta.catalog.components[k]).map((k) => {
    const m = byKey[k], c = meta.catalog.components[k];
    const p = num(r[`${k}__pct`]);
    return {
      label: m?.label ?? c.label, value: fmt(r[k], m?.fmt ?? c.fmt),
      note: p !== null ? `${ordinal(p)} percentile in universe` : c?.about, cls: m && m.better !== 0 ? rankClass(p) : "",
    };
  });
  const z = num(r.altman_z), mScore = num(r.beneish_m);
  const naNote = "Not applicable: this score is not meaningful for banks, insurers and other financial companies.";
  const known = num(r.f_signals_known);
  const sec = `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${r.cik}&type=10-K`;

  return (
    <div className="stack">
      <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
        <a href="#/screener">← Screener</a>
        <h1>{r.ticker} <span style={{ fontWeight: 400 }}>{r.name}</span></h1>
        <span className="chip">{r.sector}</span>
        <span className="muted">{r.sub_industry}</span>
        {financial && <span className="chip">Financial company</span>}
      </div>

      <div className="grid3">
        <div className="panel">
          <dl className="kv">
            <dt>Price</dt><dd className="num">${fmt(r.price, "ratio")} <span className="muted">on {shortDate(String(r.price_date ?? ""))}</span></dd>
            <dt>Market cap</dt><dd className="num">{fmt(r.market_cap, "money")} <span className="muted">({r.market_cap_source === "provider" ? "Yahoo" : r.market_cap_source ?? "unknown"})</span></dd>
            <dt>Enterprise value</dt><dd className="num">{fmt(r.enterprise_value, "money")}</dd>
            <dt>Composite</dt><dd className="num">{fmt(r.composite, "pctile")} <span className="muted">with your current weights</span></dd>
          </dl>
        </div>
        <div className="panel">
          <dl className="kv">
            <dt>Fiscal year used</dt><dd>ending {shortDate(String(r.period_end ?? ""))}</dd>
            <dt>Annual report filed</dt><dd>{shortDate(String(r.available ?? ""))} <a href={sec} target="_blank" rel="noreferrer">SEC filings</a></dd>
            <dt>SEC industry</dt><dd>{detail.filer?.sic ?? MISSING} {detail.filer?.sic_description ?? ""}</dd>
            <dt>Yahoo sector</dt><dd>{detail.profile?.sector ?? MISSING} / {detail.profile?.industry ?? MISSING}</dd>
          </dl>
        </div>
        <div className="panel">
          <dl className="kv">
            <dt>Prices fetched</dt><dd>{ageLabel(detail.fetched.prices)}</dd>
            <dt>Fundamentals fetched</dt><dd>{ageLabel(detail.fetched.fundamentals)}</dd>
            <dt>Profile fetched</dt><dd>{ageLabel(detail.fetched.profile)}</dd>
            <dt>Scores computed</dt><dd>{ageLabel(meta.computed_at)}</dd>
          </dl>
        </div>
      </div>

      <div className="panel stack" style={{ gap: 4 }}>
        <h2>Insights <span className="muted" style={{ fontWeight: 400 }}>from fixed rules on the numbers below</span></h2>
        {detail.insights.length === 0 && <span className="muted">No rule is triggered for this stock.</span>}
        {detail.insights.map((i) => (
          <div key={i.text} className={`insight tone-${i.tone}`}>
            {i.text}{" "}
            <span className="muted">
              ({i.measures.map((k) => `${byKey[k]?.label ?? k}: ${fmt(r[k], byKey[k]?.fmt ?? "ratio")}`).join(" · ")})
            </span>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="row" style={{ marginBottom: 4 }}>
          <h2>Price</h2>
          <span className="tabs">
            {RANGES.map(([label, yrs]) => (
              <button key={label} type="button" className={range === yrs ? "on" : ""} onClick={() => setRange(yrs)}>{label}</button>
            ))}
          </span>
          <label className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={total} onChange={(e) => setTotal(e.target.checked)} />Include dividends
          </label>
          <span className="spacer" />
          {["ret_1m", "ret_3m", "ret_6m", "ret_1y", "ret_3y", "ret_5y"].map((k) => (
            <span key={k} className="muted">{byKey[k]?.label.replace("Return ", "")} <b style={{ color: "var(--text)" }}>{pct(r[k])}</b></span>
          ))}
        </div>
        <TimeChart dates={prices.dates} lines={lines} from={from} format={usd} />
      </div>

      <h2>Fundamental scores</h2>
      <div className="grid3">
        {card("f_score", piotroskiParts(r), known !== null && num(r.f_score) === null ? `Only ${known} of 9 signals can be computed, so no total is shown.` : undefined)}
        {financial ? card("altman_z", [], naNote) : card("altman_z", weightedParts(r, [
          ["z_x1", "X1 working capital / assets", 1.2], ["z_x2", "X2 retained earnings / assets", 1.4],
          ["z_x3", "X3 EBIT / assets", 3.3], ["z_x4", "X4 market cap / liabilities", 0.6], ["z_x5", "X5 revenue / assets", 1.0],
        ]), z === null ? undefined : z < 1.81 ? "Below 1.81: Altman's distress zone." : z < 2.99 ? "Between 1.81 and 2.99: grey zone." : "Above 2.99: safe zone.")}
        {financial ? card("beneish_m", [], naNote) : card("beneish_m", [
          { label: "Constant", value: "-4.84" },
          ...weightedParts(r, [
            ["m_dsri", "DSRI receivables / sales, vs prior year", 0.92], ["m_gmi", "GMI prior / current gross margin", 0.528],
            ["m_aqi", "AQI other long-term assets share, vs prior", 0.404], ["m_sgi", "SGI sales growth", 0.892],
            ["m_depi", "DEPI prior / current depreciation rate", 0.115], ["m_sgai", "SGAI SG&A / sales, vs prior year", -0.172],
            ["m_tata", "TATA (income − cash flow) / assets", 4.679], ["m_lvgi", "LVGI leverage, vs prior year", -0.327],
          ]),
        ], mScore === null ? undefined : mScore > -1.78 ? "Above −1.78: the level Beneish associates with possible manipulation." : "Below −1.78: no manipulation signal.")}
        {card("accruals_cf")}
        {card("accruals_sloan")}
        {card("gross_profitability")}
        {card("asset_growth")}
      </div>

      <h2>Factors</h2>
      <div className="grid3">
        {card("value_score", sub(["book_to_market", "earnings_yield", "ebit_ev", "ev_ebit", "fcf_yield"]))}
        {card("mom_12_1")}
        {card("quality", sub(["q_profitability", "q_growth", "q_safety", "q_gpoa", "q_roe", "q_roa", "q_cfoa", "q_gmar", "q_acc", "q_lev", "q_evol"]))}
        {card("low_risk_score", sub(["beta", "vol_1y"]))}
        {card("max_drawdown_1y", sub(["dist_52w_high", "ma50_gap", "ma200_gap", "trend_up"]))}
      </div>

      <h2>Fundamentals by fiscal year <span className="muted" style={{ fontWeight: 400 }}>as first reported in each annual report; table in USD millions</span></h2>
      <div className="grid3">
        <div className="panel"><h3>Revenue</h3><Columns bars={bar("revenue")} format={money} /></div>
        <div className="panel"><h3>Net income</h3><Columns bars={bar("net_income")} format={money} /></div>
        <div className="panel"><h3>Free cash flow</h3><Columns bars={bar("free_cash_flow")} format={money} /></div>
        <div className="panel"><h3>F-Score</h3><Columns bars={bar("f_score")} format={(v) => v.toFixed(0)} /></div>
        <div className="panel"><h3>Gross profitability (gross profit / assets)</h3><Columns bars={bar("gross_profitability", 0.01)} format={(v) => `${v.toFixed(0)}%`} /></div>
        <div className="panel"><h3>Accruals, cash-flow form (% of assets)</h3><Columns bars={bar("accruals_cf", 0.01)} format={(v) => `${v.toFixed(1)}%`} /></div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Fiscal year end</th><th>Filed</th>
              {["Revenue", "Gross profit", "EBIT", "Net income", "Op. cash flow", "Free cash flow", "Total assets", "Debt", "Equity"].map((h) => <th key={h} className="num">{h}</th>)}
              <th className="num">F-Score</th><th className="num">Beneish M</th><th className="num">Asset growth</th>
            </tr>
          </thead>
          <tbody>
            {[...hist].reverse().map((h) => (
              <tr key={String(h.period_end)}>
                <td>{h.period_end}</td><td className="muted">{h.available}</td>
                {["revenue", "gross_profit", "ebit", "net_income", "cfo", "free_cash_flow", "total_assets", "total_debt", "equity"].map((k) => (
                  <td key={k} className="num">{millions(h[k])}</td>
                ))}
                <td className="num">{fmt(h.f_score, "int")}</td>
                <td className="num">{financial ? "n/a" : fmt(h.beneish_m, "ratio")}</td>
                <td className="num">{pct(h.asset_growth)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {detail.sources && (
        <div className="panel stack" style={{ gap: 4 }}>
          <h2>Where the latest year's figures come from</h2>
          <span className="muted">
            Fiscal year ending {detail.sources.period_end}, from filings available on {detail.sources.available}.
            Market cap {r.market_cap_source === "provider" ? `from Yahoo (${money(num(r.market_cap) ?? 0)})` : "computed as price × filed diluted shares"}.
          </span>
          {Object.keys(detail.sources.derived).length > 0 && (
            <div>
              <b>Computed, not reported:</b>{" "}
              {Object.entries(detail.sources.derived).map(([k, note]) => `${k.replace(/_/g, " ")} = ${note}`).join("; ")}.
            </div>
          )}
          <details>
            <summary>XBRL tags used ({Object.keys(detail.sources.tags).length})</summary>
            <div className="kv" style={{ marginTop: 6 }}>
              {Object.entries(detail.sources.tags).map(([k, tag]) => (
                <div key={k} style={{ display: "contents" }}><dt>{k.replace(/_/g, " ")}</dt><dd>{tag}</dd></div>
              ))}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
