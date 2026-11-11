import { ColorType, LineSeries, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";

export interface Line { name: string; color: "series-1" | "series-2" | "muted"; values: (number | null)[]; dashed?: boolean }

/** Bumps whenever the colour theme changes, so charts can re-read their colours. */
export function useThemeVersion(): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    const bump = () => setV((x) => x + 1);
    const observer = new MutationObserver(bump);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", bump);
    return () => { observer.disconnect(); media.removeEventListener("change", bump); };
  }, []);
  return v;
}

const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/**
 * Time series on one shared axis (never two scales). `from` limits the visible
 * range. A legend row above the plot names every line and shows the values
 * under the pointer, so identity never depends on colour alone.
 */
export function TimeChart({ dates, lines, from, format, log, height = 320 }: {
  dates: string[]; lines: Line[]; from?: string | null; format: (v: number) => string; log?: boolean; height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  const theme = useThemeVersion();
  const [hover, setHover] = useState<{ date: string; values: (number | null)[] } | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const colorOf = (c: Line["color"]) => (c === "muted" ? cssVar("--text-3") : cssVar(`--${c}`));
    const chart: IChartApi = createChart(el.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: cssVar("--surface") }, textColor: cssVar("--text-2"), attributionLogo: false, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: cssVar("--border") } },
      rightPriceScale: { borderVisible: false, mode: log ? 1 : 0 },
      timeScale: { borderVisible: false },
      crosshair: { horzLine: { visible: false, labelVisible: false } },
      localization: { priceFormatter: format, locale: "en-US" },
      handleScroll: false, handleScale: false,
    });
    const series: ISeriesApi<"Line">[] = lines.map((line) => {
      const s = chart.addSeries(LineSeries, {
        color: colorOf(line.color), lineWidth: 2, lineStyle: line.dashed ? 2 : 0,
        priceLineVisible: false, lastValueVisible: false, crosshairMarkerRadius: 4,
      });
      const data = [];
      for (let i = 0; i < dates.length; i++) {
        const v = line.values[i];
        if (v !== null && v !== undefined && (!from || dates[i] >= from)) data.push({ time: dates[i] as Time, value: v });
      }
      s.setData(data);
      return s;
    });
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((p) => {
      if (!p.time) { setHover(null); return; }
      setHover({
        date: String(p.time),
        values: series.map((s) => { const d = p.seriesData.get(s) as { value?: number } | undefined; return d?.value ?? null; }),
      });
    });
    return () => chart.remove();
  }, [dates, lines, from, log, theme, format]);

  const last = (line: Line) => { for (let i = line.values.length - 1; i >= 0; i--) if (line.values[i] !== null) return line.values[i]; return null; };
  return (
    <div>
      <div className="row" style={{ gap: 14, minHeight: 20, fontSize: 12 }}>
        <span className="muted" style={{ width: 78 }}>{hover ? hover.date : dates[dates.length - 1]}</span>
        {lines.map((line, i) => {
          const v = hover ? hover.values[i] : last(line);
          return (
            <span key={line.name} className="row" style={{ gap: 5 }}>
              <svg width="16" height="8" aria-hidden="true">
                <line x1="0" y1="4" x2="16" y2="4" strokeWidth="2" strokeDasharray={line.dashed ? "4 3" : undefined}
                  stroke={line.color === "muted" ? "var(--text-3)" : `var(--${line.color})`} />
              </svg>
              {line.name} <b className="num">{v === null ? "—" : format(v)}</b>
            </span>
          );
        })}
      </div>
      <div ref={el} style={{ width: "100%", height }} />
    </div>
  );
}
