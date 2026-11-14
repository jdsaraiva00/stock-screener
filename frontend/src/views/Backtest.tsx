import { useMemo, useState } from "react";
import { api, type BacktestResult } from "../api";
import type { Shared } from "../App";
import { TimeChart, type Line } from "../components/TimeChart";
import { MISSING, fmt, num } from "../format";
import { bounds, toBacktestFilters } from "../screen";
import { Menu, WeightsEditor } from "./Screener";

const growth = (v: number) => `${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}×`;
const signed = (v: unknown, digits = 2) => (num(v) === null ? MISSING : num(v)!.toFixed(digits));

const STAT_ROWS: [string, string, "pct" | "ratio", string][] = [
  ["cagr", "Annual return (CAGR)", "pct", "Compound annual growth rate, after the cost setting."],
  ["volatility", "Volatility", "pct", "Annualised standard deviation of daily returns."],
  ["sharpe", "Sharpe ratio", "ratio", "Average daily return above the risk-free rate, over its standard deviation, annualised."],
  ["max_drawdown", "Maximum drawdown", "pct", "Largest fall from a previous peak."],
  ["total_return", "Total return", "pct", "Over the whole simulated period."],
  ["turnover_annual", "Turnover per year", "pct", "Share of the portfolio replaced per year (one-way), excluding the initial purchase."],
];
const HOLDINGS_PAGE = 12;

