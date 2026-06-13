"use client";

// module: Live trading surface. The gated, dimmed-until-armed money screen. A 2-CLICK
// activation flow (Go live -> modal showing EXACTLY what will trade -> Confirm arms it),
// a real positions table, defund controls, daily-loss vs cap, and the current mode.
//
// SAFETY (real money): LIVE IS OFF BY DEFAULT. This component never decides whether an order
// is real — the engine does, only when toggle ON + keys present + gate PASSED + caps available
// + not kill-switched; otherwise it paper-simulates and defaults to testnet. We send confirm
// only on the explicit second click. Offline -> a clearly-labelled paper demo, never armed.
//
// Types mirror the shared contract (see ./contracts) — locally typed until @cosmu/contracts-ts ships them.

import { useState } from "react";
import { AlertTriangle, Building2, Lock, Power, Rocket, ShieldCheck, Unlock, X } from "lucide-react";
import {
  type ActivateResponse,
  type Caps,
  type DefundResponse,
  type EligibleStrategy,
  type LiveMode,
  type LiveVenuesResponse,
  type PositionsResponse
} from "./contracts";
import { LaunchLiveModal } from "./launch-live-modal";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MetricCard, GaugeBar } from "@/components/ui/viz";
import { MoneyInput } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn, formatSigned, formatUsd } from "@/lib/utils";

const DEFAULT_CAPS: Caps = { per_strategy_cap: 250, global_cap: 1000, max_daily_loss: 100 };

function modeBadge(mode: LiveMode) {
  const map: Record<LiveMode, { variant: "up" | "warn" | "info"; label: string }> = {
    sim: { variant: "info", label: "Paper" },
    testnet: { variant: "warn", label: "testnet" },
    live: { variant: "up", label: "Live" }
  };
  return map[mode];
}

