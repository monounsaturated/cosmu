"use client";

// module: GoLiveModal — the in-UI "Go Live" flow for a paper-stage strategy. It collects the venue, symbol,
// budget and the hard caps, then POSTs /live/launch (the SAME endpoint the CLI used, the ONLY writer of
// status='live'). The engine — never this UI — decides whether arming is allowed: it enforces venue keys,
// paper maturity (>= PAPER_MIN_DAYS net-positive), regime fit, and the global toggle/caps/kill-switch
// interlocks. We surface its verdict verbatim, success OR refusal reason. Nothing here moves money by itself.
//
// SAFETY, in plain words (shown to the operator): arming records intent; a REAL order is submitted only when
// ALL hold — global live toggle ON + venue keys present + gate passed + caps available + no kill-switch — and
// the engine runs TESTNET first. Venues with a wired execution adapter (Binance spot, Alpaca equities,
// Polymarket prediction CLOB) can arm once their keys are on the server; every other venue is shown but cannot
// arm ("not connected").

import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { engineFetch } from "@/lib/engine";
import { formatVenue } from "@/lib/utils";
import type { LaunchActivateResponse, VenueCatalogResponse, VenueFeeInfo } from "@cosmu/contracts-ts";

// Sensible, conservative starting caps (USD) for a first live arming — the operator tunes them in the form.
const DEFAULTS = { budget: 100, perStrategyCap: 250, globalCap: 1000, maxDailyLoss: 50 };

type Phase = "form" | "submitting" | "done";

