// One colour meaning everywhere: blue = favourable, red = unfavourable, grey = middle.
// (Blue and red, not green and red, so it survives red-green colour blindness.)
// The steps are CSS variables so the light and dark themes each have their own.

/** CSS class for a 0-100 favourability percentile; empty for missing. */
export function rankClass(pct: number | null): string {
  if (pct === null) return "";
  if (pct >= 90) return "rk rk-g3";
  if (pct >= 75) return "rk rk-g2";
  if (pct >= 60) return "rk rk-g1";
  if (pct > 40) return "rk rk-mid";
  if (pct > 25) return "rk rk-b1";
  if (pct > 10) return "rk rk-b2";
  return "rk rk-b3";
}

/** The same scale for a signed number where positive is favourable (returns, changes). */
export function signClass(v: number | null, strong = 0.2): string {
  if (v === null) return "";
  const t = Math.max(-1, Math.min(1, v / strong));
  return rankClass(50 + 50 * t);
}

export const SCALE_STEPS = ["b3", "b2", "b1", "mid", "g1", "g2", "g3"];