export function Backtest({ shared }: { shared: Shared }) {
  const { meta, byKey, screen, setScreen } = shared;
  const [topN, setTopN] = useState(30);
  const [rebalance, setRebalance] = useState<"monthly" | "quarterly">("quarterly");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [cost, setCost] = useState(10);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [log, setLog] = useState(true);
  const [shown, setShown] = useState(HOLDINGS_PAGE);

  const run = async () => {
    setRunning(true); setError(null);
    try {
      setResult(await api.backtest({
        weights: screen.weights, filters: toBacktestFilters(screen, byKey), sectors: screen.sectors,
        exclude_financials: screen.excludeFinancials, top_n: topN, rebalance,
        start: start || null, end: end || null, cost_bps: cost,
      }));
      setShown(HOLDINGS_PAGE);
    } catch (e) { setError((e as Error).message); setResult(null); }
    finally { setRunning(false); }
  };

  const lines: Line[] = useMemo(() => {
    if (!result) return [];
    const out: Line[] = [{ name: `Top ${result.config.top_n} portfolio`, color: "series-1", values: result.curve.portfolio }];
    if (result.curve.benchmark) out.push({ name: "S&P 500, total return", color: "series-2", values: result.curve.benchmark });
    out.push({ name: result.coverage.membership ? "All members at each date, equal-weighted" : "All current members, equal-weighted",
      color: "muted", values: result.curve.universe, dashed: true });
    return out;
  }, [result]);

  const weightText = Object.entries(screen.weights).filter(([, w]) => w > 0)
    .map(([k, w]) => `${byKey[k]?.label ?? k} ×${w}`).join(", ") || "none";
  const filterText = [
    ...screen.filters.map((f) => {
      const b = bounds(f, byKey[f.key]);
      if (b.lo === null && b.hi === null) return null;
      const what = `${byKey[f.key]?.label ?? f.key}${f.basis === "value" ? "" : f.basis === "pct" ? " (universe rank)" : " (sector rank)"}`;
      return f.op === "between" ? `${what} between ${f.a} and ${f.b}` : `${what} ${f.op === ">=" ? "at least" : "at most"} ${f.a}`;
    }).filter(Boolean),
    ...(screen.sectors.length ? [`sectors: ${screen.sectors.join(", ")}`] : []),
    ...(screen.excludeFinancials ? ["financials excluded"] : []),
  ].join("; ") || "none";

  const columns: ["portfolio" | "benchmark" | "universe", string][] = [
    ["portfolio", "Portfolio"], ["benchmark", "S&P 500, total return"], ["universe", "All current members, equal-weighted"],
  ];

  return (
    <div className="stack">
      <div className="panel stack">
        <div className="row">
          <h2>Backtest</h2>
          <span className="muted">
            Each period: rank the stocks that pass the filters by the composite, hold the top N in equal weights,
            trade at the next day's close.
          </span>
        </div>
        <dl className="kv">
          <dt>Composite weights</dt>
          <dd>
            {weightText}{" "}
            <Menu label="Change" wide>
              <WeightsEditor weights={screen.weights} measures={meta.catalog.measures} defaults={meta.catalog.default_weights}
                onChange={(weights) => setScreen({ ...screen, weights })} />
            </Menu>
          </dd>
          <dt>Filters</dt><dd>{filterText} <a href="#/screener">Edit in the screener</a></dd>
        </dl>
        <div className="row" style={{ gap: 14 }}>
          <label className="row" style={{ gap: 4 }}>Top N
            <input type="number" min={1} max={200} value={topN} onChange={(e) => setTopN(Number(e.target.value))} style={{ width: 64 }} />
          </label>
          <label className="row" style={{ gap: 4 }}>Rebalance
            <select value={rebalance} onChange={(e) => setRebalance(e.target.value as "monthly" | "quarterly")}>
              <option value="quarterly">Quarterly</option>
              <option value="monthly">Monthly</option>
            </select>
          </label>
          <label className="row" style={{ gap: 4 }}>From
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="row" style={{ gap: 4 }}>To
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </label>
          <label className="row" style={{ gap: 4 }} title="Charged on every dollar bought and on every dollar sold">Cost per trade
            <input type="number" min={0} step={1} value={cost} onChange={(e) => setCost(Number(e.target.value))} style={{ width: 64 }} />
            <span className="muted">basis points (0.01%)</span>
          </label>
          <button type="button" className="primary" onClick={run} disabled={running}>{running ? "Running…" : "Run backtest"}</button>
          {running && <span className="muted">The first run takes up to about 15 seconds; later runs reuse it.</span>}
        </div>
        <span className="muted">Leave the dates empty to use everything available.</span>
        {error && <div className="error">{error}</div>}
      </div>

      <div className="panel stack" style={{ gap: 6 }}>
        <h2>Read this before trusting a result</h2>
        <div className="notice">
          <b>Survivorship bias.</b> On each date only that date's index members are eligible, using the record of
          additions and removals (reasonably complete from 2011). Companies that left the index are included when
          free data has their prices: that covers most of those dropped for size, but few of those acquired and
          almost none that went bankrupt, so results are still biased upward, less than with today's members alone.
          {result?.coverage.membership && (
            <> With this cache: {result.coverage.former_members} former members in the record, {result.coverage.former_with_prices} with
            prices and {result.coverage.former_with_fundamentals} with filed fundamentals.</>
          )}
          {result && !result.coverage.membership && <> This cache has no membership record yet: run a data update to fetch it.</>}
          {" "}The dashed line, all members at each date held in equal weights, shows how large the universe effect is
          on its own: a screen is only interesting to the extent it beats that line, not the index.
        </div>
        <div className="notice">
          <b>Date coverage.</b>{" "}
          {result
            ? <>This run covers {result.coverage.first_day} to {result.coverage.last_date} ({result.coverage.rebalances} rebalances). </>
            : <>Prices in the cache start in 2000. </>}
          Filed fundamentals (SEC XBRL data) start around 2009–2011, so a screen that uses them cannot start earlier.
          Fundamentals are used only from the date each annual report was filed, never from the fiscal year end.
        </div>
        <div className="notice">
          <b>Published anomalies fade.</b> McLean and Pontiff (2016) find that the return to published anomalies is
          about a quarter lower out of sample and more than half lower after publication. Every measure here comes
          from published research. Treat results as indicative only.
          <span className="muted"> McLean, R. D. and Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? Journal of Finance 71(1).</span>
        </div>
        {result?.notes.slice(2).map((n) => <div key={n} className="notice">{n}</div>)}
      </div>

      {result && (
        <>
          <div className="panel">
            <div className="row" style={{ marginBottom: 4 }}>
              <h2>Growth of 1</h2>
              <label className="row" style={{ gap: 4 }}>
                <input type="checkbox" checked={log} onChange={(e) => setLog(e.target.checked)} />Log scale
              </label>
              <span className="muted">After costs. All three lines include dividends.</span>
            </div>
            <TimeChart dates={result.curve.dates} lines={lines} format={growth} log={log} height={340} />
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Statistic</th>{columns.map(([k, label]) => result.stats[k] && <th key={k} className="num">{label}</th>)}<th>Meaning</th></tr>
              </thead>
              <tbody>
                {STAT_ROWS.map(([key, label, kind, about]) => (
                  <tr key={key}>
                    <td>{label}</td>
                    {columns.map(([k]) => result.stats[k] && (
                      <td key={k} className="num">{key in result.stats[k]! ? fmt(result.stats[k]![key], kind) : ""}</td>
                    ))}
                    <td className="muted">{about}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="panel stack">
            <div className="row">
              <h2>Does it add anything beyond known factors?</h2>
              <span className="muted">
                Monthly returns above the risk-free rate, regressed on the Fama-French factors (Ken French Data Library).
                Alpha is what the factors leave unexplained. As a rule of thumb, |t| below 2 is indistinguishable from zero.
              </span>
            </div>
            {result.regression.length === 0 && <span className="muted">Fewer than 24 whole months with factor data: no regression.</span>}
            <div className="grid2">
              {result.regression.map((m) => {
                const alpha = m.terms[0];
                const clear = num(alpha.t) !== null && Math.abs(num(alpha.t)!) >= 2;
                return (
                  <div key={m.model}>
                    <h3>{m.model}</h3>
                    <table className="plain">
                      <thead><tr><th>Term</th><th className="num">Estimate</th><th className="num">t-statistic</th></tr></thead>
                      <tbody>
                        {m.terms.map((t) => (
                          <tr key={t.name}><td>{t.name}</td><td className="num">{signed(t.coef, 3)}</td><td className="num">{signed(t.t)}</td></tr>
                        ))}
                      </tbody>
                    </table>
                    <div className="muted" style={{ marginTop: 4 }}>
                      Alpha {signed(m.alpha_annual_pct, 1)}% a year, {clear ? "statistically distinguishable from zero" : "not distinguishable from zero"} here
                      (and still subject to the survivorship bias above). R² {signed(m.r_squared)}, {m.months} months, {m.first_month} to {m.last_month}.
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <h2 style={{ marginBottom: 6 }}>Holdings at each rebalance</h2>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr><th>Chosen on</th><th className="num">Eligible</th><th className="num">Replaced</th><th>Holdings, best score first</th></tr>
                </thead>
                <tbody>
                  {[...result.holdings].reverse().slice(0, shown).map((h) => (
                    <tr key={h.date}>
                      <td style={{ whiteSpace: "nowrap" }}>{h.date}</td>
                      <td className="num">{h.eligible}</td>
                      <td className="num">{fmt(h.turnover, "pct")}</td>
                      <td style={{ lineHeight: 1.7, whiteSpace: "normal" }}>
                        {h.tickers.length === 0 && <span className="muted">Nothing passed the screen: cash</span>}
                        {h.tickers.map((t, i) => (
                          <a key={t} href={`#/stock/${t}`} title={`Composite ${fmt(h.scores[i], "pctile")}`} style={{ marginRight: 8 }}>{t}</a>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {result.holdings.length > shown && (
              <div className="row" style={{ marginTop: 8 }}>
                <button type="button" onClick={() => setShown(shown + 40)}>Show earlier rebalances</button>
                <button type="button" onClick={() => setShown(result.holdings.length)}>Show all {result.holdings.length}</button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
