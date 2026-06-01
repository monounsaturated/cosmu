// module: the money-state label. The single, unambiguous source of truth for "what kind of money
// is this number?" shown next to every $ / % figure across the app. Three states, derived (never
// invented) from the data adapter + the live valve:
//   PAPER — simulated money on live-shadow prices, no real funds (the default while farming).
//   DEMO  — placeholder shown only when the engine is unreachable (data.ts demo=true).
//   LIVE  — real capital, only when explicitly armed (live_enabled / armed = true).
// A small Badge + an "i" tooltip explains all three so the owner is never confused.

import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";

export type MoneyMode = "paper" | "demo" | "live";

// Derive the mode honestly: engine offline -> DEMO; armed/live -> LIVE; otherwise PAPER.
export function moneyMode({ demo, live }: { demo?: boolean; live?: boolean }): MoneyMode {
  if (demo) return "demo";
  if (live) return "live";
  return "paper";
}

const META: Record<MoneyMode, { label: string; variant: "up" | "warn" | "info" }> = {
  paper: { label: "PAPER", variant: "info" },
  demo: { label: "DEMO", variant: "warn" },
  live: { label: "LIVE", variant: "up" }
};

const EXPLAINER = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-info">Paper</span> — simulated money on live-shadow prices, no real funds.
    </p>
    <p>
      <span className="font-semibold text-warn">Demo</span> — placeholder shown while the engine is unreachable.
    </p>
    <p>
      <span className="font-semibold text-up">Live</span> — real capital (off until you arm it).
    </p>
  </div>
);

export function MoneyState({ mode, withInfo = true }: { mode: MoneyMode; withInfo?: boolean }) {
  const meta = META[mode];
  return (
    <span className="inline-flex items-center gap-1.5">
      <Badge variant={meta.variant}>{meta.label}</Badge>
      {withInfo ? <Tooltip content={EXPLAINER} /> : null}
    </span>
  );
}
