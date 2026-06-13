"use client";

// module: the live-trading Rules modal — the operator's hard-limit editor, opened from the grey "Rules"
// button left of Stop in the Live header. It edits the three caps the engine enforces deterministically
// in the order gauntlet:
//   • global max notional — the HARD $ blocker: total live notional can never exceed this.
//   • max daily loss      — the auto-disarm threshold for the day.
//   • per-venue max notional — a per-venue ceiling, shown alongside each legal venue's REAL deployed_usd
//     and headroom (cap − deployed) so the operator sizes against actual exposure.
//
// SAFETY: setting Rules NEVER arms live — the toggle / keys / gate / kill-switch interlocks still all
// apply. This control only writes limits. POST /live/rules returns the reconciled RulesResponse; we
// re-seed the form from the server's answer so the displayed caps + headroom are always the truth.
//
// HONESTY: per-venue cap blank = uncapped (sent as null, which CLEARS the cap). Deployed + headroom are
// the engine's real numbers; a venue with no cap shows "—" headroom, never a fabricated figure. Offline
// → an honest note, never a silent success. Per-control in-flight flag, always cleared in `finally`.

import { useMemo, useState } from "react";
import { AlertTriangle, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import type { RulesResponse, VenueRule } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn, formatUsd } from "@/lib/utils";

// A blank per-venue field means "uncapped" (null). We keep the editable value as a string so the input
// can be empty without coercing to 0 (0 is a real, different cap meaning "no notional allowed").
type VenueEdit = { venue: string; name: string; cap: string; deployed_usd: number };

function toEdits(venues: VenueRule[]): VenueEdit[] {
  return venues.map((v) => ({
    venue: v.venue,
    name: v.name,
    cap: v.max_notional == null ? "" : String(v.max_notional),
    deployed_usd: v.deployed_usd
  }));
}

