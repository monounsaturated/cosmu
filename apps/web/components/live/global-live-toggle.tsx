"use client";

// module: the GLOBAL live toggle — the one switch that arms real-money execution across every venue
// (VISION §5, §11; docs/PRODUCT.md A5/D3). LIVE IS OFF BY DEFAULT. Two-click safety: the first click
// asks the engine what would trade (POST /toggle/live {enabled:true, confirm:false}); the engine answers
// requires_confirm + a reason; only the explicit second click sends confirm:true and arms it. Turning
// live OFF is immediate (enabled:false, confirm:true). This control never itself fires an order — the
// deterministic master only submits a real order when this is ON, keys are present, the gate has passed,
// caps are available, and the kill-switch is clear. Offline → an honest note, never a fabricated armed state.
//
// Per-button in-flight state: each of the three buttons (Go live / Confirm arm / Turn live off) owns its
// own pending flag and AbortController timeout. One slow engine call can never permanently grey out the
// Cancel button or any other control. Flags always clear in `finally` — no button can get stuck disabled.

import { useState } from "react";
import Link from "next/link";
import { AlertTriangle, Lock, Power, ShieldCheck, Unlock } from "lucide-react";
import type { ToggleResponse } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

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
    <div className="space-y-3 rounded-lg border border-border/70 bg-surface-2/30 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          {enabled ? <Unlock className="size-5 text-up" /> : <Lock className="size-5 text-quiet" />}
          <div className="leading-tight">
            <div className="text-[13px] font-semibold text-foreground">Global live toggle</div>
            <div className="text-[11.5px] text-quiet">
              {enabled ? "Armed — real-money execution is ON, within caps." : "Off by default — everything runs in Simulation."}
            </div>
          </div>
        </div>
        <Badge variant={enabled ? "up" : "info"}>{enabled ? "Live" : "Simulation"}</Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {enabled ? (
          <Button variant="outline" size="sm" type="button" onClick={disarm} disabled={disarmPending || !connected}>
            <Power className="size-4" /> Turn live off
          </Button>
        ) : awaitingConfirm ? (
          <>
            <Button variant="primary" size="sm" type="button" onClick={confirmArm} disabled={confirmArmPending || !connected}>
              <ShieldCheck className="size-4" /> Confirm — arm live
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => { setAwaitingConfirm(false); setNote(null); }}>
              Cancel
            </Button>
          </>
        ) : (
          <Button variant="secondary" size="sm" type="button" onClick={requestArm} disabled={requestArmPending || !connected}>
            <Power className="size-4" /> Go live…
          </Button>
        )}
        <Link href="/live" className="text-[11.5px] font-medium text-iris-soft hover:underline">
          Caps & positions →
        </Link>
      </div>

      {awaitingConfirm && !enabled ? (
        <p className="rounded-md border border-border/60 bg-background/50 px-3 py-2 text-[11.5px] leading-relaxed text-quiet">
          Confirming arms real-money execution. The engine submits an order only when live is on, keys are present, the
          gate has passed on real data, caps are available, and the kill-switch is clear. This is a capability, not proven profit.
        </p>
      ) : null}

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
