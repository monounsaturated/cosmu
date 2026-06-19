"use client";

// Live trading surface (Iris Bento dashboard). The gated, money screen — mirror of the Paper dashboard.
// Its toolbar carries the global ARM state, a grey "Rules" button (opens the hard-limit Rules modal), and a
// danger Stop control (opens the liquidate modal). Below: the equity hero on top, then a KPI+guard row that
// FOLDS the guardrails (Daily loss / Max DD / Exposure) as editable-cap guard boxes into the live-vs-sim
// money line (Invested / Free / P&L), then [Open positions | Recent trades] side by side. Arming is done from
// the strategy sheet (Go Live → POST `/live/launch`), NOT here — this surface only monitors, Stops, and edits Rules.
//
// SAFETY (real money): LIVE IS OFF BY DEFAULT. This component never decides whether an order is real — the
// engine does, only when toggle ON + keys present + gate PASSED + caps available + not kill-switched. There is
// no arm control on this surface (arming lives on the strategy sheet). Offline → an honest not-connected note, never armed.
//
// HONESTY: the KPI row reads the engine's live-vs-sim SPLIT (getPortfolioSummary). When nothing is routed
// live (`has_live` false) every live money figure is null and renders an explicit "—" — NEVER 0 and NEVER
// the SIM number. The guardrails sit at 0% while disarmed (the honest safe state). Max DD has no live metric
// source yet, so it renders an honest "—" rather than a fabricated reading.
//
// LIVE ORDERS panel (control panel): lists the engine's real-venue orders (GET /live/orders — is_paper=0
// only, NEVER the sim/paper lane) with a per-row Cancel that POSTs /live/orders/{id}/cancel (confirm → cancel
// → refresh). This surface only LISTS + CANCELS; it never places or modifies an order. Empty list → the honest
// "No live orders — nothing armed" state. Cancel is a real money-path control: the engine resolves the order's
// own venue adapter and is conservative (404 for unknown/sim orders, honest reason for data-only venues).

import { useState, type ReactNode } from "react";
import type { PortfolioSummaryResponse, RulesResponse } from "@cosmu/contracts-ts";
import type { LiveOrdersResponse, PositionsResponse } from "./contracts";
import { RulesModal } from "./rules-modal";
import { GuardTile } from "./guard-tile";
import { EquityHero } from "./equity-hero";
import { AllocDonut } from "./alloc-donut";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { Modal } from "@/components/ui/modal";
import { EmptyState } from "@/components/ui/honest-state";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn, formatPct, formatSigned, formatUsd } from "@/lib/utils";

// One bento money KPI box. "—" is the honesty contract — live figures are null until capital is routed live.
function MoneyBox({ label, value, sub, tone }: { label: string; value: string; sub?: ReactNode; tone?: "up" | "dn" }) {
  return (
    <div className="kpi-box">
      <div className="kpi-label">{label}</div>
      <div className={cn("kpi-val tab", tone)}>{value}</div>
      {sub ? <div className={cn("kpi-sub", tone ?? "muted")}>{sub}</div> : null}
    </div>
  );
}

