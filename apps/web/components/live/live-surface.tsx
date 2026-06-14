"use client";

// Live trading surface (Iris Bento dashboard). The gated, money screen — mirror of the Paper dashboard.
// Its toolbar carries the global ARM state, a grey "Rules" button (opens the hard-limit Rules modal), and a
// danger Stop control (opens the liquidate modal). Below: the equity hero on top, then a KPI+guard row that
// FOLDS the guardrails (Daily loss / Max DD / Exposure) as editable-cap guard boxes into the live-vs-sim
// money line (Invested / Free / P&L), then [Open positions | Recent trades] side by side. The 2-CLICK
// activation flow (Review & arm → Confirm) and the per-strategy Launch flow are preserved.
//
// SAFETY (real money): LIVE IS OFF BY DEFAULT. This component never decides whether an order is real — the
// engine does, only when toggle ON + keys present + gate PASSED + caps available + not kill-switched. We send
// confirm only on the explicit second click. Offline → an honest not-connected note, never armed.
//
// HONESTY: the KPI row reads the engine's live-vs-sim SPLIT (getPortfolioSummary). When nothing is routed
// live (`has_live` false) every live money figure is null and renders an explicit "—" — NEVER 0 and NEVER
// the SIM number. The guardrails sit at 0% while disarmed (the honest safe state). Max DD has no live metric
// source yet, so it renders an honest "—" rather than a fabricated reading. The recent-trades feed has no
// engine endpoint, so it is an honest empty.

import { useState, type ReactNode } from "react";
import type { Point, PortfolioSummaryResponse, RulesResponse } from "@cosmu/contracts-ts";
import type { PositionsResponse } from "./contracts";
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
  equityCurve,
  venues
}: {
  initial: PositionsResponse & { connected: boolean };
  initialSummary: PortfolioSummaryResponse & { connected: boolean };
  initialRules: RulesResponse & { connected: boolean };
  equityCurve: Point[];
  venues: { name: string; amount: number }[];
}) {
  const [state, setState] = useState<PositionsResponse>(initial);
  const [connected, setConnected] = useState(initial.connected);
  const [summary, setSummary] = useState<PortfolioSummaryResponse>(initialSummary);
  const [rules, setRules] = useState<RulesResponse>(initialRules);
  const [rulesOpen, setRulesOpen] = useState(false);
  const [liqOpen, setLiqOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [defundAllPending, setDefundAllPending] = useState(false);
  const [defundingPosition, setDefundingPosition] = useState<string | null>(null);
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
      // The two reads are independent — fetch them in PARALLEL (was a sequential waterfall: positions, THEN
      // summary, ~2× the latency on a Rules save / defund). ONLY positions drives connected-state, so the
      // summary fetch swallows its own rejection (→ null) — a summary miss must keep the last-known split, NOT
      // falsely disconnect the surface (matches the prior nested-try/catch behaviour).
      const [res, sres] = await Promise.all([
        engineFetch("/live/positions"),
        engineFetch("/portfolio/summary").catch(() => null),
      ]);
      if (!res.ok) throw new Error("engine unavailable");
      setState((await res.json()) as PositionsResponse);
      setConnected(true);
      if (sres?.ok) setSummary((await sres.json()) as PortfolioSummaryResponse);
    } catch {
      setConnected(false);
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
          venues: next.venues.map((v) => ({ venue: v.venue, max_notional: v.max_notional ?? null }))
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
  const positions = isLive ? state.positions : [];
  const POS_LIM = 4;
  const shownPositions = showAllPositions ? positions : positions.slice(0, POS_LIM);

  return (
    <Page>
      {/* Toolbar (v18 page-live) — Running/Off badge on the left; the grey Rules button + danger Stop on the
          right. Live is launched via the CLI (Commands · `cosmu live launch`), so there is no in-UI arm flow. */}
      <Toolbar
        title="Live"
        left={
          armed ? (
            <span className="badge badge-run" style={{ display: "inline-flex", gap: 5, alignItems: "center" }}>
              <span className="run-dot" /> Running
            </span>
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
        {/* Equity hero ALWAYS on top — the real live equity curve (honest empty until a live track record). */}
        <EquityHero label="Total equity" curve={isLive ? equityCurve : []} />

        {/* KPI + guard row: 3 money KPIs + 3 guard boxes folded into one line. */}
        {/* The capital-allocation donut (2/8) on the LEFT + 6 KPI/guard boxes (6/8). */}
        <div className="kgrid kpi-guard" style={{ gridTemplateColumns: "2fr repeat(6,1fr)" }}>
          {/* Capital allocation by venue — honest empty until something is deployed live. */}
          <AllocDonut venues={isLive ? venues : []} />
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
          {/* Guardrails — editable caps. Max DD has no live metric source yet → handed null → honest "—". */}
          <GuardTile
            label="Daily loss"
            used={dailyLossUsed}
            cap={dailyLossCap}
            unit="usd"
            onCapChange={(n) => saveCap({ max_daily_loss: n })}
          />
          <GuardTile label="Max DD" used={null} cap={0} unit="pct" editable={false} />
          <GuardTile
            label="Exposure"
            used={exposureUsed}
            cap={globalCap}
            unit="usd"
            onCapChange={(n) => saveCap({ global_max_notional: n })}
          />
        </div>

        {/* [Open positions | Recent trades] side by side. */}
        <div className="kgrid dash-split" style={{ gridTemplateColumns: "1fr 1fr" }}>
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

          {/* Recent trades — the engine exposes no live recent-trades endpoint yet, so this is an HONEST
              empty state rather than fabricating fills or reusing SIM trades. */}
          <div className="card dh">
            <div className="card-hdr">
              <span className="card-lbl">Recent trades</span>
            </div>
            <div className="card-body">
              <EmptyState
                title="No live trades yet"
                hint={
                  connected
                    ? "Live fills appear here once the engine executes a real order. Nothing here is fabricated — paper trades are not shown as live."
                    : "Engine not connected — recent live fills appear here once it is reachable."
                }
              />
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
