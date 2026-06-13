"use client";

// module: Live trading surface (v18 dashboard). The gated, dimmed-until-armed money screen. The header
// carries the global ARM state + a grey "Rules" button (opens the hard-limit Rules modal) + the Stop /
// Defund-all control. Below: an interactive equity chart, a KPI row that FOLDS the guardrails (Daily
// loss / Exposure / Max DD) as small arc-gauge boxes into the live-vs-sim money line, then [Open
// positions | Recent trades] side by side. The 2-CLICK activation flow (Go live → modal → Confirm) and
// the per-strategy Launch flow are preserved.
//
// SAFETY (real money): LIVE IS OFF BY DEFAULT. This component never decides whether an order is real —
// the engine does, only when toggle ON + keys present + gate PASSED + caps available + not kill-switched.
// We send confirm only on the explicit second click. Offline → an honest not-connected note, never armed.
//
// HONESTY: the KPI row reads the engine's live-vs-sim SPLIT (getPortfolioSummary). When nothing is routed
// live (`has_live` false) every live money figure is null and renders an explicit "—" — NEVER 0 and NEVER
// the SIM number. The guardrails sit at 0% while disarmed (the honest safe state). Max DD has no live
// metric yet, so it renders an honest "—" rather than a fabricated reading.
//
// Types mirror the shared contract (see ./contracts) + the live-portfolio adapters (@/app/data/portfolio).

import { useState, type ReactNode } from "react";
import { AlertTriangle, Building2, Lock, Power, Rocket, ShieldCheck, SlidersHorizontal, Unlock, X } from "lucide-react";
import type { Point, PortfolioSummaryResponse, RulesResponse } from "@cosmu/contracts-ts";
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
import { RulesModal } from "./rules-modal";
import { GuardTile } from "./guard-tile";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MoneyInput } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { TvChart } from "@/components/charts/tv-chart";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn, formatPct, formatSigned, formatUsd } from "@/lib/utils";

const DEFAULT_CAPS: Caps = { per_strategy_cap: 250, global_cap: 1000, max_daily_loss: 100 };

function modeBadge(mode: LiveMode) {
  const map: Record<LiveMode, { variant: "up" | "warn" | "info"; label: string }> = {
    sim: { variant: "info", label: "Paper" },
    testnet: { variant: "warn", label: "testnet" },
    live: { variant: "up", label: "Live" }
  };
  return map[mode];
}

// A money KPI tile: a label, a primary $ value (or "—" when honestly absent), and a sub-line. The
// "—" path is the honesty contract — live figures are null until capital is actually routed live.
function MoneyTile({
  label,
  value,
  sub,
  tone = "muted"
}: {
  label: string;
  value: string;
  sub?: ReactNode;
  tone?: "muted" | "up" | "down";
}) {
  const valueTone = tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-foreground";
  const subTone = tone === "up" ? "text-up" : tone === "down" ? "text-down" : "text-quiet";
  return (
    <div className="card-grad relative overflow-hidden rounded-lg border border-border/70 p-4 shadow-card">
      <div className="label-eyebrow">{label}</div>
      <div className={cn("mt-2 text-2xl font-semibold tabular", valueTone)}>{value}</div>
      {sub ? <div className={cn("mt-1 text-[12px]", subTone)}>{sub}</div> : null}
    </div>
  );
}

