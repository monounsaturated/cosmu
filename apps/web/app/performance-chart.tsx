type PerformanceSeries = {
  botId: string;
  botName: string;
  botNumber: number;
  points: { at: string; totalUsdValue: number; normalizedValue: number }[];
};

type PerformanceChartProps = {
  series: PerformanceSeries[];
};

const COLORS = ["#60a5fa", "#34d399", "#f472b6", "#f59e0b", "#a78bfa", "#f87171", "#22d3ee", "#84cc16"];

export function PerformanceChart({ series }: PerformanceChartProps) {
  const populatedSeries = series.filter((entry) => entry.points.length > 0);

  if (populatedSeries.length === 0) {
    return <p className="muted">Not enough after-run snapshots yet to compare bot performance curves.</p>;
  }

  const allValues = populatedSeries.flatMap((entry) => entry.points.map((point) => point.normalizedValue));
  const minValue = Math.min(...allValues, 95);
  const maxValue = Math.max(...allValues, 105);
  const valueRange = Math.max(maxValue - minValue, 1);
  const width = 720;
  const height = 260;
  const padding = 24;

  const lines = populatedSeries.map((entry, index) => {
    const points = entry.points.map((point, pointIndex) => {
      const x =
        padding +
        (pointIndex / Math.max(entry.points.length - 1, 1)) * (width - padding * 2);
      const y =
        height -
        padding -
        ((point.normalizedValue - minValue) / valueRange) * (height - padding * 2);

      return `${x},${y}`;
    });

    return {
      botId: entry.botId,
      botLabel: `#${entry.botNumber} ${entry.botName}`,
      color: COLORS[index % COLORS.length],
      path: points.join(" ")
    };
  });

  return (
    <div className="chart-stack">
      <svg viewBox={`0 0 ${width} ${height}`} className="performance-chart" role="img" aria-label="Bot performance comparison">
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#223149" />
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#223149" />
        {lines.map((line) => (
          <polyline
            key={line.botId}
            fill="none"
            stroke={line.color}
            strokeWidth="3"
            strokeLinejoin="round"
            strokeLinecap="round"
            points={line.path}
          />
        ))}
      </svg>

      <div className="chart-legend">
        {lines.map((line) => (
          <span key={line.botId} className="chart-legend-item">
            <span className="chart-legend-swatch" style={{ background: line.color }} />
            {line.botLabel}
          </span>
        ))}
      </div>
      <p className="field-help">Normalized to 100 at each bot&apos;s first after-run snapshot.</p>
    </div>
  );
}
