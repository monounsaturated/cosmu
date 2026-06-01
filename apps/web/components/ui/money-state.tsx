// module: the money-state label. The single, unambiguous source of truth for "what kind of money
// is this number?" shown next to every $ / % figure across the app. Two states only — there is NO
// "demo" money state in the product:
//   PAPER — simulated money on the single pooled Wallet, no real funds (the default while validating).
//   LIVE  — real capital, only when explicitly armed (live_enabled / armed = true).
// When the engine is not connected the surface shows an honest "Engine not connected" state instead
// of any money figure, so MoneyState is never asked to represent a fabricated number.

import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";

export type MoneyMode = "paper" | "live";

// Derive the mode honestly: armed/live -> LIVE; otherwise PAPER.
export function moneyMode({ live }: { live?: boolean }): MoneyMode {
  return live ? "live" : "paper";
}

const META: Record<MoneyMode, { label: string; variant: "up" | "info" }> = {
  paper: { label: "PAPER", variant: "info" },
  live: { label: "LIVE", variant: "up" }
};

const EXPLAINER = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-info">Paper</span> — simulated money on the pooled Wallet, no real funds.
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
