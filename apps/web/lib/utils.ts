import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatUsd(value: number, fractionDigits = 0) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: fractionDigits
  }).format(value);
}

export function formatPct(value: number | null | undefined, digits = 2) {
  // The engine contract types these as `number`, but a degraded/empty row can carry null at runtime
  // (and this renders during static prerender, where a single bad row would fail the whole build).
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
}

export function formatSigned(value: number) {
  return `${value >= 0 ? "+" : "-"}${formatUsd(Math.abs(value))}`;
}

// Compact "how long ago" for timestamps (last tick, last event). Returns null for a null/unparseable
// input so callers render an honest "—" rather than a fabricated time. Tense-free, terse: "3m", "2h", "5d".
export function timeAgo(ts: string | null | undefined): string | null {
  if (!ts) return null;
  const then = Date.parse(ts);
  if (Number.isNaN(then)) return null;
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

const EVENT_LABELS: Record<string, string> = {
  strategy_authored: "Strategy authored",
  strategy_gated: "Strategy gated",
  strategy_killed: "Strategy killed",
  track_opened: "Track funded",
  track_defunded: "Track defunded",
  tracks_funded: "Tracks funded",
  tracks_marked: "Tracks marked",
  order_placed: "Order placed",
  order_filled: "Order filled",
  order_cancelled: "Order cancelled",
  venue_toggle_changed: "Venue toggled",
  cross_asset_gate_run: "Cross-asset gate ran",
  drift_assessed: "Drift assessed",
  live_armed: "Live trading armed",
  live_disarmed: "Live trading disarmed",
  recommendation_created: "Recommendation created",
  recommendation_approved: "Recommendation approved",
  recommendation_dismissed: "Recommendation dismissed",
  autonomy_tick: "Autonomy cycle ran",
  research_pass: "Research pass complete"
};

export function formatEventKind(kind: string): string {
  return EVENT_LABELS[kind] ?? kind.replace(/_/g, " ");
}
