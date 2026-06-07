// Plain-language kill-reasons — the load-bearing honesty of the Theories surface. The engine emits
// terse machine codes (e.g. "deflated_sharpe_below_bar", "pbo_too_high"); browsing the machine's
// failures only feels like a STRENGTH if a human can read WHY each theory died. This module maps the
// known codes to a one-line, plain-language reason and renders a single, consistent kill-reason chip.
//
// Used ONLY by the Theories page (app/verdicts). No fabrication: an unknown code falls back to the raw
// code with underscores spaced out — never invented, never hidden.

import { Badge } from "@/components/ui/badge";

// Known Gate kill-reason codes to plain language. Keys are matched case-insensitively against the
// engine's reason strings; anything unmapped degrades gracefully to a spaced-out version of the code.
const KILL_REASON_LABELS: Record<string, string> = {
  deflated_sharpe_below_bar: "deflated Sharpe below the 0.95 bar",
  dsr_below_bar: "deflated Sharpe below the 0.95 bar",
  holdout_negative: "edge vanished out-of-sample",
  holdout_deflated_sharpe_negative: "edge vanished out-of-sample",
  decays_out_of_sample: "edge decayed out-of-sample",
  failed_fdr: "did not survive multiple-testing correction",
  fdr_not_survived: "did not survive multiple-testing correction",
  pbo_too_high: "overfit — high backtest-overfitting probability",
  high_pbo: "overfit — high backtest-overfitting probability",
  too_few_trades: "too few trades to trust the result",
  insufficient_trades: "too few trades to trust the result",
  insufficient_data: "not enough point-in-time data",
  negative_after_costs: "unprofitable after real fees",
  unprofitable_after_costs: "unprofitable after real fees",
  max_drawdown_exceeded: "drawdown beyond the risk limit",
  regime_unstable: "edge unstable across regimes",
  look_ahead_detected: "look-ahead bias detected",
  not_significant: "not statistically significant"
};

// Map a raw reason code to its plain-language form (case/underscore-insensitive), falling back to a
// readable version of the raw code so nothing is ever silently dropped.
export function killReasonLabel(raw: string): string {
  const key = raw.trim().toLowerCase();
  return KILL_REASON_LABELS[key] ?? raw.replace(/[-_]/g, " ");
}

// A single, consistent kill-reason chip (the down-toned Badge used across the failure surfaces).
export function KillReasonChip({ reason }: { reason: string }) {
  return <Badge variant="down">{killReasonLabel(reason)}</Badge>;
}
