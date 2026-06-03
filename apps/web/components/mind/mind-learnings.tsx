// What the agent has LEARNED — the ML survival model's state, regime coverage (where funded strategies have
// proven edge), and whether the gate pass-rate is improving. The memory insights + distilled skills are
// rendered alongside on the page. Read-only; the ML model only ORDERS the validation queue, never vetoes.

import { Cpu, Grid3x3, TrendingUp } from "lucide-react";
import type { MindLearnings as Learnings } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TRENDS = ["bull", "bear", "chop"] as const;
const VOLS = ["low", "mid", "high"] as const;

export function MindLearnings({ learnings }: { learnings: Learnings }) {
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      {/* ML survival model */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Cpu className="size-3.5 text-iris-soft" /> ML survival model
          </CardTitle>
          <Badge variant={learnings.ml_trained ? "up" : "muted"}>{learnings.ml_trained ? "trained" : "calibrating"}</Badge>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <Row label="Backend" value={learnings.ml_backend} />
          <Row label="Labeled outcomes" value={String(learnings.ml_labels)} />
          <Row label="OOS AUROC" value={learnings.ml_auroc !== null && learnings.ml_auroc !== undefined ? learnings.ml_auroc.toFixed(2) : "—"} />
          <p className="text-[11px] leading-relaxed text-quiet">
            Orders which candidates get validated first — it never vetoes. The deterministic gate alone decides survival.
          </p>
        </CardContent>
      </Card>

      {/* Regime coverage grid */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Grid3x3 className="size-3.5 text-iris-soft" /> Regime coverage
          </CardTitle>
          <Badge variant="muted">{learnings.regime_covered}/{learnings.regime_total}</Badge>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-[auto_repeat(3,1fr)] gap-1 text-[10px]">
            <span />
            {VOLS.map((v) => (
              <span key={v} className="text-center uppercase tracking-wide text-quiet">{v}</span>
            ))}
            {TRENDS.map((t) => (
              <RegimeRow key={t} trend={t} grid={learnings.regime_grid} />
            ))}
          </div>
          <p className="mt-2.5 text-[11px] leading-relaxed text-quiet">
            A funded strategy may go live only in a regime it has proven edge in.
          </p>
        </CardContent>
      </Card>

      {/* Gate efficiency */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <TrendingUp className="size-3.5 text-iris-soft" /> Gate efficiency
          </CardTitle>
          <Badge variant={learnings.gate_improving ? "up" : "muted"}>{learnings.gate_improving ? "improving" : "steady"}</Badge>
        </CardHeader>
        <CardContent className="space-y-2.5">
          <Row label="Recent pass rate" value={`${Math.round(learnings.gate_rate * 100)}%`} />
          <Sparkline trend={learnings.gate_trend} />
          <div className="flex gap-3 text-[11px] text-quiet">
            <span>{learnings.dead_ends} dead ends</span>
            <span>{learnings.winners} winners</span>
            <span>{learnings.skills} skills</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-[12px]">
      <span className="text-quiet">{label}</span>
      <span className="tabular font-medium text-foreground">{value}</span>
    </div>
  );
}

function RegimeRow({ trend, grid }: { trend: string; grid: Learnings["regime_grid"] }) {
  return (
    <>
      <span className="self-center pr-1 capitalize text-quiet">{trend}</span>
      {VOLS.map((v) => {
        const cell = grid.find((g) => g.trend === trend && g.vol === v);
        const n = cell?.strategies ?? 0;
        return (
          <div
            key={v}
            className={cn(
              "flex aspect-square items-center justify-center rounded text-[11px] font-semibold tabular",
              n > 0 ? "bg-up/15 text-up" : "bg-surface-2/40 text-quiet"
            )}
          >
            {n}
          </div>
        );
      })}
    </>
  );
}

function Sparkline({ trend }: { trend: number[] }) {
  if (trend.length === 0) return <p className="text-[11px] text-quiet">No ticks yet.</p>;
  const max = Math.max(...trend, 0.01);
  return (
    <div className="flex h-8 items-end gap-0.5">
      {trend.map((v, i) => (
        <div
          key={i}
          className="flex-1 rounded-sm bg-iris/60"
          style={{ height: `${Math.max(6, (v / max) * 100)}%` }}
          title={`${Math.round(v * 100)}%`}
        />
      ))}
    </div>
  );
}
