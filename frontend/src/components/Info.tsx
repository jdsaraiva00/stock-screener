import { useEffect, useRef, useState } from "react";
import type { Measure } from "../api";
import { SCALE_STEPS } from "../scale";

/** The "what is this and where does it come from" popover next to a measure name. */
export function Info({ measure }: { measure: Measure }) {
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
  const direction = measure.better > 0 ? "Higher is more favourable." : measure.better < 0 ? "Lower is more favourable." : "";
  return (
    <span className="info" ref={ref}>
      <button type="button" className="info-btn" aria-label={`About ${measure.label}`}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}>i</button>
      {open && (
        <span className="popover" role="dialog" onClick={(e) => e.stopPropagation()}>
          <strong>{measure.label}</strong>
          <span>{measure.about} {direction}</span>
          {measure.citation && <span className="cite">Source: {measure.citation}</span>}
        </span>
      )}
    </span>
  );
}

export function ScaleLegend() {
  return (
    <span className="legend" title="Cell colour shows the percentile rank: blue is favourable, red unfavourable.">
      <span className="muted">Unfavourable</span>
      {SCALE_STEPS.map((s) => <span key={s} className={`swatch rk rk-${s}`} />)}
      <span className="muted">Favourable</span>
    </span>
  );
}
