import { useState, type ReactNode } from "react";

/** A tooltip that follows the pointer. Returns handlers and the element to render. */
export function useTip(): [(e: React.MouseEvent, content: ReactNode) => void, () => void, ReactNode] {
  const [tip, setTip] = useState<{ x: number; y: number; content: ReactNode } | null>(null);
  const show = (e: React.MouseEvent, content: ReactNode) => setTip({ x: e.clientX, y: e.clientY, content });
  const hide = () => setTip(null);
  const node = tip && (
    <div className="tip" style={{ left: Math.min(tip.x + 12, window.innerWidth - 290), top: tip.y + 14 }}>{tip.content}</div>
  );
  return [show, hide, node];
}

export interface Bar { label: string; value: number | null; tip?: ReactNode; highlight?: boolean }

/**
 * Columns from a zero baseline. One hue; a highlighted bar uses the full colour
 * and the rest a lighter step. Rounded at the data end, square at the baseline,
 * with a surface-colour gap between neighbours. Missing values draw nothing.
 */
export function Columns({ bars, format, height = 150, everyLabel = 1, maxBar = 24 }: {
  bars: Bar[]; format: (v: number) => string; height?: number; everyLabel?: number; maxBar?: number;
}) {
  const [show, hide, tip] = useTip();
  const width = 600, padL = 58, padB = 18, padT = 8;
  const values = bars.map((b) => b.value).filter((v): v is number => v !== null);
  if (!values.length) return <div className="muted" style={{ height }}>No data</div>;
  const max = Math.max(0, ...values), min = Math.min(0, ...values);
  const span = max - min || 1;
  const plotH = height - padB - padT;
  const y = (v: number) => padT + ((max - v) / span) * plotH;
  const slot = (width - padL) / bars.length;
  const w = Math.max(1, Math.min(maxBar, slot - 2));
  const ticks = [max, min < 0 ? min : null, 0].filter((t, i, a): t is number => t !== null && a.indexOf(t) === i);
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height }} role="img" preserveAspectRatio="none">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={width} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
          </g>
        ))}
        {bars.map((b, i) => {
          if (b.value === null) return null;
          const x = padL + i * slot + (slot - w) / 2;
          const top = Math.min(y(b.value), y(0)), h = Math.max(1, Math.abs(y(b.value) - y(0)));
          const r = Math.min(3, w / 2, h);
          const up = b.value >= 0;
          const path = up
            ? `M${x},${top + h} V${top + r} Q${x},${top} ${x + r},${top} H${x + w - r} Q${x + w},${top} ${x + w},${top + r} V${top + h} Z`
            : `M${x},${top} V${top + h - r} Q${x},${top + h} ${x + r},${top + h} H${x + w - r} Q${x + w},${top + h} ${x + w},${top + h - r} V${top} Z`;
          return (
            <g key={i}>
              <path d={path} fill="var(--series-1)" opacity={b.highlight === false ? 0.45 : 1} />
              <rect x={padL + i * slot} y={padT} width={slot} height={plotH} fill="transparent"
                onMouseMove={(e) => show(e, b.tip ?? <><b>{b.label}</b>: {format(b.value!)}</>)} onMouseLeave={hide} />
            </g>
          );
        })}
      </svg>
      <div style={{ position: "absolute", left: 0, top: 0, width: `${(padL / width) * 100}%`, height, pointerEvents: "none" }}>
        {ticks.map((t) => (
          <span key={t} className="muted num" style={{ position: "absolute", right: 6, top: y(t) - 8, fontSize: 11 }}>{format(t)}</span>
        ))}
      </div>
      <div style={{ display: "flex", marginLeft: `${(padL / width) * 100}%`, marginTop: -padB + 2 }}>
        {bars.map((b, i) => (
          <span key={i} className="muted" style={{ flex: 1, textAlign: "center", fontSize: 10, overflow: "hidden", whiteSpace: "nowrap" }}>
            {i % everyLabel === 0 ? b.label : ""}
          </span>
        ))}
      </div>
      {tip}
    </div>
  );
}

/**
 * Where one value sits among its peers: a dot per peer on a line, the subject
 * marked with a ring. Peers beyond the 2nd-98th percentile are drawn at the edge.
 */
export function PeerStrip({ peers, subject, format, flip }: {
  peers: { ticker: string; value: number }[]; subject: number | null; format: (v: number) => string; flip?: boolean;
}) {
  const [show, hide, tip] = useTip();
  if (peers.length < 3) return <span className="muted">Too few peers with this measure</span>;
  const sorted = peers.map((p) => p.value).sort((a, b) => a - b);
  const q = (p: number) => sorted[Math.min(sorted.length - 1, Math.max(0, Math.round(p * (sorted.length - 1))))];
  const lo = q(0.02), hi = q(0.98), span = hi - lo || 1;
  const x = (v: number) => { const t = Math.max(0, Math.min(1, (v - lo) / span)); return `${2 + (flip ? 1 - t : t) * 96}%`; };
  return (
    <div className="strip">
      <svg>
        <line x1="2%" x2="98%" y1="7" y2="7" stroke="var(--border-strong)" strokeWidth="1" />
        {peers.map((p) => (
          <circle key={p.ticker} cx={x(p.value)} cy="7" r="2.5" fill="var(--text-3)" opacity="0.55"
            onMouseMove={(e) => show(e, <><b>{p.ticker}</b>: {format(p.value)}</>)} onMouseLeave={hide} />
        ))}
        {subject !== null && <circle cx={x(subject)} cy="7" r="4.5" fill="var(--series-1)" stroke="var(--surface)" strokeWidth="2" />}
      </svg>
      {tip}
    </div>
  );
}
