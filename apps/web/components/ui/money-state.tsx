// module: the money-state label. The single, unambiguous source of truth for "what kind of money
// is this number?" shown next to every $ / % figure across the app. Two states only — there is NO
// "demo" money state in the product:
//   Simulation — paper-trading on live market data, no real funds (per strategy — there is no pooled wallet).
//   Live       — real capital, only when explicitly armed (live_enabled / armed = true).
// When the engine is not connected the surface shows an honest "Engine not connected" state instead
// of any money figure, so MoneyState is never asked to represent a fabricated number.

import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";

export type MoneyMode = "sim" | "live";

// Derive the mode honestly: armed/live -> Live; otherwise Simulation.
export function moneyMode({ live }: { live?: boolean }): MoneyMode {
  return live ? "live" : "sim";
}

const META: Record<MoneyMode, { label: string; variant: "up" | "info" }> = {
  sim: { label: "Simulation", variant: "info" },
  live: { label: "Live", variant: "up" }
};

const EXPLAINER = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-info">Simulation</span> — paper-trading on live market data — proves it holds forward, no real money.
    </p>
    <p>
      <span className="font-semibold text-up">Live</span> — trading real capital (off until you arm it).
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
