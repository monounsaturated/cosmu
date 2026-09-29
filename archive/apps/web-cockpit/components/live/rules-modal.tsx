"use client";

// The live-trading Rules modal (Iris Bento Modal) — the operator's hard-limit editor, opened from the grey
// "Rules" button left of Stop in the Live toolbar. It edits the three caps the engine enforces
// deterministically in the order gauntlet:
//   • global max notional — the HARD $ blocker: total live notional can never exceed this.
//   • max daily loss      — the auto-disarm threshold for the day.
//   • per-venue max notional — a per-venue ceiling, shown alongside each legal venue's REAL deployed_usd and
//     AVAILABLE capital (cap − deployed) so the operator sizes against actual exposure.
//   • per-venue ACTIVATION — an On/Off switch per venue (POST /universe/venue, applied immediately): a disabled
//     venue is OUT of the tradable universe, so no strategy can arm or trade on it. The engine keeps ≥1 enabled.
//
// SAFETY: setting Rules NEVER arms live — the toggle / keys / gate / kill-switch interlocks still all apply.
// This control only writes limits. POST /live/rules returns the reconciled RulesResponse; we re-seed the
// form from the server's answer so the displayed caps + headroom are always the truth. Per-control in-flight
// flag + 8s AbortController, always cleared in `finally`.
//
// HONESTY: per-venue cap blank = uncapped (sent as null, which CLEARS the cap). Deployed + headroom are the
// engine's real numbers; a venue with no cap shows "—" headroom in a `.quiet` span, never a fabricated
// figure. Offline → an honest note, never a silent success. Jurisdiction is NOT shown.

import { useEffect, useMemo, useState } from "react";
import type { RulesResponse, UniverseResponse, VenueRule } from "@cosmu/contracts-ts";
import { Modal } from "@/components/ui/modal";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn, formatUsd } from "@/lib/utils";

