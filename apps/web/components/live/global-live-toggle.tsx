"use client";

// The GLOBAL live toggle (Iris Bento) — the one switch that arms real-money execution across every venue.
// LIVE IS OFF BY DEFAULT. Two-click safety: the first click asks the engine what would trade (POST
// /toggle/live {enabled:true, confirm:false}); the engine answers requires_confirm + a reason; only the
// explicit second click sends confirm:true and arms it. Turning live OFF is immediate (enabled:false,
// confirm:true). This control never itself fires an order — the deterministic master only submits a real
// order when this is ON, keys are present, the gate has passed, caps are available, and the kill-switch is
// clear. Offline → an honest note, never a fabricated armed state.
//
// Per-button in-flight state: each of the three buttons owns its own pending flag + AbortController timeout,
// always cleared in `finally` — no button can get stuck disabled. The 5 interlocks are stated as the safety
// CONTRACT (not a live per-check reading), so arming is informed, never a single careless click.

import { useState } from "react";
import type { ToggleResponse } from "@cosmu/contracts-ts";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

const INTERLOCKS = [
  { label: "Live armed", detail: "This switch is on" },
  { label: "Execution keys present", detail: "A venue has trading keys wired" },
  { label: "Gate passed on real data", detail: "The cross-asset gate cleared, not just a backtest" },
  { label: "Caps available", detail: "Within per-strategy, global, and daily-loss caps" },
  { label: "Kill-switch clear", detail: "No auto-disarm or manual halt active" }
] as const;

export function GlobalLiveToggle({
  initialEnabled,
  connected,
  onArmedChange
}: {
  initialEnabled: boolean;
  connected: boolean;
  /** Lets the parent surface re-pull positions / summary once the armed state changes. */
  onArmedChange?: (enabled: boolean) => void;
}) {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [awaitingConfirm, setAwaitingConfirm] = useState(false);
  const [promoted, setPromoted] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [requestArmPending, setRequestArmPending] = useState(false);
  const [confirmArmPending, setConfirmArmPending] = useState(false);
  const [disarmPending, setDisarmPending] = useState(false);

  async function post(
    body: { enabled: boolean; confirm: boolean },
    setPending: (v: boolean) => void,
    onOk: (data: ToggleResponse) => void
  ) {
    if (!ENGINE_CONFIGURED) {
      setNote("Engine not connected — set API_BASE_URL. Live can only be armed against a connected engine.");
      return;
    }
    setNote(null);
    setPending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await engineFetch("/toggle/live", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine unavailable");
      onOk((await res.json()) as ToggleResponse);
    } catch {
      setNote("Engine not connected — could not change the live toggle.");
    } finally {
      clearTimeout(timer);
      setPending(false);
    }
  }

  // CLICK 1 — ask what would happen. We never arm here.
  function requestArm() {
    if (requestArmPending) return;
    post({ enabled: true, confirm: false }, setRequestArmPending, (data) => {
      setAwaitingConfirm(true);
      if (data.reason) setNote(data.reason);
    });
  }

  // CLICK 2 — arm.
  function confirmArm() {
    if (confirmArmPending) return;
    post({ enabled: true, confirm: true }, setConfirmArmPending, (data) => {
      setEnabled(data.enabled);
      setPromoted(data.promoted ?? []);
      setAwaitingConfirm(false);
      if (!data.enabled) setNote(data.reason ?? "Not armed — the gate has not passed on real data.");
      else onArmedChange?.(true);
    });
  }

  function disarm() {
    if (disarmPending) return;
    post({ enabled: false, confirm: true }, setDisarmPending, (data) => {
      setEnabled(data.enabled);
      setPromoted([]);
      setAwaitingConfirm(false);
      onArmedChange?.(data.enabled);
    });
  }

  return (
    <div className="card dh">
      <div className="card-body">
        {/* State header — the single most important fact, read first. */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span className="kpi-label" style={{ marginBottom: 0 }}>Arm live</span>
            <span className={cn("badge", enabled ? "badge-up" : "badge-iris")}>{enabled ? "Live" : "Paper"}</span>
          </div>
        </div>
        <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.01em", color: "var(--fg)", marginTop: 6 }}>
          {enabled ? "Armed — real-money execution is on" : "Disarmed — everything runs in Paper"}
        </div>
        <div className="quiet" style={{ fontSize: 11 }}>
          {enabled
            ? "Within caps. Turn off any time — it is immediate."
            : "Off by default. Arming is a deliberate two-step confirm."}
        </div>

        {/* The 5 interlocks — the safety contract every real order must satisfy. */}
        <div style={{ marginTop: 12 }}>
          <div className="kpi-label" style={{ marginBottom: 6 }}>5 interlocks · all must hold before any real order</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {INTERLOCKS.map(({ label, detail }, i) => (
              <div key={label} style={{ display: "flex", gap: 8, alignItems: "baseline", fontSize: 11.5 }}>
                <span className="tab quiet" style={{ width: 14, flexShrink: 0 }}>{i + 1}</span>
                <span style={{ color: "var(--fg)", fontWeight: 500 }}>{label}</span>
                <span className="quiet" style={{ fontSize: 10.5 }}>{detail}</span>
              </div>
            ))}
          </div>
        </div>
        <p className="quiet" style={{ fontSize: 10.5, lineHeight: 1.6, marginTop: 8 }}>
          The engine enforces all five server-side. This is the contract, not a live reading — it is a
          capability, not proven profit.
        </p>

        {/* The two-step action row. */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          {enabled ? (
            <button className="btn btn-sm" onClick={disarm} disabled={disarmPending || !connected}>
              Turn live off
            </button>
          ) : awaitingConfirm ? (
            <>
              <button className="btn btn-iris btn-sm" onClick={confirmArm} disabled={confirmArmPending || !connected}>
                Confirm — arm live
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setAwaitingConfirm(false);
                  setNote(null);
                }}
              >
                Cancel
              </button>
              <span className="quiet" style={{ fontSize: 10.5 }}>Step 2 of 2</span>
            </>
          ) : (
            <>
              <button className="btn btn-iris btn-sm" onClick={requestArm} disabled={requestArmPending || !connected}>
                Review &amp; arm…
              </button>
              <span className="quiet" style={{ fontSize: 10.5 }}>Step 1 of 2 — review before arming</span>
            </>
          )}
        </div>

        {promoted.length > 0 ? (
          <p className="up" style={{ fontSize: 11.5, marginTop: 8 }}>
            Promoted {promoted.length} strateg{promoted.length === 1 ? "y" : "ies"} to live.
          </p>
        ) : null}

        {note ? <div style={{ marginTop: 8, color: "var(--down)", fontSize: 12 }}>{note}</div> : null}
      </div>
    </div>
  );
}