export function LiveSurface({
  initial,
  initialVenues,
  initialSummary,
  initialRules,
  equityCurve
}: {
  initial: PositionsResponse & { connected: boolean };
  initialVenues: LiveVenuesResponse & { connected: boolean };
  initialSummary: PortfolioSummaryResponse & { connected: boolean };
  initialRules: RulesResponse & { connected: boolean };
  equityCurve: Point[];
}) {
  const [state, setState] = useState<PositionsResponse>(initial);
  const [connected, setConnected] = useState(initial.connected);
  const [venues, setVenues] = useState<LiveVenuesResponse>(initialVenues);
  const [summary, setSummary] = useState<PortfolioSummaryResponse>(initialSummary);
  const [rules, setRules] = useState<RulesResponse>(initialRules);
  const [modalOpen, setModalOpen] = useState(false);
  const [rulesOpen, setRulesOpen] = useState(false);
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

  // The live-vs-sim MONEY SPLIT (getPortfolioSummary). The honesty discriminator: when no position is
  // routed live (`has_live` false), every live_* money field is null → the UI renders "—", never 0 and
  // never the SIM number. `live_free` is BUDGET HEADROOM (global_cap − invested), NOT exchange cash.
  const hasLive = summary.has_live;
  const usd = (v: number | null | undefined) => (typeof v === "number" ? formatUsd(v) : "—");
  const liveEquity = summary.live_equity;
  const liveInvested = summary.live_invested;
  const liveFree = summary.live_free;
  const livePnl = summary.live_pnl_net;
  const globalCap = rules.global_max_notional || summary.live_global_cap || state.caps.global_cap;

  // Guardrails folded into the KPI line — REAL used/cap only. While disarmed they sit at 0 (the honest
  // safe state). Exposure = live invested vs the global hard cap; Daily loss vs its cap. Max DD has no
  // live metric source yet, so its tile renders an honest "—" rather than a fabricated reading.
  const dailyLossUsed = hasLive ? state.daily_loss : 0;
  const dailyLossCap = rules.max_daily_loss || state.caps.max_daily_loss;
  const exposureUsed = hasLive && typeof liveInvested === "number" ? liveInvested : 0;

  async function refreshVenues() {
    if (!ENGINE_CONFIGURED) return;
    try {
      const res = await engineFetch("/live/venues");
      if (res.ok) setVenues((await res.json()) as LiveVenuesResponse);
    } catch {
      /* leave last-known venues; the connected badge already reflects engine reachability */
    }
  }

  async function refreshSummary() {
    if (!ENGINE_CONFIGURED) return;
    try {
      const res = await engineFetch("/portfolio/summary");
      if (res.ok) setSummary((await res.json()) as PortfolioSummaryResponse);
    } catch {
      /* leave last-known split; the connected badge reflects engine reachability */
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
      await Promise.all([refreshVenues(), refreshSummary()]);
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
      {/* Header: armed state + mode + the Rules button (left of Stop) + the global ARM / Stop control. */}
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
          {/* The grey Rules button sits LEFT of the Stop / Go-live control. */}
          <Button variant="secondary" size="md" onClick={() => setRulesOpen(true)}>
            <SlidersHorizontal className="size-4" /> Rules
          </Button>
          {!armed ? (
            <Button variant="primary" size="md" onClick={openGoLive} disabled={goLivePending}>
              <Power className="size-4" /> Go live
            </Button>
          ) : (
            <Button variant="outline" size="md" onClick={() => defund("all")} disabled={defundAllPending}>
              <X className="size-4" /> Stop &amp; defund all
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

      {/* Interactive equity chart on top — the live equity curve with its own range selector + crosshair.
          The TvChart renders its own honest empty state when there is no real track record. */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Live equity</CardTitle>
            <CardDescription>
              {hasLive
                ? "Real capital at risk now — value and cumulative return at the crosshair."
                : "Nothing routed live yet. The curve renders once the engine has a real live track record."}
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <TvChart
            points={equityCurve}
            mode={money}
            valueKind="usd"
            height={260}
            emptyTitle="No live equity yet"
            emptyHint="Live equity renders once capital is armed and the engine has a real track record. Nothing here is fabricated."
          />
        </CardContent>
      </Card>

      {/* KPI row that FOLDS the guardrails into the live-vs-sim money line. Money tiles render "—" for
          every live figure until capital is actually routed live (the honesty contract). Guardrails sit
          at 0 while disarmed; Max DD has no live metric source yet, so it renders an honest "—". */}
      <section className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <MoneyTile
          label="Live equity"
          value={usd(liveEquity)}
          sub={hasLive ? "real capital" : "nothing live"}
        />
        <MoneyTile
          label="Invested"
          value={usd(liveInvested)}
          sub={
            typeof liveInvested === "number"
              ? `${summary.positions_count_live} strateg${summary.positions_count_live === 1 ? "y" : "ies"}`
              : "—"
          }
        />
        <MoneyTile
          label="Free"
          value={usd(liveFree)}
          sub={
            typeof liveFree === "number" && typeof liveInvested === "number" && globalCap > 0
              ? `${Math.round((liveFree / globalCap) * 100)}% headroom`
              : "budget headroom"
          }
        />
        <MoneyTile
          label="P&L"
          value={typeof livePnl === "number" ? formatSigned(livePnl) : "—"}
          tone={typeof livePnl === "number" ? (livePnl >= 0 ? "up" : "down") : "muted"}
          sub={
            typeof livePnl === "number" && typeof liveInvested === "number" && liveInvested > 0
              ? formatPct((livePnl / liveInvested) * 100)
              : "net of costs"
          }
        />
        {/* Guardrails folded as small arc-gauge boxes. */}
        <GuardTile label="Daily loss" used={dailyLossUsed} cap={dailyLossCap} unit="usd" />
        <GuardTile label="Exposure" used={exposureUsed} cap={globalCap} unit="usd" />
      </section>

      {/* A thin guardrails strip the KPI fold can't fully carry — the auto-halt note + the Max-DD honest
          "—" (no live drawdown metric yet) so the operator sees the third guardrail without fabrication. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-border/60 bg-surface-2/30 px-3.5 py-2.5 text-[12px]">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Guardrails · auto-halt if breached</span>
        <span className="text-muted">
          Max drawdown <span className="tabular text-quiet">— </span>
          <span className="text-quiet">no live metric yet</span>
        </span>
        <span className="text-muted">
          Daily loss{" "}
          <span className="tabular text-foreground">
            {usd(dailyLossUsed)} / {usd(dailyLossCap)}
          </span>
        </span>
        <span className="text-muted">
          Exposure{" "}
          <span className="tabular text-foreground">
            {usd(exposureUsed)} / {usd(globalCap)}
          </span>
        </span>
        <button onClick={() => setRulesOpen(true)} className="ml-auto text-iris-soft hover:underline">
          Edit rules
        </button>
      </div>

      <VenuesCard venues={venues} connected={connected} isLive={isLive} togglingVenue={togglingVenue} onToggle={toggleVenue} />

      {/* [Open positions | Recent trades] side by side — each its own card with a "See all", aligned to
          the top (items-start) so a tall positions list never stretches the trades card. */}
      <section className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2 lg:gap-5">
        <PositionsCard
          state={state}
          isLive={isLive}
          defundingPosition={defundingPosition}
          onDefund={(id) => defund("strategy", id)}
        />
        <RecentTradesCard connected={connected} />
      </section>

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

      {rulesOpen ? (
        <RulesModal
          rules={rules}
          connected={connected}
          onClose={() => setRulesOpen(false)}
          onSaved={(next) => {
            setRules(next);
            void refreshSummary();
          }}
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

// Open positions — SCOPED + LABELLED by money state. When NOT live, the engine still returns the SIM
// tracks' open positions; we label them Paper so a paper position is never read as live capital. The
// table scrolls horizontally on overflow (the Table primitive wraps in overflow-x-auto; cells nowrap).
function PositionsCard({
  state,
  isLive,
  defundingPosition,
  onDefund
}: {
  state: PositionsResponse;
  isLive: boolean;
  defundingPosition: string | null;
  onDefund: (instrumentId: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            Open positions
            <Badge variant={isLive ? "up" : "info"}>{isLive ? "Live" : "Paper"}</Badge>
          </CardTitle>
          <CardDescription>
            {isLive
              ? "Real capital at risk now. Close returns capital to the reserve."
              : "Paper positions on live data — no real money. They do not count as live-deployed capital."}
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
                <TH className="whitespace-nowrap">Symbol</TH>
                <TH className="whitespace-nowrap">Venue</TH>
                <TH className="whitespace-nowrap text-right">Qty</TH>
                <TH className="whitespace-nowrap text-right">Avg price</TH>
                <TH className="whitespace-nowrap text-right">Unrealized P&amp;L</TH>
                <TH className="whitespace-nowrap text-right">Close</TH>
              </TR>
            </THead>
            <TBody>
              {state.positions.map((p, i) => (
                // Defensive unique key: the same instrument can be held on one venue by more than one
                // strategy, so instrument_id alone can collide — index-suffix so no row is dropped.
                <TR key={`${p.instrument_id}-${p.venue}-${i}`}>
                  <TD className="whitespace-nowrap font-medium text-foreground">{p.symbol}</TD>
                  <TD className="whitespace-nowrap text-muted">{p.venue}</TD>
                  <TD className="whitespace-nowrap text-right tabular text-muted">{p.qty}</TD>
                  <TD className="whitespace-nowrap text-right tabular text-muted">{formatUsd(p.avg_price)}</TD>
                  <TD className={cn("whitespace-nowrap text-right tabular", p.unrealized_pnl >= 0 ? "text-up" : "text-down")}>
                    {formatSigned(p.unrealized_pnl)}
                  </TD>
                  <TD className="whitespace-nowrap text-right">
                    <Button variant="ghost" size="sm" onClick={() => onDefund(p.instrument_id)} disabled={defundingPosition === p.instrument_id}>
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
  );
}

// Recent trades — the live fills feed. The engine exposes no live recent-trades endpoint yet, so this
// renders an HONEST "no live trades yet" state rather than fabricating fills or reusing SIM trades.
// (Wiring note: bind to GET /live/recent once the engine ships it; the See-all is a no-op until then.)
function RecentTradesCard({ connected }: { connected: boolean }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Recent trades</CardTitle>
          <CardDescription>Live fills as the engine executes within its caps.</CardDescription>
        </div>
        <span className="text-[11px] text-quiet">See all →</span>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col items-center justify-center gap-1.5 py-10 text-center">
          <Lock className="size-5 text-quiet" />
          <div className="text-[13px] text-muted">No live trades yet</div>
          <div className="max-w-sm text-[11.5px] text-quiet">
            {connected
              ? "Live fills appear here once the engine executes a real order. Nothing here is fabricated — paper trades are not shown as live."
              : "Engine not connected — recent live fills appear here once it is reachable."}
          </div>
        </div>
      </CardContent>
    </Card>
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
