"use client";

// The Paper "Open positions" card (Iris Bento `.card` + `.mini-tbl`, mirrors the mockup's positions()).
// ONE row per funded paper track: name (links to its detail sheet) · pair (class · venue · tf) · size
// (invested) · value (current mark) · P&L ($ + %). The first 4 rows show; "See all →" reveals the rest
// (the `.dash-extra` / `.dash-open` mechanic from the mockup).
//
// HONESTY: a track with no marked dollar value (value_usd / pnl_usd === null) renders "—" in those cells —
// never a 0. If NO track carries any dollar mark, the table collapses to an honest empty state. Nothing is
// fabricated; the per-fill blotter lives on each strategy's detail sheet.

import { useState } from "react";
import Link from "next/link";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatPct, formatUsd, formatVenue, numOrNull } from "@/lib/utils";

const LIM = 4;

// finite-number guard (the shared honest-"—" helper).
const num = numOrNull;

// The instrument-line under the strategy name (class · venue · timeframe) — the real facets the engine
// derives from the spec, so each row reads like a real positions blotter even before P&L moves. Skips any
// empty facet rather than printing a bare "·".
function instrumentLine(r: LeaderboardRow): string {
  return [r.asset_class, formatVenue(r.venue), r.timeframe].filter((s) => s && s !== "—").join(" · ");
}

// The /strategies deep-link for a paper row → opens the screener with that Version's sheet and pins the matching
// row. The leaderboard row carries no traded symbol (LeaderboardRow has none), so we pass only `venue` when it
// exists; the screener then highlights the version's first row AT that venue (else its first row). symbol would
// require a contract field that does not exist.
function strategyHref(r: LeaderboardRow): string {
  const params = new URLSearchParams({ v: r.version_id });
  if (r.venue && r.venue !== "—") params.set("venue", r.venue);
  return `/strategies?${params.toString()}`;
}

// How long the track has been funded — real `paper_age_days`. A fresh track reads "<1d"/"today" so a $0
// P&L is legible as "just entered" rather than "no data". Never fabricated.
function heldLabel(ageDays: number | null): string {
  if (ageDays === null || ageDays <= 0) return "today";
  if (ageDays < 1) return "<1d";
  return `${Math.round(ageDays)}d`;
}

export function PaperPositions({ rows }: { rows: LeaderboardRow[] }) {
  const [open, setOpen] = useState(false);

  // Stable, decision-relevant order: biggest absolute marked P&L first, then by name.
  const ordered = [...rows].sort((a, b) => {
    const pa = num(a.pnl_usd);
    const pb = num(b.pnl_usd);
    if (pa !== null && pb !== null && pa !== pb) return Math.abs(pb) - Math.abs(pa);
    if (pa !== null && pb === null) return -1;
    if (pa === null && pb !== null) return 1;
    return a.name.localeCompare(b.name);
  });

  const anyMarked = rows.some((r) => num(r.value_usd) !== null || num(r.pnl_usd) !== null);

  return (
    <div className={cn("card dh", open && "dash-open")}>
      <div className="card-hdr">
        <span className="card-lbl">Open positions</span>
        {anyMarked && ordered.length > LIM ? (
          <button className="seeall-btn" onClick={() => setOpen((v) => !v)}>
            {open ? "Show less" : "See all →"}
          </button>
        ) : null}
      </div>
      <div className="card-body">
        {!anyMarked ? (
          <EmptyState
            title="No marked track value yet."
            hint="A track shows its deployed capital and net-of-fee P&L here once it accrues marked history. Open a track to see its per-fill blotter."
          />
        ) : (
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>Strategy</th>
                <th>Held</th>
                <th className="r">Size</th>
                <th className="r">Value</th>
                <th className="r">P&amp;L</th>
                <th className="r">P&amp;L %</th>
              </tr>
            </thead>
            <tbody>
              {ordered.map((row, i) => {
                const value = num(row.value_usd);
                const pnl = num(row.pnl_usd);
                const pct = num(row.pnl_pct);
                // Invested = current value − net P&L, only when both real marks exist.
                const invested = value !== null && pnl !== null ? value - pnl : null;
                // Tone: green/red only when P&L has actually moved. An exact $0 (freshly entered, mark = cost)
                // is NEUTRAL — never a misleading green "+0.00%" that reads like a gain.
                const pnlCls = pnl === null ? "quiet" : pnl > 0 ? "up" : pnl < 0 ? "dn" : "muted";
                const instr = instrumentLine(row);
                return (
                  <tr key={row.version_id} className={cn(i >= LIM && "dash-extra")}>
                    <td className="pos-strat">
                      <Link href={strategyHref(row)} className="strat-link" data-tip={row.name}>
                        {row.name}
                      </Link>
                      {instr ? <span className="pos-sub">{instr}</span> : null}
                    </td>
                    <td className="muted tab">{heldLabel(num(row.paper_age_days))}</td>
                    <td className="r tab muted">{invested === null ? "—" : formatUsd(invested)}</td>
                    <td className="r tab">{value === null ? "—" : formatUsd(value)}</td>
                    <td className={cn("r tab", pnlCls)}>{pnl === null ? "—" : formatUsd(pnl)}</td>
                    <td className={cn("r tab", pnlCls)}>{pct === null ? "—" : formatPct(pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