export function LiveSurface({
  initial,
  initialSummary,
  initialRules,
  venues,
  initialOrders
}: {
  initial: PositionsResponse & { connected: boolean };
  initialSummary: PortfolioSummaryResponse & { connected: boolean };
  initialRules: RulesResponse & { connected: boolean };
  venues: { name: string; amount: number }[];
  initialOrders: LiveOrdersResponse & { connected: boolean };
}) {
  const [state, setState] = useState<PositionsResponse>(initial);
  const [connected, setConnected] = useState(initial.connected);
  const [summary, setSummary] = useState<PortfolioSummaryResponse>(initialSummary);
  const [rules, setRules] = useState<RulesResponse>(initialRules);
  const [orders, setOrders] = useState<LiveOrdersResponse>(initialOrders);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [liqOpen, setLiqOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [defundAllPending, setDefundAllPending] = useState(false);
  const [defundingPosition, setDefundingPosition] = useState<string | null>(null);
  const [cancelingOrder, setCancelingOrder] = useState<string | null>(null);
  const [showAllPositions, setShowAllPositions] = useState(false);

  const armed = state.armed;
  // The ONE truth gate for this whole surface: real money is at risk only when armed AND on the live venue.
  const isLive = armed && state.mode === "live";

  // The live-vs-sim MONEY SPLIT. The honesty discriminator: when no position is routed live (`has_live`
  // false), every live_* money field is null → the UI renders "—", never 0 and never the SIM number.
  const hasLive = summary.has_live;
  const usd = (v: number | null | undefined) => (typeof v === "number" ? formatUsd(v) : "—");
  // Gate every live money figure on the surface's OWN truth (armed AND on the live venue), not just the
  // engine's has_live — when nothing is armed live, show an honest "—" rather than leaking the sim split
  // (which is why Live was mirroring Paper's equity/positions).
  const liveInvested = isLive ? summary.live_invested : null;
  const liveFree = isLive ? summary.live_free : null;
  const livePnl = isLive ? summary.live_pnl_net : null;
  const globalCap = rules.global_max_notional || summary.live_global_cap || state.caps.global_cap;

  // Guardrails folded into the KPI line — REAL used/cap only. While disarmed they sit at 0 (the honest safe
  // state). Exposure = live invested vs the global hard cap; Daily loss vs its cap. Max DD has no live metric
  // source yet, so its tile is handed `null` and renders an honest "—".
  const dailyLossUsed = hasLive ? state.daily_loss : 0;
  const dailyLossCap = rules.max_daily_loss || state.caps.max_daily_loss;
  const exposureUsed = isLive && typeof liveInvested === "number" ? liveInvested : 0;

  async function refreshAll() {
    if (!ENGINE_CONFIGURED) {
      setConnected(false);
      return;
    }
    try {
      // The reads are independent — fetch them in PARALLEL (was a sequential waterfall: positions, THEN
      // summary, ~2× the latency on a Rules save / defund). ONLY positions drives connected-state, so the
      // summary + orders fetches swallow their own rejection (→ null) — a miss keeps the last-known value, NOT
      // a false disconnect (matches the prior nested-try/catch behaviour).
      const [res, sres, ores] = await Promise.all([
        engineFetch("/live/positions"),
        engineFetch("/portfolio/summary").catch(() => null),
        engineFetch("/live/orders").catch(() => null),
      ]);
      if (!res.ok) throw new Error("engine unavailable");
      setState((await res.json()) as PositionsResponse);
      setConnected(true);
      if (sres?.ok) setSummary((await sres.json()) as PortfolioSummaryResponse);
      if (ores?.ok) setOrders((await ores.json()) as LiveOrdersResponse);
    } catch {
      setConnected(false);
    }
  }

  // Cancel ONE live order at its venue (the control-panel action). Confirm → POST /live/orders/{id}/cancel →
  // refresh. The engine is the authority: it resolves the order's own venue adapter and refuses anything that
  // is not a real live order (404 for unknown/sim ids). A non-2xx or an engine `canceled:false` surfaces the
  // honest reason; only that row's button goes grey while in flight.
  async function cancelOrder(orderId: string) {
    if (cancelingOrder) return;
    if (typeof window !== "undefined" && !window.confirm(`Cancel live order ${orderId}? This sends a cancel to the venue.`)) return;
    setCancelingOrder(orderId);
    setNote(null);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      if (!ENGINE_CONFIGURED) {
        setNote("Engine not connected — cancel unavailable.");
        return;
      }
      const res = await engineFetch(`/live/orders/${encodeURIComponent(orderId)}/cancel`, {
        method: "POST",
        signal: ctrl.signal
      });
      if (!res.ok) {
        setNote(res.status === 404 ? "That order is no longer a live order — nothing to cancel." : "Could not cancel that order.");
        return;
      }
      const body = (await res.json()) as { canceled: boolean; reason?: string | null };
      if (!body.canceled) setNote(body.reason ? `Cancel rejected: ${body.reason}` : "Cancel was not accepted by the venue.");
      await refreshAll();
    } catch {
      setNote("Engine not connected — could not cancel.");
    } finally {
      clearTimeout(timer);
      setCancelingOrder(null);
    }
  }

  // Defund: "Defund all" uses defundAllPending; per-row "Close" uses defundingPosition so only that row's
  // button goes grey. The rest of the surface (and other rows) stay fully interactive.
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
      await res.json();
      setLiqOpen(false);
      await refreshAll();
    } catch {
      setConnected(false);
      setNote("Engine not connected — could not defund.");
    } finally {
      clearTimeout(timer);
      if (scope === "all") setDefundAllPending(false);
      else setDefundingPosition(null);
    }
  }

  // Persist an inline guard-cap edit (Daily-loss / Exposure) to the engine Rules, optimistically.
  async function saveCap(patch: Partial<Pick<RulesResponse, "global_max_notional" | "max_daily_loss">>) {
    const next = { ...rules, ...patch };
    setRules(next);
    if (!ENGINE_CONFIGURED) return;
    try {
      const res = await engineFetch("/live/rules", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          global_max_notional: next.global_max_notional,
          max_daily_loss: next.max_daily_loss,
          venues: (next.venues ?? []).map((v) => ({ venue: v.venue, max_notional: v.max_notional ?? null }))
        })
      });
      if (res.ok) setRules((await res.json()) as RulesResponse);
    } catch {
      /* keep the optimistic value; the connected badge reflects reachability */
    }
  }

  // The live exposure amount the liquidate modal will market-sell (real, or "—" when nothing is live).
  const liqAmount = hasLive && typeof liveInvested === "number" ? formatUsd(liveInvested) : null;
  const liqCount = summary.positions_count_live;

  // Live positions only — when not armed live, do not mirror the sim/paper positions onto the Live screen.
  // `state.positions` is typed non-null but the engine can omit it — guard so `.slice`/`.map` below can't throw.
  const positions = isLive ? (state.positions ?? []) : [];
  const POS_LIM = 4;
  const shownPositions = showAllPositions ? positions : positions.slice(0, POS_LIM);

  // Live orders feed (engine is the authority — these are real-venue orders only, never sim/paper). Cancel
  // is only meaningful on a still-working order; a canceled row stays visible (audit) but its button is gone.
  const liveOrders = orders.orders ?? [];

  return (
    <Page>
      {/* Toolbar (v18 page-live) — Running/Off badge on the left; the grey Rules button + danger Stop on the
          right. Arming is done on the strategy sheet (Go Live → `/live/launch`); this surface only monitors + Stops. */}
      <Toolbar
        title="Live"
        left={
          armed ? (
            // Make the money-reality UNMISTAKABLE in the badge itself: testnet = fake money (the safe default),
            // live = real funds, sim = internal only. A bare "Running" could be misread as real money — it must
            // never say "Running" without naming which money it is on. `state.mode` is the engine's resolved mode.
            state.mode === "live" ? (
              <span className="badge badge-dn" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                <span className="run-dot" style={{ background: "var(--down)" }} /> LIVE · real money
              </span>
            ) : state.mode === "testnet" ? (
              <span className="badge badge-gold" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                <span className="run-dot" style={{ background: "var(--gold)" }} /> TESTNET · test money (not real)
              </span>
            ) : (
              <span className="badge badge-run" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
                <span className="run-dot" /> Running · sim
              </span>
            )
          ) : (
            <span className="badge badge-muted">Off</span>
          )
        }
        right={
          <>
            <button className="btn btn-sm" onClick={() => setRulesOpen(true)}>
              Rules
            </button>
            <button
              className="btn btn-danger btn-sm"
              onClick={() => setLiqOpen(true)}
              disabled={!armed}
              title={armed ? "Liquidate all live positions and disarm" : "Nothing is armed live to stop"}
              style={!armed ? { opacity: 0.45, cursor: "not-allowed" } : undefined}
            >
              Stop
            </button>
          </>
        }
      />

      {note ? <div style={{ color: "var(--down)", fontSize: 12, marginBottom: 12 }}>{note}</div> : null}

      {/* id="dash-live" scopes the compact dashboard KPI sizing (globals.css #dash-live .kpi-val/.kpi-box). */}
      <div id="dash-live">
        {/* Equity hero ALWAYS on top — but with NO curve. `equityCurve` is overview.equity_curve, which is
            scope='aggregate' (Σ-allocated SIM/paper), NOT a live-scoped series — feeding it here is a latent
            SIM-as-live leak the moment summary.live_equity goes non-null (the old `isLive && live_equity != null`
            guard would then plot the aggregate sim curve under a "live" hero). Lowest-risk fix: pass [] (honest
            empty hero) until a real live-scoped equity series exists. Do NOT repoint this to equityCurve. */}
        <EquityHero label="Total equity" curve={[]} />

        {/* Money + guard boxes (left, 3×2) + Open positions (right). */}
        <div className="kgrid dash-split" style={{ gridTemplateColumns: "minmax(0,3fr) minmax(0,2fr)" }}>
          <div className="kgrid kpi-guard" style={{ gridTemplateColumns: "repeat(3,1fr)", marginBottom: 0 }}>
          <MoneyBox
            label="Invested"
            value={usd(liveInvested)}
            sub={
              typeof liveInvested === "number"
                ? `${liqCount} strateg${liqCount === 1 ? "y" : "ies"}`
                : "nothing live"
            }
          />
          <MoneyBox
            label="Free"
            value={usd(liveFree)}
            sub={
              typeof liveFree === "number" && globalCap > 0
                ? `${Math.round((liveFree / globalCap) * 100)}% headroom`
                : "budget headroom"
            }
          />
          <MoneyBox
            label="P&L"
            value={typeof livePnl === "number" ? formatSigned(livePnl) : "—"}
            tone={typeof livePnl === "number" ? (livePnl >= 0 ? "up" : "dn") : undefined}
            sub={
              typeof livePnl === "number" && typeof liveInvested === "number" && liveInvested > 0
                ? `${formatPct((livePnl / liveInvested) * 100)} net`
                : "net of costs"
            }
          />
          {/* Guardrails — editable caps. Max DD has no live metric source yet so its tile is hidden
              (showing "—" reads as broken; the field is surfaced in the strategy sheet's backtest equity panel). */}
          <GuardTile
            label="Daily loss"
            used={dailyLossUsed}
            cap={dailyLossCap}
            unit="usd"
            onCapChange={(n) => saveCap({ max_daily_loss: n })}
          />
          <GuardTile
            label="Exposure"
            used={exposureUsed}
            cap={globalCap}
            unit="usd"
            onCapChange={(n) => saveCap({ global_max_notional: n })}
          />
          {/* Spacer to keep the 3-column kpi-guard grid balanced after removing Max DD tile. */}
          <div />
          </div>

          {/* Capital allocation by venue — honest "No live capital deployed" until something is live. */}
          <div className="card dh">
            <div className="card-hdr">
              <span className="card-lbl">Capital allocation</span>
            </div>
            <div className="card-body">
              <AllocDonut venues={isLive ? venues : []} />
            </div>
          </div>
        </div>

        {/* Open positions (left) + Recent trades (right). `dash-tables` decouples their heights so expanding
            Open positions ("See all") never resizes/moves the Recent-trades card beside it. */}
        <div className="kgrid dash-split dash-tables" style={{ gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
          {/* Open positions — labelled by money state so a paper position is never read as live capital. */}
          <div className="card dh">
            <div className="card-hdr">
              <span className="card-lbl">
                Open positions{" "}
                {isLive ? (
                  <span className="badge badge-up" style={{ marginLeft: 4 }}>
                    Live
                  </span>
                ) : null}
              </span>
              {positions.length > POS_LIM ? (
                <button className="seeall-btn" onClick={() => setShowAllPositions((v) => !v)}>
                  {showAllPositions ? "Show less" : "See all →"}
                </button>
              ) : null}
            </div>
            <div className="card-body">
              {positions.length === 0 ? (
                <EmptyState
                  title="No open positions"
                  hint={
                    isLive
                      ? "Armed, but nothing is filled yet. Positions appear here as the engine trades within its caps."
                      : "Nothing is at risk live while disarmed. This is the honest empty state — no fabricated positions."
                  }
                />
              ) : (
                <table className="mini-tbl">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Venue</th>
                      <th className="r">Qty</th>
                      <th className="r">Avg price</th>
                      <th className="r">Unrealized P&amp;L</th>
                      <th className="r">Close</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shownPositions.map((p, i) => (
                      <tr key={`${p.instrument_id}-${p.venue}-${i}`}>
                        <td style={{ fontWeight: 500, color: "var(--fg)" }}>{p.symbol}</td>
                        <td className="muted">{p.venue}</td>
                        <td className="r tab muted">{p.qty}</td>
                        <td className="r tab muted">{formatUsd(p.avg_price)}</td>
                        <td className={cn("r tab", p.unrealized_pnl >= 0 ? "up" : "dn")}>
                          {formatSigned(p.unrealized_pnl)}
                        </td>
                        <td className="r">
                          <button
                            className="btn btn-ghost btn-xs"
                            onClick={() => defund("strategy", p.instrument_id)}
                            disabled={defundingPosition === p.instrument_id}
                          >
                            Close
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* Live orders control panel — the engine's real-venue orders (is_paper=0 only). Always shown so the
              operator has a fixed place to watch + cancel; an honest empty state when nothing has routed live.
              Cancel is a real money-path control (confirm → POST /live/orders/{id}/cancel → refresh). */}
          <div className="card dh">
            <div className="card-hdr">
              <span className="card-lbl">
                Live orders{" "}
                {liveOrders.length > 0 ? (
                  <span className="badge badge-up" style={{ marginLeft: 4 }}>
                    {liveOrders.filter((o) => o.status === "working").length} working
                  </span>
                ) : null}
              </span>
            </div>
            <div className="card-body">
              {liveOrders.length === 0 ? (
                <EmptyState
                  title="No live orders — nothing armed"
                  hint={
                    connected
                      ? "Orders appear here the moment a strategy is armed and the engine routes a real order. Sim and paper orders are never shown here."
                      : "Engine not connected — live orders appear here once it is reachable."
                  }
                />
              ) : (
                <table className="mini-tbl">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Venue</th>
                      <th>Side</th>
                      <th className="r">Qty</th>
                      <th className="r">Price</th>
                      <th>Status</th>
                      <th className="r">Cancel</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liveOrders.map((o, i) => (
                      <tr key={`${o.order_id}-${i}`}>
                        <td style={{ fontWeight: 500, color: "var(--fg)" }}>{o.symbol}</td>
                        <td className="muted">{o.venue}</td>
                        <td className={cn(o.side === "buy" ? "up" : "dn")}>{o.side}</td>
                        <td className="r tab muted">{o.qty}</td>
                        <td className="r tab muted">{formatUsd(o.price)}</td>
                        <td>
                          {o.status === "working" ? (
                            <span className="badge badge-run">working</span>
                          ) : (
                            <span className="badge badge-muted">canceled</span>
                          )}
                        </td>
                        <td className="r">
                          {o.status === "working" ? (
                            <button
                              className="btn btn-ghost btn-xs"
                              onClick={() => cancelOrder(o.order_id)}
                              disabled={cancelingOrder === o.order_id}
                              title={`Cancel order ${o.order_id} at ${o.venue}`}
                            >
                              {cancelingOrder === o.order_id ? "…" : "Cancel"}
                            </button>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>

      </div>

      {/* Rules modal — the hard-limit caps editor. */}
      {rulesOpen ? (
        <RulesModal
          rules={rules}
          connected={connected}
          onClose={() => setRulesOpen(false)}
          onSaved={(next) => {
            setRules(next);
            void refreshAll();
          }}
        />
      ) : null}

      {/* Liquidate modal — Stop all live trading (market-sell to USDC + disarm). */}
      <Modal
        open={liqOpen}
        onClose={() => setLiqOpen(false)}
        title="Stop all live trading"
        titleColor="var(--down)"
        actions={
          <>
            <button className="btn btn-ghost" onClick={() => setLiqOpen(false)}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={() => defund("all")} disabled={defundAllPending}>
              Stop &amp; sell to USDC
            </button>
          </>
        }
      >
        Sell every open live position to USDC, kill the running bots, and place no further orders.
        <br />
        <br />
        {liqAmount ? (
          <>
            <strong>
              {liqAmount} across {liqCount} strateg{liqCount === 1 ? "y" : "ies"}
            </strong>{" "}
            will be market-sold.
          </>
        ) : (
          <>Nothing is routed live right now — there is no live exposure to sell.</>
        )}{" "}
        The P&amp;L they produced <strong>stays on your live record</strong> — stopped strategies keep their
        stats. Paper strategies are not affected.
      </Modal>
    </Page>
  );
}