// A blank per-venue field means "uncapped" (null). We keep the editable value as a string so the input can
// be empty without coercing to 0 (0 is a real, different cap meaning "no notional allowed").
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

  // Per-venue ENABLED state (the tradable-universe on/off). Read from /universe, toggled via
  // POST /universe/venue — a DISABLED venue is out of the universe, so NO strategy can arm or trade on it.
  // This is the operator's "set on/off the activation of a venue". `undefined` = not loaded yet.
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>({});
  const [toggling, setToggling] = useState<string | null>(null);

  useEffect(() => {
    if (!connected) return;
    let alive = true;
    engineFetch("/universe")
      .then((r) => (r.ok ? (r.json() as Promise<UniverseResponse>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => alive && setEnabledMap(Object.fromEntries(d.venues.map((v) => [v.id, v.enabled]))))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [connected]);

  async function toggleVenue(venue: string, next: boolean) {
    if (toggling) return;
    setNote(null);
    setToggling(venue);
    try {
      const res = await engineFetch("/universe/venue", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ venue_id: venue, enabled: next })
      });
      if (!res.ok) throw new Error(String(res.status));
      const d = (await res.json()) as UniverseResponse;
      setEnabledMap(Object.fromEntries(d.venues.map((v) => [v.id, v.enabled])));
    } catch {
      setNote("Couldn’t change that venue — the engine refused (at least one venue must stay enabled).");
    } finally {
      setToggling(null);
    }
  }

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
    <Modal
      open
      onClose={onClose}
      title="Live trading rules"
      width={620}
      actions={
        <>
          <span className="badge badge-muted" style={{ marginRight: "auto" }}>
            Setting rules does not arm live
          </span>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-iris" onClick={save} disabled={pending || !connected}>
            Save rules
          </button>
        </>
      }
    >
      <p style={{ marginBottom: 14 }}>
        The hard limits the engine enforces on every live order. Editing these never arms live — the toggle,
        keys, gate, and kill-switch interlocks still all apply.
      </p>

      {/* The two global blockers. */}
      <div className="kgrid" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 12 }}>
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
      <div className="money-band" style={{ gridTemplateColumns: "1fr 1fr", marginBottom: 14 }}>
        <div className="mb-cell">
          <div className="mb-label">Deployed now</div>
          <div className="mb-val tab">{formatUsd(totalDeployed)}</div>
          <div className="mb-sub">
            across {venues.length} venue{venues.length === 1 ? "" : "s"}
          </div>
        </div>
        <div className="mb-cell">
          <div className="mb-label">{globalHeadroom != null && globalHeadroom < 0 ? "Over cap by" : "Headroom"}</div>
          <div className={cn("mb-val tab", globalHeadroom != null && globalHeadroom < 0 ? "dn" : "")}>
            {globalHeadroom == null ? <span className="quiet">—</span> : formatUsd(Math.abs(globalHeadroom))}
          </div>
          <div className="mb-sub">vs the global hard blocker</div>
        </div>
      </div>

      {/* Per-venue caps — compact table with deployed + headroom. */}
      <div style={{ marginBottom: 4 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
          <span className="kpi-label" style={{ marginBottom: 0 }}>Per-venue activation &amp; caps</span>
          <span className="quiet" style={{ fontSize: 10.5 }}>Off = can&apos;t arm · blank cap = uncapped</span>
        </div>
        {venues.length === 0 ? (
          <div
            className="quiet"
            style={{ border: "1px dashed var(--border)", borderRadius: "var(--r-sm)", padding: "16px 12px", textAlign: "center", fontSize: 12 }}
          >
            {connected ? "No live-legal venues yet." : "Venues appear here once the engine is reachable."}
          </div>
        ) : (
          <div className="tbl-scroll">
            <table className="mini-tbl">
              <thead>
                <tr>
                  <th>Venue</th>
                  <th>Active</th>
                  <th className="r">Deployed</th>
                  <th className="r" data-tip="Capital still available to deploy on this venue under its cap (cap − deployed). Budget headroom, not a fetched exchange balance.">Available</th>
                  <th className="r">Max notional ($)</th>
                </tr>
              </thead>
              <tbody>
                {venues.map((v) => {
                  const cap = parseCap(v.cap);
                  const headroom = cap == null ? null : cap - v.deployed_usd;
                  const on = enabledMap[v.venue]; // undefined until /universe loads
                  return (
                    <tr key={v.venue} style={on === false ? { opacity: 0.5 } : undefined}>
                      <td style={{ fontWeight: 500, color: "var(--fg)" }}>{v.name}</td>
                      <td>
                        <button
                          type="button"
                          className={cn("venue-sw", on && "on")}
                          disabled={toggling !== null || !connected || on === undefined}
                          onClick={() => toggleVenue(v.venue, !on)}
                          data-tip={
                            on
                              ? "Enabled — strategies may arm/trade on this venue. Click to disable."
                              : "Disabled — nothing can arm or trade on this venue. Click to enable."
                          }
                          aria-label={`${v.name} ${on ? "enabled" : "disabled"}`}
                        >
                          <span className="venue-sw-dot" />
                          {on === undefined ? "…" : on ? "On" : "Off"}
                        </button>
                      </td>
                      <td className="r tab muted">{formatUsd(v.deployed_usd)}</td>
                      <td className={cn("r tab", headroom == null ? "quiet" : headroom < 0 ? "dn" : "up")}>
                        {headroom == null ? "—" : formatUsd(headroom)}
                      </td>
                      <td className="r">
                        <input
                          className="cap-in"
                          style={{ width: 72, textAlign: "right" }}
                          type="number"
                          min={0}
                          inputMode="decimal"
                          value={v.cap}
                          placeholder="∞"
                          disabled={on === false}
                          onChange={(e) => setVenueCap(v.venue, e.target.value)}
                          aria-label={`${v.name} max notional`}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {note ? <div style={{ marginTop: 12, color: "var(--down)", fontSize: 12 }}>{note}</div> : null}
    </Modal>
  );
}

// A labelled $-prefixed numeric field kept as a string (so it can be empty mid-edit). Used for the two
// global blockers; per-venue caps use their own inline `.cap-in` inputs in the table.
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
    <label style={{ display: "block" }}>
      <span className="kpi-label" style={{ marginBottom: 4, display: "block" }}>{label}</span>
      <input
        className="search-input"
        style={{ width: "100%", height: 30 }}
        type="number"
        min={0}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
      />
      <span className="quiet" style={{ fontSize: 10.5, marginTop: 4, display: "block" }}>{hint}</span>
    </label>
  );
}