export function LiveSurface({
  initial,
  initialVenues
}: {
  initial: PositionsResponse & { connected: boolean };
  initialVenues: LiveVenuesResponse & { connected: boolean };
}) {
  const [state, setState] = useState<PositionsResponse>(initial);
  const [connected, setConnected] = useState(initial.connected);
  const [venues, setVenues] = useState<LiveVenuesResponse>(initialVenues);
  const [modalOpen, setModalOpen] = useState(false);
  const [caps, setCaps] = useState<Caps>(initial.caps ?? DEFAULT_CAPS);
  const [eligible, setEligible] = useState<EligibleStrategy[]>([]);
  const [note, setNote] = useState<string | null>(null);
  // Per-control in-flight flags. NEVER a page-global pending: one slow/hanging engine request must
  // NEVER grey out (freeze) the entire surface. Each control owns its own flag, always cleared in
  // `finally`, so no button can get permanently stuck disabled.
  const [goLivePending, setGoLivePending] = useState(false);
  const [confirmPending, setConfirmPending] = useState(false);
  const [defundAllPending, setDefundAllPending] = useState(false);
  // Venue toggling owns its OWN in-flight id so a single venue request can never disable (grey out)
  // the rest of the surface — and never the whole page. null = nothing toggling right now.
  const [togglingVenue, setTogglingVenue] = useState<string | null>(null);
  // Per-row defund in-flight: only the row being defunded goes grey.
  const [defundingPosition, setDefundingPosition] = useState<string | null>(null);
  // Launch-live modal state: which strategy to launch (null = closed).
  const [launchTarget, setLaunchTarget] = useState<{ versionId: string; name: string } | null>(null);

  const armed = state.armed;
  const mode = modeBadge(state.mode);
  // The ONE truth gate for this whole surface: real money is at risk only when armed AND on the live
  // venue. Everything else the engine reports (positions, per-venue deployed totals) is SIMULATION
  // capital and must NEVER be presented as live-deployed money — that's the bug the operator caught.
  const isLive = armed && state.mode === "live";
  // The single money-state label for every $ on this surface: LIVE only when armed on the live
  // venue, otherwise Paper. There is no demo money state — offline shows an honest not-connected note.
  const money = moneyMode({ live: isLive });
  // LIVE-only money figures. The engine's /live/positions + /live/venues report SIM capital too (it has no
  // live/sim split today — flagged as a backend gap), so the UI gates them: $0 deployed / $0 daily loss
  // until truly armed-and-live. This is the fix for "$10,000 / $5,000 deployed" reading the SIM aggregate.
  const liveDeployed = isLive ? venues.total_deployed_usd : 0;
  const liveDailyLoss = isLive ? state.daily_loss : 0;
  const dailyLossPct = isLive && state.caps.max_daily_loss > 0 ? Math.min(100, (state.daily_loss / state.caps.max_daily_loss) * 100) : 0;

  async function refreshVenues() {
    if (!ENGINE_CONFIGURED) return;
    try {
      const res = await engineFetch("/live/venues");
      if (res.ok) setVenues((await res.json()) as LiveVenuesResponse);
    } catch {
      /* leave last-known venues; the connected badge already reflects engine reachability */
    }
  }

  async function refreshPositions() {
    if (!ENGINE_CONFIGURED) {
      setConnected(false);
      return;
    }
    try {
      const res = await engineFetch("/live/positions");
      if (!res.ok) throw new Error("engine unavailable");
      const data = (await res.json()) as PositionsResponse;
      setState(data);
      setCaps(data.caps);
      setConnected(true);
      await refreshVenues();
    } catch {
      setConnected(false);
    }
  }

  // Tick / untick a venue into the trading universe (POST /universe/venue). Optimistic, then reconciled
  // from /live/venues. This selects WHERE money may go; "not connected" venues simply can't trade until wired.
  //
  // This deliberately does NOT use the page-wide `pending` transition: a single venue request must never
  // grey out (or freeze) the whole surface. It owns a local `togglingVenue` flag instead, always clears it
  // in `finally` (so the checkbox can never get stuck grey), reverts the optimistic flip on failure, and
  // aborts after a timeout so a hanging engine can't lock the control open. Errors are caught and surfaced
  // as a note — never thrown, so the React tree can't crash.
  async function toggleVenue(id: string, enabled: boolean) {
    if (!ENGINE_CONFIGURED || togglingVenue) return;
    const flip = (val: boolean) =>
      setVenues((v) => ({ ...v, venues: v.venues.map((x) => (x.id === id ? { ...x, enabled: val } : x)) }));
    flip(enabled); // optimistic
    setTogglingVenue(id);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await engineFetch("/universe/venue", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ venue_id: id, enabled }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("toggle rejected");
      setConnected(true);
      await refreshVenues();
    } catch {
      flip(!enabled); // revert the optimistic change so the box reflects reality
      setNote("Couldn’t update that venue — the engine didn’t accept the change. Try again.");
    } finally {
      clearTimeout(timer);
      setTogglingVenue(null);
    }
  }

  // CLICK 1 — open the activation modal. This sends the live toggle request (enabled:true,
  // confirm:false). The engine answers requires_confirm; we never arm on this click.
  // Per-control in-flight: only the "Go live" button goes pending; the rest of the surface stays interactive.
  async function openGoLive() {
    if (goLivePending) return;
    setNote(null);
    setGoLivePending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      if (!ENGINE_CONFIGURED) {
        setConnected(false);
        setNote("Engine not connected — set API_BASE_URL. Arming requires a connected engine with the Gate passed.");
        return;
      }
      const res = await engineFetch("/toggle/live", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: true, confirm: false }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine unavailable");
      const data = (await res.json()) as { enabled: boolean; requires_confirm: boolean; reason?: string };
      if (data.reason) setNote(data.reason);
      setModalOpen(true);
      setConnected(true);
    } catch {
      setConnected(false);
      setNote("Engine not connected — cannot review eligible strategies.");
    } finally {
      clearTimeout(timer);
      setGoLivePending(false);
    }
  }

  // CLICK 2 — confirm arming. Sends confirm:true with the caps the operator reviewed.
  // Per-control in-flight: only the "Confirm arm" button goes pending; cancelling the modal always works.
  async function confirmActivate() {
    if (confirmPending) return;
    setConfirmPending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      if (!ENGINE_CONFIGURED) {
        setNote("Engine not connected — cannot arm.");
        return;
      }
      const res = await engineFetch("/live/activate", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ ...caps, confirm: true }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine unavailable");
      const data = (await res.json()) as ActivateResponse;
      setEligible(data.eligible);
      setCaps(data.caps);
      if (data.armed) {
        setModalOpen(false);
        setNote(null);
        await refreshPositions();
      } else {
        setNote(data.reason ?? "Not armed — the gate has not passed on real data.");
      }
    } catch {
      setConnected(false);
      setNote("Engine not connected — cannot arm.");
    } finally {
      clearTimeout(timer);
      setConfirmPending(false);
    }
  }

  // Defund: "Defund all" uses defundAllPending; per-row "Close" uses defundingPosition so only
  // that row's button goes grey. The rest of the surface (and other rows) stay fully interactive.
  async function defund(scope: "all" | "strategy", versionId?: string) {
    const inFlight = scope === "all" ? defundAllPending : defundingPosition === versionId;
    if (inFlight) return;
    if (scope === "all") setDefundAllPending(true);
    else if (versionId) setDefundingPosition(versionId);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      if (!ENGINE_CONFIGURED) {
        setNote("Engine not connected — defund unavailable.");
        return;
      }
      const res = await engineFetch("/live/defund", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(scope === "strategy" ? { scope, version_id: versionId } : { scope }),
        signal: ctrl.signal
      });
      if (!res.ok) throw new Error("engine unavailable");
      (await res.json()) as DefundResponse;
      await refreshPositions();
    } catch {
      setConnected(false);
      setNote("Engine not connected — could not defund.");
    } finally {
      clearTimeout(timer);
      if (scope === "all") setDefundAllPending(false);
      else setDefundingPosition(null);
    }
  }

  return (
    // The page owns the max-width column + responsive padding; the surface only owns its own vertical rhythm.
    <div className="space-y-6 lg:space-y-7">
      {/* Header: armed state + mode + the always-on "off by default" reassurance */}
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">live trading</div>
          <h1 className="mt-1 flex items-center gap-2 text-3xl font-semibold tracking-tight text-foreground">
            {armed ? <Unlock className="size-6 text-up" /> : <Lock className="size-6 text-quiet" />}
            {armed ? "Armed" : "Disarmed"}
          </h1>
          <p className="mt-1.5 text-[13px] text-muted">
            Live is <span className="text-foreground">off by default</span>. Arming needs the cross-asset gate to have
            passed on real data plus an explicit two-click confirmation.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <MoneyState mode={money} />
          <Badge variant={mode.variant}>
            <ShieldCheck className="size-3" /> mode · {mode.label}
          </Badge>
          {!connected ? <Badge variant="warn">engine not connected</Badge> : null}
          {!armed ? (
            <Button variant="primary" size="md" onClick={openGoLive} disabled={goLivePending}>
              <Power className="size-4" /> Go live
            </Button>
          ) : (
            <Button variant="outline" size="md" onClick={() => defund("all")} disabled={defundAllPending}>
              <X className="size-4" /> Defund all
            </Button>
          )}
        </div>
      </section>

      {note ? (
        <div className="flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{note}</span>
        </div>
      ) : null}

      {/* Caps + live-deployed as gauges. The "Deployed" tile is the headline honesty fix: it shows
          LIVE-deployed capital, which is $0 until armed-and-live — never the SIM aggregate the engine
          also tracks. Each gauge reads occupancy vs its cap/limit at a glance. */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard
          label="Live deployed"
          tone="iris"
          value={
            <span className={liveDeployed > 0 ? "text-foreground" : "text-muted"}>
              {formatUsd(liveDeployed)} <span className="text-[12px] font-normal text-quiet">/ {formatUsd(state.caps.global_cap)}</span>
            </span>
          }
          hint={
            <div className="space-y-1.5">
              <GaugeBar value={liveDeployed} max={state.caps.global_cap} marker={1} tone="iris" />
              <span className="text-quiet">{isLive ? "real capital at risk now" : "nothing live — disarmed"}</span>
            </div>
          }
        />
        <MetricCard label="Per-strategy cap" tone="iris" value={formatUsd(state.caps.per_strategy_cap)} hint="max into any one strategy" />
        <MetricCard label="Max daily loss" tone="warn" value={formatUsd(state.caps.max_daily_loss)} hint="auto-disarm threshold" />
        <MetricCard
          label="Daily loss so far"
          tone={dailyLossPct >= 100 ? "down" : "warn"}
          value={<span className={liveDailyLoss > 0 ? "text-down" : "text-muted"}>{formatUsd(liveDailyLoss)}</span>}
          hint={
            <div className="space-y-1.5">
              <GaugeBar value={liveDailyLoss} max={state.caps.max_daily_loss} marker={1} tone={dailyLossPct >= 100 ? "down" : "warn"} />
              <span className="text-quiet">{isLive ? `${dailyLossPct.toFixed(0)}% of cap` : "no live loss while disarmed"}</span>
            </div>
          }
        />
      </section>

      <VenuesCard venues={venues} connected={connected} isLive={isLive} togglingVenue={togglingVenue} onToggle={toggleVenue} />

      {/* Caps at a glance — two gauges that read the live-risk headroom: deployed vs the global cap, and
          daily loss vs the auto-disarm limit. Both are $0 / 0% while disarmed (the honest safe state). */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Caps at a glance</CardTitle>
            <CardDescription>
              {isLive ? "The engine auto-disarms for the day when daily loss reaches the cap." : "Live-risk gauges sit at 0 while disarmed — nothing is deployed."}
            </CardDescription>
          </div>
          <Badge variant={dailyLossPct >= 100 ? "down" : "muted"}>{dailyLossPct.toFixed(0)}% daily-loss cap</Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          <CapGauge
            label="Deployed vs global cap"
            value={liveDeployed}
            max={state.caps.global_cap}
            tone="iris"
            valueLabel={`${formatUsd(liveDeployed)} / ${formatUsd(state.caps.global_cap)}`}
          />
          <CapGauge
            label="Daily loss vs limit"
            value={liveDailyLoss}
            max={state.caps.max_daily_loss}
            tone={dailyLossPct >= 100 ? "down" : "warn"}
            valueLabel={`${formatUsd(liveDailyLoss)} / ${formatUsd(state.caps.max_daily_loss)}`}
          />
        </CardContent>
      </Card>

      {/* Positions — SCOPED + LABELLED by money state. When NOT live, the engine still returns the SIM
          tracks' open positions; we label them Paper so a paper position is never read as live capital. */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              Open positions
              <Badge variant={isLive ? "up" : "info"}>{isLive ? "Live" : "Paper"}</Badge>
            </CardTitle>
            <CardDescription>
              {isLive
                ? "Real capital at risk now. Defund returns capital to the reserve."
                : "Paper tracks — paper positions on live data, no real money. They do not count as live-deployed capital."}
            </CardDescription>
          </div>
          <Badge variant="muted">{state.positions.length} open</Badge>
        </CardHeader>
        <CardContent>
          {state.positions.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-1.5 py-10 text-center">
              <Lock className="size-5 text-quiet" />
              <div className="text-[13px] text-muted">No open positions</div>
              <div className="max-w-sm text-[11.5px] text-quiet">
                {isLive
                  ? "Armed, but nothing is filled yet. Positions appear here as the engine trades within its caps."
                  : "Nothing is at risk live while disarmed. This is the honest empty state — no fabricated positions."}
              </div>
            </div>
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH className="sticky-col">Symbol</TH>
                  <TH>Venue</TH>
                  <TH className="text-right">Qty</TH>
                  <TH className="text-right">Avg price</TH>
                  <TH className="text-right">Unrealized P&amp;L</TH>
                  <TH className="text-right">Defund</TH>
                </TR>
              </THead>
              <TBody>
                {state.positions.map((p) => (
                  <TR key={p.instrument_id}>
                    <TD className="sticky-col font-medium text-foreground">{p.symbol}</TD>
                    <TD className="text-muted">{p.venue}</TD>
                    <TD className="text-right tabular text-muted">{p.qty}</TD>
                    <TD className="text-right tabular text-muted">{formatUsd(p.avg_price)}</TD>
                    <TD className={cn("text-right tabular", p.unrealized_pnl >= 0 ? "text-up" : "text-down")}>
                      {formatSigned(p.unrealized_pnl)}
                    </TD>
                    <TD className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => defund("strategy", p.instrument_id)} disabled={defundingPosition === p.instrument_id}>
                        <X className="size-3.5" /> Close
                      </Button>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {modalOpen ? (
        <ActivationModal
          caps={caps}
          eligible={eligible}
          note={note}
          pending={confirmPending}
          connected={connected}
          onChangeCaps={setCaps}
          onConfirm={confirmActivate}
          onClose={() => setModalOpen(false)}
          onLaunchStrategy={(s) => setLaunchTarget({ versionId: s.version_id, name: s.name })}
        />
      ) : null}

      {launchTarget ? (
        <LaunchLiveModal
          versionId={launchTarget.versionId}
          strategyName={launchTarget.name}
          onClose={() => setLaunchTarget(null)}
          onArmed={() => {
            setLaunchTarget(null);
            void refreshPositions();
          }}
        />
      ) : null}
    </div>
  );
}

// A labelled cap gauge row: title + the real value/limit on the right, and a marker-tipped bar that fills
// toward 100% of its cap. Pure presentation over real numbers — never a fabricated reading.
function CapGauge({
  label,
  value,
  max,
  tone,
  valueLabel
}: {
  label: string;
  value: number;
  max: number;
  tone: "iris" | "warn" | "down";
  valueLabel: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[12px]">
        <span className="text-muted">{label}</span>
        <span className="tabular font-medium text-foreground">{valueLabel}</span>
      </div>
      <GaugeBar value={value} max={max} marker={1} tone={tone} height={8} />
    </div>
  );
}

// Lean venue overview: the TOTAL live budget up top, then the jurisdiction-legal venues as tick-to-include
// rows. Each shows its deployed amount when connected, or an honest "not connected" when legal-but-unwired.
// `isLive` gates the deployed totals: until armed-and-live, LIVE-deployed is $0 (the engine's per-venue
// numbers include SIM capital, which must never read as live money here).
function VenuesCard({
  venues,
  connected,
  isLive,
  togglingVenue,
  onToggle
}: {
  venues: LiveVenuesResponse;
  connected: boolean;
  isLive: boolean;
  togglingVenue: string | null;
  onToggle: (id: string, enabled: boolean) => void;
}) {
  const rows = venues.venues;
  const connectedCount = rows.filter((v) => v.connected).length;
  const deployedTotal = isLive ? venues.total_deployed_usd : 0;
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Venues</CardTitle>
          <CardDescription>
            Where live capital can go. Tick to include a venue; “not connected” means it’s legal here but has no
            execution keys wired yet{venues.jurisdiction ? ` · jurisdiction ${venues.jurisdiction}` : ""}.
          </CardDescription>
        </div>
        <Badge variant="muted">
          {formatUsd(deployedTotal)} / {formatUsd(venues.global_cap)} live
        </Badge>
      </CardHeader>
      <CardContent>
        {!connected ? (
          <div className="flex flex-col items-center gap-1.5 py-8 text-center">
            <Building2 className="size-5 text-quiet" />
            <div className="text-[13px] text-muted">Engine not connected</div>
            <div className="max-w-sm text-[11.5px] text-quiet">Available venues + per-venue budget appear here once the engine is reachable — no fabricated rows.</div>
          </div>
        ) : rows.length === 0 ? (
          <div className="py-8 text-center text-[12.5px] text-muted">No live-legal venues for this jurisdiction.</div>
        ) : (
          <ul className="divide-y divide-border/40">
            {rows.map((v) => (
              <li key={v.id} className="flex items-center gap-3 py-2.5">
                <input
                  type="checkbox"
                  checked={v.enabled}
                  // Only the row that's actually in flight is disabled — never the whole list — and it
                  // always clears, so a checkbox can't get stuck grey.
                  disabled={togglingVenue === v.id}
                  onChange={(e) => onToggle(v.id, e.target.checked)}
                  aria-label={`Include ${v.name}`}
                  className="size-4 shrink-0 accent-iris disabled:opacity-50"
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-medium text-foreground">{v.name}</span>
                    <Badge variant="muted">{v.kind}</Badge>
                  </div>
                </div>
                {v.connected ? (
                  <div className="text-right">
                    <div className="tabular text-[13px] font-medium text-foreground">{formatUsd(isLive ? v.deployed_usd : 0)}</div>
                    <div className="text-[10.5px] uppercase tracking-wide text-up">connected</div>
                  </div>
                ) : (
                  <Badge variant="warn">not connected</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
        {connected && connectedCount === 0 && rows.length > 0 ? (
          <p className="mt-2 text-[11px] text-quiet">No venue has execution keys wired yet — nothing can trade live until one is connected.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ActivationModal({
  caps,
  eligible,
  note,
  pending,
  connected,
  onChangeCaps,
  onConfirm,
  onClose,
  onLaunchStrategy,
}: {
  caps: Caps;
  eligible: EligibleStrategy[];
  note: string | null;
  pending: boolean;
  connected: boolean;
  onChangeCaps: (c: Caps) => void;
  onConfirm: () => void;
  onClose: () => void;
  onLaunchStrategy?: (s: EligibleStrategy) => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button aria-label="Close" onClick={onClose} className="animate-overlay-in absolute inset-0 bg-black/50" />
      <div className="glass animate-menu-in relative w-full max-w-lg rounded-2xl border border-border bg-surface p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Power className="size-4 text-iris-soft" /> Go live — review what will trade
            </h2>
            <p className="mt-1 text-[12.5px] text-muted">
              Confirming arms real-money execution within these caps. Nothing trades until you press Confirm.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-quiet hover:text-foreground">
            <X className="size-5" />
          </button>
        </div>

        {/* Quiet, non-alarmist gate note */}
        <p className="mt-3 rounded-md border border-border/60 bg-surface-2/40 px-3 py-2 text-[11.5px] leading-relaxed text-quiet">
          A note on safety: the engine only submits a real order when live is on, execution keys are present, the
          cross-asset gate has passed on real data, caps are available, and the kill-switch is clear. Otherwise it
          runs in Paper and defaults to testnet. This capability is not proven profit.
        </p>

        <div className="mt-4 space-y-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Eligible strategies</div>
            {eligible.length === 0 ? (
              <p className="mt-1.5 text-[12.5px] text-muted">None eligible yet — the gate must pass on real data first.</p>
            ) : (
              <ul className="mt-1.5 space-y-1.5">
                {eligible.map((s) => (
                  <li key={s.version_id} className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2 text-[12.5px]">
                    <span className="flex-1 text-foreground">{s.name}</span>
                    <Badge variant="muted">{s.version_id.slice(0, 8)}</Badge>
                    {onLaunchStrategy && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => { onClose(); onLaunchStrategy(s); }}
                      >
                        <Rocket className="size-3" /> Launch
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <MoneyInput label="Per-strategy cap" value={caps.per_strategy_cap} onChange={(v) => onChangeCaps({ ...caps, per_strategy_cap: v })} />
            <MoneyInput label="Global cap" value={caps.global_cap} onChange={(v) => onChangeCaps({ ...caps, global_cap: v })} />
            <MoneyInput label="Max daily loss" value={caps.max_daily_loss} onChange={(v) => onChangeCaps({ ...caps, max_daily_loss: v })} />
          </div>
        </div>

        {note ? (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span>{note}</span>
          </div>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" size="md" onClick={onConfirm} disabled={pending || !connected}>
            <ShieldCheck className="size-4" /> Confirm — arm live
          </Button>
        </div>
      </div>
    </div>
  );
}

