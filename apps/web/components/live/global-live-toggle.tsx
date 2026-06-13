"use client";

// module: the GLOBAL live toggle — the one switch that arms real-money execution across every venue
// (VISION §5, §11; docs/PRODUCT.md A5/D3). LIVE IS OFF BY DEFAULT. Two-click safety: the first click
// asks the engine what would trade (POST /toggle/live {enabled:true, confirm:false}); the engine answers
// requires_confirm + a reason; only the explicit second click sends confirm:true and arms it. Turning
// live OFF is immediate (enabled:false, confirm:true). This control never itself fires an order — the
// deterministic master only submits a real order when this is ON, keys are present, the gate has passed,
// caps are available, and the kill-switch is clear. Offline → an honest note, never a fabricated armed state.
//
// This is the highest-gravity control in the product, so it is presented as a deliberate two-step ARM
// action: state header → the 5 interlocks (the safety CONTRACT every real order must satisfy — stated
// plainly, NOT fabricated live readings) → the two-click confirm. The interlocks are the same five the
// engine enforces server-side; we surface them so arming is informed, never a single careless click.
//
// Per-button in-flight state: each of the three buttons (Go live / Confirm arm / Turn live off) owns its
// own pending flag and AbortController timeout. One slow engine call can never permanently grey out the
// Cancel button or any other control. Flags always clear in `finally` — no button can get stuck disabled.

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, KeyRound, Lock, Power, ShieldCheck, SlidersHorizontal, Unlock, Wallet, Zap } from "lucide-react";
import type { ToggleResponse } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

// The 5 interlocks the engine enforces before it will submit a single real order. Stated as the SAFETY
// CONTRACT — not a live per-check reading (the engine does not report each one individually). They make
// arming an informed, deliberate act rather than a careless toggle.
const INTERLOCKS = [
  { icon: Power, label: "Live armed", detail: "This switch is on" },
  { icon: KeyRound, label: "Execution keys present", detail: "A venue has trading keys wired" },
  { icon: ShieldCheck, label: "Gate passed on real data", detail: "The cross-asset gate cleared, not just a backtest" },
  { icon: Wallet, label: "Caps available", detail: "Within per-strategy, global, and daily-loss caps" },
  { icon: Zap, label: "Kill-switch clear", detail: "No auto-disarm or manual halt active" },
] as const;

export function GlobalLiveToggle({
  initialEnabled,
  connected
}: {
  initialEnabled: boolean;
  connected: boolean;
}) {
  const [enabled, setEnabled] = useState(initialEnabled);
  const [awaitingConfirm, setAwaitingConfirm] = useState(false);
  const [promoted, setPromoted] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  // Per-button in-flight flags — never a shared pending so one request can't freeze the whole widget.
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
    });
  }

  function disarm() {
    if (disarmPending) return;
    post({ enabled: false, confirm: true }, setDisarmPending, (data) => {
      setEnabled(data.enabled);
      setPromoted([]);
      setAwaitingConfirm(false);
    });
  }

  return (
    <div
      className={cn(
        // The arming console's frame escalates with state: a calm bordered panel when disarmed, a warm
        // accent while awaiting the confirm click, and an "up" accent once armed — so the operator always
        // reads the gravity of the current state at a glance.
        "space-y-4 rounded-xl border p-4 shadow-card sm:p-5",
        enabled ? "border-up/40 bg-up/[0.05]" : awaitingConfirm ? "border-warn/45 bg-warn/[0.05]" : "border-border/70 card-grad"
      )}
    >
      {/* State header — the single most important fact, read first. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span
            className={
              enabled
                ? "flex size-10 items-center justify-center rounded-full border border-up/40 bg-up/10 text-up"
                : "flex size-10 items-center justify-center rounded-full border border-border/70 bg-surface-2/60 text-quiet"
            }
          >
            {enabled ? <Unlock className="size-5" /> : <Lock className="size-5" />}
          </span>
          <div className="leading-tight">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">arm live</span>
              <Badge variant={enabled ? "up" : "info"}>{enabled ? "Live" : "Paper"}</Badge>
            </div>
            <div className="mt-0.5 text-[15px] font-semibold tracking-tight text-foreground">
              {enabled ? "Armed — real-money execution is on" : "Disarmed — everything runs in Paper"}
            </div>
            <div className="text-[11.5px] text-quiet">
              {enabled ? "Within caps. Turn off any time — it is immediate." : "Off by default. Arming is a deliberate two-step confirm."}
            </div>
          </div>
        </div>
        <Link href="/live" className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-iris-soft hover:underline">
          <SlidersHorizontal className="size-3.5" /> Caps &amp; positions
        </Link>
      </div>

      {/* The 5 interlocks — the safety contract every real order must satisfy. */}
      <div className="space-y-2 rounded-lg border border-border/60 bg-background/40 p-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-quiet">
          5 interlocks · all must hold before any real order
        </div>
        <ul className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
          {INTERLOCKS.map(({ icon: Icon, label, detail }, i) => (
            <li key={label} className="flex items-start gap-2.5">
              <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-md border border-border/70 bg-surface-2/50 text-[10px] font-semibold tabular text-quiet">
                {i + 1}
              </span>
              <div className="leading-tight">
                <span className="inline-flex items-center gap-1.5 text-[12px] font-medium text-foreground">
                  <Icon className="size-3 text-muted" /> {label}
                </span>
                <div className="text-[11px] text-quiet">{detail}</div>
              </div>
            </li>
          ))}
        </ul>
        <p className="text-[10.5px] leading-relaxed text-quiet">
          The engine enforces all five server-side. This is the contract, not a live reading — it is a capability, not proven profit.
        </p>
      </div>

      {/* Step 2 explainer — only while awaiting the confirm click. */}
      {awaitingConfirm && !enabled ? (
        <p className="rounded-md border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[11.5px] leading-relaxed text-warn">
          Step 2 of 2. Confirming arms real-money execution within the caps on the Live page. The engine still only
          submits an order when all five interlocks hold. Nothing trades until you press Confirm.
        </p>
      ) : null}

      {/* The two-step action row. */}
      <div className="flex flex-wrap items-center gap-2">
        {enabled ? (
          <Button variant="outline" size="md" type="button" onClick={disarm} disabled={disarmPending || !connected}>
            <Power className="size-4" /> Turn live off
          </Button>
        ) : awaitingConfirm ? (
          <>
            <Button variant="primary" size="md" type="button" onClick={confirmArm} disabled={confirmArmPending || !connected}>
              <ShieldCheck className="size-4" /> Confirm — arm live
            </Button>
            <Button variant="ghost" size="md" type="button" onClick={() => { setAwaitingConfirm(false); setNote(null); }}>
              Cancel
            </Button>
            <span className="text-[11px] text-quiet">Step 2 of 2</span>
          </>
        ) : (
          <>
            <Button variant="secondary" size="md" type="button" onClick={requestArm} disabled={requestArmPending || !connected}>
              <Power className="size-4" /> Review &amp; arm…
            </Button>
            <span className="text-[11px] text-quiet">Step 1 of 2 — review before arming</span>
          </>
        )}
      </div>

      {promoted.length > 0 ? (
        <p className="text-[11.5px] text-up">Promoted {promoted.length} strateg{promoted.length === 1 ? "y" : "ies"} to live.</p>
      ) : null}

      {note ? (
        <div className="flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{note}</span>
        </div>
      ) : null}
    </div>
  );
}
