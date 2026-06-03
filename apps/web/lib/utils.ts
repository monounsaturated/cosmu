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

export function formatPct(value: number, digits = 2) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatSigned(value: number) {
  return `${value >= 0 ? "+" : "-"}${formatUsd(Math.abs(value))}`;
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