// Parse a per-venue cap field: blank → null (uncapped); otherwise a finite ≥0 number, else keep null.
function parseCap(raw: string): number | null {
  const t = raw.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

export function RulesModal({
  rules,
  connected,
  onClose,
  onSaved
}: {
  rules: RulesResponse;
  connected: boolean;
  onClose: () => void;
  onSaved: (next: RulesResponse) => void;
}) {
  const [globalMax, setGlobalMax] = useState(String(rules.global_max_notional ?? 0));
  const [maxDailyLoss, setMaxDailyLoss] = useState(String(rules.max_daily_loss ?? 0));
  const [venues, setVenues] = useState<VenueEdit[]>(() => toEdits(rules.venues));
  const [pending, setPending] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // Live preview of total deployed across venues — the figure the global cap blocks against.
  const totalDeployed = useMemo(() => venues.reduce((s, v) => s + v.deployed_usd, 0), [venues]);
  const globalNum = Number(globalMax);
  const globalHeadroom = Number.isFinite(globalNum) ? globalNum - totalDeployed : null;

  function setVenueCap(venue: string, cap: string) {
    setVenues((vs) => vs.map((v) => (v.venue === venue ? { ...v, cap } : v)));
  }

  async function save() {
    if (pending) return;
    setNote(null);
    if (!ENGINE_CONFIGURED) {
      setNote("Engine not connected — set API_BASE_URL. Rules can only be saved against a connected engine.");
      return;
    }
    const g = Number(globalMax);
    const d = Number(maxDailyLoss);
    if (!Number.isFinite(g) || g < 0 || !Number.isFinite(d) || d < 0) {
      setNote("Global max notional and max daily loss must be valid amounts (≥ 0).");
      return;
    }
    setPending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const body = {
        global_max_notional: g,
        max_daily_loss: d,
        venues: venues.map((v) => ({ venue: v.venue, max_notional: parseCap(v.cap) }))
      };
      const res = await engineFetch("/live/rules", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine rejected the rules");
      const next = (await res.json()) as RulesResponse;
      // Re-seed from the server's reconciled answer so the form is always the truth, then close.
      onSaved(next);
      onClose();
    } catch {
      setNote("Couldn’t save the rules — the engine didn’t accept the change. Try again.");
    } finally {
      clearTimeout(timer);
      setPending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Live trading rules">
      <button aria-label="Close" onClick={onClose} className="animate-overlay-in absolute inset-0 bg-black/50" />
      <div className="glass animate-menu-in relative w-full max-w-2xl rounded-2xl border border-border bg-surface p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
              <SlidersHorizontal className="size-4 text-iris-soft" /> Live trading rules
            </h2>
            <p className="mt-1 text-[12.5px] text-muted">
              The hard limits the engine enforces on every live order. Editing these never arms live — the
              toggle, keys, gate, and kill-switch interlocks still all apply.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-quiet hover:text-foreground">
            <X className="size-5" />
          </button>
        </div>

        {/* The two global blockers. */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <RuleField
            label="Global max notional"
            hint="The hard $ ceiling — total live notional can never exceed this."
            value={globalMax}
            onChange={setGlobalMax}
          />
          <RuleField
            label="Max daily loss"
            hint="Auto-disarms live for the day when reached."
            value={maxDailyLoss}
            onChange={setMaxDailyLoss}
          />
        </div>

        {/* Global headroom preview against real deployed capital. */}
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-border/60 bg-surface-2/40 px-3 py-2 text-[12px]">
          <span className="text-muted">
            Deployed now <span className="tabular font-medium text-foreground">{formatUsd(totalDeployed)}</span> across {venues.length}{" "}
            venue{venues.length === 1 ? "" : "s"}
          </span>
          {globalHeadroom != null ? (
            <span className={cn("tabular", globalHeadroom < 0 ? "text-down" : "text-quiet")}>
              {globalHeadroom < 0 ? "over cap by " : "headroom "}
              <span className="font-medium">{formatUsd(Math.abs(globalHeadroom))}</span>
            </span>
          ) : null}
        </div>

        {/* Per-venue caps — compact, horizontally scrollable table with deployed + headroom. */}
        <div className="mt-4">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Per-venue max notional</span>
            <span className="text-[11px] text-quiet">Blank = uncapped</span>
          </div>
          {venues.length === 0 ? (
            <div className="rounded-md border border-border/60 bg-surface-2/30 px-3 py-4 text-center text-[12px] text-muted">
              {connected ? "No live-legal venues for this jurisdiction yet." : "Venues appear here once the engine is reachable."}
            </div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH className="whitespace-nowrap">Venue</TH>
                  <TH className="whitespace-nowrap text-right">Deployed</TH>
                  <TH className="whitespace-nowrap text-right">Headroom</TH>
                  <TH className="whitespace-nowrap text-right">Max notional ($)</TH>
                </TR>
              </THead>
              <TBody>
                {venues.map((v) => {
                  const cap = parseCap(v.cap);
                  const headroom = cap == null ? null : cap - v.deployed_usd;
                  return (
                    <TR key={v.venue}>
                      <TD className="whitespace-nowrap font-medium text-foreground">{v.name}</TD>
                      <TD className="whitespace-nowrap text-right tabular text-muted">{formatUsd(v.deployed_usd)}</TD>
                      <TD className="whitespace-nowrap text-right tabular">
                        {headroom == null ? (
                          <span className="text-quiet">—</span>
                        ) : (
                          <span className={headroom < 0 ? "text-down" : "text-up"}>{formatUsd(headroom)}</span>
                        )}
                      </TD>
                      <TD className="whitespace-nowrap text-right">
                        <div className="ml-auto flex w-32 items-center rounded-md border border-border bg-background/60 px-2 transition-colors focus-within:border-iris/60 focus-within:ring-2 focus-within:ring-ring/40">
                          <span className="text-[12px] text-quiet">$</span>
                          <input
                            type="number"
                            min={0}
                            inputMode="decimal"
                            value={v.cap}
                            placeholder="∞"
                            onChange={(e) => setVenueCap(v.venue, e.target.value)}
                            aria-label={`${v.name} max notional`}
                            className="w-full bg-transparent py-1.5 pl-1 text-right text-[13px] tabular text-foreground outline-none placeholder:text-quiet"
                          />
                        </div>
                      </TD>
                    </TR>
                  );
                })}
              </TBody>
            </Table>
          )}
        </div>

        {note ? (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span>{note}</span>
          </div>
        ) : null}

        <div className="mt-5 flex items-center justify-between gap-2">
          <Badge variant="muted">Setting rules does not arm live</Badge>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="md" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="md" onClick={save} disabled={pending || !connected}>
              <ShieldCheck className="size-4" /> Save rules
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// A labelled $-prefixed numeric field kept as a string (so it can be empty mid-edit). Used for the two
// global blockers; per-venue caps use their own inline inputs in the table.
function RuleField({
  label,
  hint,
  value,
  onChange
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wide text-quiet">{label}</span>
      <div className="mt-1 flex items-center rounded-md border border-border bg-surface-2/40 px-2.5 transition-colors focus-within:border-iris/60 focus-within:ring-2 focus-within:ring-ring/40">
        <span className="text-[12px] text-quiet">$</span>
        <input
          type="number"
          min={0}
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-transparent py-2 pl-1 text-[13px] tabular text-foreground outline-none"
        />
      </div>
      <span className="mt-1 block text-[11px] text-quiet">{hint}</span>
    </label>
  );
}
