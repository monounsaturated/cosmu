// module: KpiRow — the Overview's compact KPI strip, the second-glance answer to "where does the machine
// stand?". Four dense tiles, every one REAL engine data:
//   • Survivors       — strategies that have cleared the honest Gate (funnel.gate_passed).
//   • In simulation   — funded tracks accumulating live-bar evidence with no capital (funnel.funded).
//   • Days to live-ready — the SHORTEST remaining wait until a maturing track crosses the ≥30d signal,
//                          or "ready" the moment one has. Honest "—" when no track is in simulation.
//   • Gate verdicts   — how many theories the Gate has ruled on (PASS or FAIL), with the pass tally.
//
// HONESTY CONTRACT: nothing is fabricated. Each tile shows "—" + "engine offline" when its source is not
// connected, and an honest empty value when the engine is up but the count is genuinely zero. The
// days-to-ready number is computed only from real forward_age_days — never an estimate or a target.

import { CalendarClock, ClipboardCheck, FlaskConical, ShieldCheck } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import type { ExperimentsResponse, FunnelStats } from "@/app/data";
import { MetricCard } from "@/components/ui/viz";

const LIVE_READY_DAYS = 30;

export function KpiRow({
  funnel,
  intelConnected,
  simRows,
  lbConnected,
  summary,
  experimentsConnected
}: {
  funnel: FunnelStats;
  intelConnected: boolean;
  simRows: LeaderboardRow[];
  lbConnected: boolean;
  summary: ExperimentsResponse["summary"];
  experimentsConnected: boolean;
}) {
  // Days to live-ready — derived ONLY from real forward_age_days. If any track already has ≥30d it is
  // "ready"; otherwise we surface the shortest remaining wait. Null (→ "—") when nothing is maturing.
  const ages = simRows.map((r) => Math.floor(r.forward_age_days ?? 0));
  const anyReady = ages.some((d) => d >= LIVE_READY_DAYS);
  const maturing = ages.filter((d) => d < LIVE_READY_DAYS);
  const minRemaining = maturing.length > 0 ? Math.min(...maturing.map((d) => LIVE_READY_DAYS - d)) : null;

  let liveReadyValue: string;
  let liveReadyHint: string;
  let liveReadyTone: "up" | "iris" | "muted";
  if (!lbConnected) {
    liveReadyValue = "—";
    liveReadyHint = "engine offline";
    liveReadyTone = "muted";
  } else if (anyReady) {
    liveReadyValue = "Ready";
    liveReadyHint = "a track has cleared 30 days";
    liveReadyTone = "up";
  } else if (minRemaining !== null) {
    liveReadyValue = `${minRemaining}d`;
    liveReadyHint = "until the first track matures";
    liveReadyTone = "iris";
  } else {
    liveReadyValue = "—";
    liveReadyHint = "no tracks in simulation";
    liveReadyTone = "muted";
  }

  const ruled = summary.total;
  const passes = summary.passed;

  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Survivors"
        tone="up"
        icon={<ShieldCheck className="size-4" />}
        value={intelConnected ? funnel.gate_passed : "—"}
        hint={intelConnected ? `${funnel.authored} authored · ${funnel.killed} killed` : "engine offline"}
      />
      <MetricCard
        label="In simulation"
        tone="iris"
        icon={<FlaskConical className="size-4" />}
        value={intelConnected ? funnel.funded : "—"}
        hint={intelConnected ? `${funnel.live} live` : "engine offline"}
      />
      <MetricCard
        label="Days to live-ready"
        tone={liveReadyTone}
        icon={<CalendarClock className="size-4" />}
        value={liveReadyValue}
        hint={liveReadyHint}
      />
      <MetricCard
        label="Gate verdicts"
        tone={experimentsConnected ? "info" : "muted"}
        icon={<ClipboardCheck className="size-4" />}
        value={experimentsConnected ? ruled : "—"}
        hint={experimentsConnected ? (ruled > 0 ? `${passes} passed · ${ruled - passes} failed` : "none ruled yet") : "ledger offline"}
      />
    </section>
  );
}
