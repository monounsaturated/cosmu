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
