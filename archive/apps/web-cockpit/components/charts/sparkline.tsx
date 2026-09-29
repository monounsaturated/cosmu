// A tiny axis-less inline equity sparkline (Iris Bento). Renders the SHAPE of a strategy's paper equity at a
// glance inside a table row — no axes, no crosshair, no gradient, no interaction. Up/down colour is derived
// from the series direction (last vs first), matching the EquityChart convention.
//
// HONESTY: pass only a REAL (downsampled) series. With fewer than 2 finite points it renders NOTHING — a single
// dot or a flat fabricated line would be misleading. The engine sends `spark` only for tracks that have genuinely
// traded on paper (null otherwise), so an un-traded row shows a blank cell, never a manufactured trend.

type SparklineProps = {
  /** Compact equity series (already downsampled server-side). null/short → renders nothing. */
  values?: number[] | null;
  width?: number;
  height?: number;
  /** Override the up/down auto-colour. */
  color?: string;
};

export function Sparkline({ values, width = 84, height = 22, color }: SparklineProps) {
  const v = (values ?? []).filter((x) => Number.isFinite(x));
  if (v.length < 2) return null;

  const W = 100;
  const H = 30;
  const PAD = 2;
  const mn = Math.min(...v);
  const mx = Math.max(...v);
  const rng = mx - mn || Math.abs(mx) * 0.01 || 1;
  const X = (i: number) => (i / (v.length - 1)) * W;
  const Y = (val: number) => PAD + (H - PAD * 2) * (1 - (val - mn) / rng);
  const pts = v.map((val, i) => `${X(i).toFixed(1)},${Y(val).toFixed(1)}`).join(" ");
  const stroke = color ?? (v[v.length - 1] >= v[0] ? "var(--up)" : "var(--down)");

  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={stroke}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