export function GoLiveModal({
  open,
  onClose,
  versionId,
  strategyName,
  defaultSymbol
}: {
  open: boolean;
  onClose: () => void;
  versionId: string;
  strategyName: string;
  // A reasonable default trading symbol for the venue (e.g. "BTCUSDT" for Binance spot). Editable.
  defaultSymbol?: string | null;
}) {
  const [venues, setVenues] = useState<VenueFeeInfo[] | null>(null);
  const [venueId, setVenueId] = useState("binance");
  const [symbol, setSymbol] = useState(defaultSymbol || "BTCUSDT");
  const [budget, setBudget] = useState(DEFAULTS.budget);
  const [perStrategyCap, setPerStrategyCap] = useState(DEFAULTS.perStrategyCap);
  const [globalCap, setGlobalCap] = useState(DEFAULTS.globalCap);
  const [maxDailyLoss, setMaxDailyLoss] = useState(DEFAULTS.maxDailyLoss);
  const [confirm, setConfirm] = useState(false);
  const [phase, setPhase] = useState<Phase>("form");
  const [result, setResult] = useState<LaunchActivateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load the venue catalog once the modal opens so we can show which venues are actually wired (configured).
  useEffect(() => {
    if (!open || venues) return;
    let alive = true;
    engineFetch("/live/venue-catalog")
      .then((r) => (r.ok ? (r.json() as Promise<VenueCatalogResponse>) : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        if (!alive) return;
        setVenues(d.venues);
        // Prefer Binance if it's configured (the one armed venue), else the first configured venue.
        const armable = d.venues.filter((v) => v.configured);
        const binance = armable.find((v) => v.id === "binance");
        if (binance) setVenueId("binance");
        else if (armable[0]) setVenueId(armable[0].id);
      })
      .catch(() => alive && setVenues([]));
    return () => {
      alive = false;
    };
  }, [open, venues]);

  const selected = venues?.find((v) => v.id === venueId);
  const venueConfigured = selected?.configured ?? venueId === "binance";
  // Polymarket (prediction CLOB) trades YES/NO shares priced 0–1 (a probability), addressed by a market label
  // or CLOB token id — not a 'BTCUSDT'-style pair — so the symbol hint + budget framing adapt to the venue.
  const isPrediction = selected?.kind === "prediction";

  async function submit() {
    setError(null);
    setPhase("submitting");
    try {
      const res = await engineFetch("/live/launch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          version_id: versionId,
          venue_id: venueId,
          symbol,
          budget,
          per_strategy_cap: perStrategyCap,
          global_cap: globalCap,
          max_daily_loss: maxDailyLoss,
          confirm
        })
      });
      if (!res.ok) {
        setError(`engine returned ${res.status}`);
        setPhase("form");
        return;
      }
      const data = (await res.json()) as LaunchActivateResponse;
      setResult(data);
      setPhase("done");
    } catch {
      setError("could not reach the engine");
      setPhase("form");
    }
  }

  function reset() {
    setPhase("form");
    setResult(null);
    setError(null);
    setConfirm(false);
    onClose();
  }

  const canSubmit = confirm && venueConfigured && symbol.trim().length > 0 && budget > 0 && phase === "form";

  return (
    <Modal
      open={open}
      onClose={reset}
      title={`Go live — ${strategyName}`}
      titleColor="var(--down)"
      actions={
        phase === "done" ? (
          <button type="button" className="btn btn-sm" onClick={reset}>
            Close
          </button>
        ) : (
          <>
            <button type="button" className="btn btn-sm" onClick={reset}>
              Cancel
            </button>
            <button type="button" className="btn btn-sm btn-danger" disabled={!canSubmit} onClick={submit}>
              {phase === "submitting" ? "Arming…" : "Arm live"}
            </button>
          </>
        )
      }
    >
      {phase === "done" && result ? (
        <div className="golive-result">
          {result.armed ? (
            <p className="ai-body">
              <strong style={{ color: "var(--up)" }}>Armed.</strong> <strong style={{ color: "var(--fg)" }}>{strategyName}</strong>{" "}
              is now <strong className="dn">live</strong> on <strong style={{ color: "var(--fg)" }}>{formatVenue(result.venue_id)}</strong>{" "}
              ({result.symbol}), budget ${result.budget.toLocaleString()}. A real order still fires only with the
              global live toggle ON + no kill-switch; the engine runs <strong>testnet</strong> until you switch it
              to live mode. Forward-test readiness: <strong>{result.readiness ?? "—"}</strong>
              {result.overridden ? <span className="dn"> · armed via override (unproven)</span> : null}.
            </p>
          ) : (
            <p className="ai-body">
              <strong style={{ color: "var(--down)" }}>Not armed.</strong> The engine refused:{" "}
              <span className="quiet">{result.reason ?? "not eligible"}</span>
              {result.paper_days != null ? (
                <span className="quiet"> · {Math.round(result.paper_days)}d forward, {result.readiness}</span>
              ) : null}
              . Nothing changed — this is the honest live-eligibility gate (paper maturity + regime), not a bug.
            </p>
          )}
        </div>
      ) : (
        <div className="golive-form">
          <p className="ai-body" style={{ marginBottom: 12 }}>
            Arming records intent. A <strong>real order</strong> is submitted only when ALL hold: global live toggle
            ON · venue keys present · gate passed · caps available · no kill-switch. The engine runs{" "}
            <strong>testnet first</strong> — validate there before switching to live mode. A venue can arm only once
            its keys are on the server (the rest show &ldquo;not connected&rdquo;).
          </p>
          {isPrediction ? (
            <p className="quiet" style={{ fontSize: 11, marginBottom: 12 }}>
              <strong>Polymarket</strong> trades prediction-market shares priced <strong>0–1</strong> (a probability);
              orders are <strong>limit</strong> orders at that price, and Budget/caps are USDC notional. US-restricted —
              set a non-US jurisdiction to arm.
            </p>
          ) : null}

          <label className="golive-row">
            <span>Venue</span>
            <select value={venueId} onChange={(e) => setVenueId(e.target.value)} className="golive-input">
              {(venues ?? [{ id: "binance", name: "Binance", configured: true } as VenueFeeInfo]).map((v) => (
                <option key={v.id} value={v.id} disabled={!v.configured}>
                  {formatVenue(v.id)}
                  {v.configured ? "" : " — not connected"}
                </option>
              ))}
            </select>
          </label>

          {selected ? (
            <div className="golive-fee-info" style={{ fontSize: 11, color: "var(--quiet)", marginBottom: 8, paddingLeft: 2 }}>
              <span data-tip="Taker fee charged by the exchange per fill (basis points = 0.01%).">
                Taker fee: <strong style={{ color: "var(--fg)" }}>{selected.taker_fee_bps} bps</strong>
              </span>
              <span style={{ margin: "0 8px", opacity: 0.4 }}>·</span>
              <span data-tip="Fixed half-spread the backtest charged for this venue (market depth estimate).">
                Slippage: <strong style={{ color: "var(--fg)" }}>{selected.slippage_bps} bps</strong>
              </span>
              <span style={{ margin: "0 8px", opacity: 0.4 }}>·</span>
              <span className="quiet" style={{ fontSize: 10.5 }}>
                1 bps = 0.01% of trade notional
              </span>
            </div>
          ) : null}

          <label className="golive-row">
            <span>{isPrediction ? "Market (label or CLOB token id)" : "Symbol"}</span>
            <input
              className="golive-input"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder={isPrediction ? "PM-FED-CUT-2026" : "BTCUSDT"}
            />
          </label>

          <label className="golive-row">
            <span data-tip={isPrediction ? "USDC notional this strategy may deploy (shares × probability)." : "Capital this strategy may deploy live."}>
              {isPrediction ? "Budget (USDC)" : "Budget ($)"}
            </span>
            <input className="golive-input" type="number" min={0} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
          </label>

          <div className="golive-caps">
            <label className="golive-row">
              <span data-tip="Hard cap on notional for THIS strategy.">Per-strategy cap ($)</span>
              <input className="golive-input" type="number" min={0} value={perStrategyCap} onChange={(e) => setPerStrategyCap(Number(e.target.value))} />
            </label>
            <label className="golive-row">
              <span data-tip="Hard cap on total live notional across all strategies.">Global cap ($)</span>
              <input className="golive-input" type="number" min={0} value={globalCap} onChange={(e) => setGlobalCap(Number(e.target.value))} />
            </label>
            <label className="golive-row">
              <span data-tip="Kill-switch: live halts for the day once losses hit this.">Daily-loss kill-switch ($)</span>
              <input className="golive-input" type="number" min={0} value={maxDailyLoss} onChange={(e) => setMaxDailyLoss(Number(e.target.value))} />
            </label>
          </div>

          {!venueConfigured ? (
            <p className="quiet" style={{ fontSize: 11, color: "var(--down)" }}>
              {formatVenue(venueId)} has no API keys on the server — it can&apos;t arm. Pick Binance, or add its keys.
            </p>
          ) : null}

          <label className="golive-confirm">
            <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            <span>
              I understand this arms <strong style={{ color: "var(--fg)" }}>{strategyName}</strong> for live trading on{" "}
              {formatVenue(venueId)} under the caps above.
            </span>
          </label>

          {error ? <p className="quiet" style={{ fontSize: 11, color: "var(--down)" }}>{error}</p> : null}
        </div>
      )}
    </Modal>
  );
}
