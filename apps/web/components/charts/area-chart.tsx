import type { Point } from "@cosmu/contracts-ts";

function buildPath(points: Point[], width: number, height: number, pad: number) {
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  const coords = points.map((p, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * width;
    const y = height - pad - ((p.value - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  // Catmull-Rom → cubic bezier smoothing for a clean curve.
  let d = `M ${coords[0][0].toFixed(2)} ${coords[0][1].toFixed(2)}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[i - 1] ?? coords[i];
    const p1 = coords[i];
    const p2 = coords[i + 1];
    const p3 = coords[i + 2] ?? p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C ${c1x.toFixed(2)} ${c1y.toFixed(2)}, ${c2x.toFixed(2)} ${c2y.toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return { d, last: coords[coords.length - 1] };
}

export function AreaChart({
  points,
  color = "var(--color-iris)",
  height = 240
}: {
  points: Point[];
  color?: string;
  height?: number;
}) {
  const width = 760;
  const pad = 14;
  const { d, last } = buildPath(points, width, height, pad);
  const gid = `area-${Math.round(Math.abs(points[0]?.value ?? 0))}`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      style={{ height }}
      preserveAspectRatio="none"
      role="img"
      aria-label="Pooled wallet equity curve"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((f) => (
        <line
          key={f}
          x1="0"
          x2={width}
          y1={height * f}
          y2={height * f}
          stroke="var(--color-border)"
          strokeOpacity="0.5"
          strokeDasharray="2 6"
        />
      ))}
      <path d={`${d} L ${width} ${height} L 0 ${height} Z`} fill={`url(#${gid})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r="4.5" fill={color} />
      <circle cx={last[0]} cy={last[1]} r="9" fill={color} fillOpacity="0.18" />
    </svg>
  );
}
