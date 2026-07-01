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

// Compact count formatting for nav counters + filter-option counts: a count over 999 reads "48.5k" (1 decimal),
// "1.5k", while ≤ 999 stays bare ("10", "999"). A whole-thousand value drops the ".0" ("10k", not "10.0k"). Never
// abbreviates below 1000, so the exact small counts the operator scans are always precise. Non-finite/negative → "0".
export function formatCount(n: number | null | undefined): string {
  if (typeof n !== "number" || !Number.isFinite(n) || n < 0) return "0";
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  // 1 decimal, but trim a trailing ".0" so exact thousands read "48k" not "48.0k". toFixed(1) then strip.
  const s = k.toFixed(1);
  return `${s.endsWith(".0") ? s.slice(0, -2) : s}k`;
}

// The canonical paper-stage STATUS predicate (paper / forward_test). ONE taxonomy, imported everywhere
// (screener, dashboards, sidebar counts) so the cohort never drifts between surfaces. Mirrors the engine's
// PAPER_ALIASES (knowledge/lifecycle_status.py): "forward_test" is the tolerated legacy spelling of PAPER;
// the never-written phantom "forward" is intentionally NOT matched.
export function isPaper(status: string | null | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "paper" || s === "forward_test";
}

// The HONEST paper predicate: a strategy is in Paper only if it has a paper-ish status AND has genuinely
// traded on paper (a real fill in the executions ledger, `has_paper_fills`). Single source of truth for the
// "Paper" badge + the Paper cohort, so a funded-but-never-filled documented arm reads "Backtest" — matching
// its own sheet's "no fills yet" — instead of "Paper" over fabricated money. Fills (not status) decide, so a
// stale/legacy status can never lie on any surface.
export function isPaperRow(row: { status?: string | null; has_paper_fills?: boolean | null }): boolean {
  return isPaper(row.status) && row.has_paper_fills === true;
}

// Terminal state: a strategy the Gate or operator has killed/defunded. Its row stays queryable so the record
// SURVIVES the kill — a CLOSED paper track (killed AND it once traded on paper) keeps its funded amount + final
// net-of-fee P&L in the Paper "Track record". Losses are remembered, not erased.
export function isKilled(status: string | null | undefined): boolean {
  return (status ?? "").toLowerCase() === "killed";
}
export function isClosedPaperRow(row: { status?: string | null; has_paper_fills?: boolean | null }): boolean {
  return isKilled(row.status) && row.has_paper_fills === true;
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

// The operator's display timezone. Engine timestamps are stored UTC (tz-aware ISO); every user-facing
// wall-clock render goes through fmtTz so it reads in THIS zone — deterministically on the Vercel server
// (which runs UTC) AND in the browser. Without it, a server-rendered timestamp shows the server's UTC
// (a trade logged 02:16Z would read "02:16" instead of the operator's 04:16). Single-operator app, so this
// is a constant — change it here if the operator relocates.
export const APP_TZ = "Europe/Paris";

// Format a UTC ISO timestamp as wall-clock in APP_TZ. Pass the same Intl options you'd give
// toLocaleDateString/toLocaleTimeString; `timeZone` is injected. Returns "" for a null/unparseable input so
// callers render an honest blank rather than "Invalid Date".
export function fmtTz(ts: string | null | undefined, options: Intl.DateTimeFormatOptions): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { timeZone: APP_TZ, ...options }).format(d);
}
