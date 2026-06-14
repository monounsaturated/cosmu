import { clsx, type ClassValue } from "clsx";

// Conditional class joiner. The app is styled with the hand-written Iris Bento CSS (app/globals.css),
// NOT Tailwind utilities, so plain clsx is all we need — no tailwind-merge collapsing.
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function formatUsd(value: number, fractionDigits = 0) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: fractionDigits
  }).format(value);
}

export function formatPct(value: number | null | undefined, digits = 2) {
  // The engine contract types these as `number`, but a degraded/empty row can carry null at runtime.
  // Return "—" (em-dash) for null/NaN/non-finite — mirrors timeAgo's null handling; callers render
  // it as text so a non-numeric string is fine.
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function formatSigned(value: number) {
  return `${value >= 0 ? "+" : "-"}${formatUsd(Math.abs(value))}`;
}

// Signed USD with NO sign on zero ("+$419" / "-$81" / "$0"). Distinct from formatSigned, which always
// emits a sign (formatSigned(0) === "+$0"). Canonical home for the +/-abs money construction.
export function signedUsd(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatUsd(Math.abs(value))}`;
}

// Finite-number guard — returns the number only when it is a real finite value, else null. Used wherever a
// nullable engine money/metric field renders an honest "—" instead of 0.
export function numOrNull(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

// The canonical paper-stage predicate (paper / forward_test / forward). ONE taxonomy, imported everywhere
// (screener, dashboards, sidebar counts) so the cohort never drifts between surfaces.
export function isPaper(status: string | null | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "paper" || s === "forward_test" || s === "forward";
}

// Pretty venue display names. The engine stores raw venue ids ("ibkr", "kraken_futures"); the UI shows the
// recognisable brand. An UNKNOWN id falls back to a title-cased, underscore-split form, so a NEW venue still
// reads cleanly ("my_new_venue" → "My New Venue") without a code change. "—" for a null/empty venue.
const VENUE_LABELS: Record<string, string> = {
  binance: "Binance",
  binanceus: "Binance.US",
  ibkr: "IBKR",
  kraken: "Kraken",
  kraken_futures: "Kraken Futures",
  ig: "IG",
  hyperliquid: "HyperLiquid",
  polymarket: "Polymarket",
  alpaca: "Alpaca",
  coinbase: "Coinbase",
  sim: "Sim",
};
export function formatVenue(venue: string | null | undefined): string {
  if (!venue) return "—";
  const key = venue.trim().toLowerCase();
  if (VENUE_LABELS[key]) return VENUE_LABELS[key];
  return key
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
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
