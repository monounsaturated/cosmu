"use client";

// LaunchLiveModal — strategy-specific launch flow (Iris Bento Modal). Triggered from the /live page
// (per-strategy row) or /strategy/[id] detail page. Fetches fees live from GET /live/venue-catalog, lets the
// operator pick venue + asset, set a budget ($100 default, editable), and review the paper readiness signal.
// Arming calls POST /live/launch (the existing interlock path). The 5 interlocks remain the hard execution
// safety; paper maturity (>= PAPER_MIN_DAYS net-positive) is a HARD precondition for arming — a "not yet
// proven" strategy is refused unless explicitly override-launched.
//
// Venue key-gating: venues whose `configured` flag is false are greyed-out and unselectable. The `configured`
// flag comes from the engine (server-side key check) — keys are NEVER sent to the browser. Per-control
// in-flight flag + 8s AbortController, always cleared in `finally`.

import { useEffect, useState } from "react";
import type {
  LaunchActivateResponse,
  VenueCatalogResponse,
  VenueFeeInfo,
} from "./contracts";
import { Modal } from "@/components/ui/modal";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

const DEFAULT_GLOBAL_CAP = 1000;
const DEFAULT_MAX_DAILY_LOSS = 50;

interface Props {
  /** The gate-passed strategy to launch. */
  versionId: string;
  strategyName: string;
  onClose: () => void;
  onArmed?: (response: LaunchActivateResponse) => void;
}

export function LaunchLiveModal({ versionId, strategyName, onClose, onArmed }: Props) {
  const [catalog, setCatalog] = useState<VenueCatalogResponse | null>(null);
  const [catalogConnected, setCatalogConnected] = useState(true);
  const [selectedVenueId, setSelectedVenueId] = useState<string>("");
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [budget, setBudget] = useState<number>(100);
  const [perStrategyCap, setPerStrategyCap] = useState<number>(100);
  const [globalCap, setGlobalCap] = useState<number>(DEFAULT_GLOBAL_CAP);
  const [maxDailyLoss, setMaxDailyLoss] = useState<number>(DEFAULT_MAX_DAILY_LOSS);
  const [result, setResult] = useState<LaunchActivateResponse | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);

  // Fetch the venue catalog (fees + configured flags) on mount.
  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      setCatalogConnected(false);
      return;
    }
    engineFetch("/live/venue-catalog")
      .then((r) => (r.ok ? r.json() : null))
      .then((data: VenueCatalogResponse | null) => {
        if (!data) {
          setCatalogConnected(false);
          return;
        }
        setCatalog(data);
        const firstVenue = data.venues.find((v) => v.configured && v.live_enabled);
        if (firstVenue) {
          setSelectedVenueId(firstVenue.id);
          const firstInstr = data.instruments.find((i) => i.venue_id === firstVenue.id);
          if (firstInstr) setSelectedSymbol(firstInstr.symbol);
        }
      })
      .catch(() => setCatalogConnected(false));
  }, []);

  // Keep perStrategyCap in sync with budget as a convenience default.
  useEffect(() => {
    setPerStrategyCap(budget);
  }, [budget]);

  const selectedVenue = catalog?.venues.find((v) => v.id === selectedVenueId) ?? null;
  const venueInstruments = catalog?.instruments.filter((i) => i.venue_id === selectedVenueId) ?? [];

  function handleVenueChange(venueId: string) {
    setSelectedVenueId(venueId);
    const instr = catalog?.instruments.find((i) => i.venue_id === venueId);
    setSelectedSymbol(instr?.symbol ?? "");
    setResult(null);
    setNote(null);
  }

  async function handleConfirm() {
    if (pending) return;
    if (!ENGINE_CONFIGURED) {
      setNote("Engine not connected — cannot launch.");
      return;
    }
    if (!selectedVenueId || !selectedSymbol) {
      setNote("Pick a venue and asset first.");
      return;
    }
    if (!selectedVenue?.configured) {
      setNote(`Venue "${selectedVenueId}" has no API keys configured. Add them in the engine env first.`);
      return;
    }
    setNote(null);
    setPending(true);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8000);
    try {
      const res = await engineFetch("/live/launch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          version_id: versionId,
          venue_id: selectedVenueId,
          symbol: selectedSymbol,
          budget,
          per_strategy_cap: perStrategyCap,
          global_cap: globalCap,
          max_daily_loss: maxDailyLoss,
          confirm: true,
        }),
        signal: ctrl.signal,
      });
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        setNote(err.detail ?? `Engine error ${res.status}`);
        return;
      }
      const data = (await res.json()) as LaunchActivateResponse;
      setResult(data);
      setConfirmed(true);
      onArmed?.(data);
    } catch {
      setNote("Engine not reachable — cannot launch live.");
    } finally {
      clearTimeout(timer);
      setPending(false);
    }
  }

  const canConfirm = !pending && !!selectedVenueId && !!selectedSymbol && !!selectedVenue?.configured;

  return (
    <Modal
      open
      onClose={onClose}
      title={`Launch live — ${strategyName}`}
      width={560}
      actions={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {confirmed ? "Close" : "Cancel"}
          </button>
          {!confirmed && catalogConnected ? (
            <button className="btn btn-iris" onClick={handleConfirm} disabled={!canConfirm}>
              Confirm — launch live
            </button>
          ) : null}
        </>
      }
    >
      <p style={{ marginBottom: 14 }}>
        Pick a venue + asset, set a budget, and confirm. The 5 interlocks remain the hard safety; nothing
        trades until all clear.
      </p>

      {!catalogConnected ? (
        <div style={{ color: "var(--down)", fontSize: 12 }}>
          Engine not reachable — venue catalog unavailable. Connect the engine to launch live.
        </div>
      ) : null}

      {catalogConnected && !confirmed ? (
        <>
          {/* Venue picker */}
          <div className="kpi-label" style={{ marginBottom: 6 }}>Venue</div>
          {catalog ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 14 }}>
              {catalog.venues.map((v) => {
                const isSelected = v.id === selectedVenueId;
                const disabled = !v.configured || !v.live_enabled;
                return (
                  <button
                    key={v.id}
                    disabled={disabled}
                    onClick={() => !disabled && handleVenueChange(v.id)}
                    aria-pressed={isSelected}
                    className={cn("chip", isSelected && "active")}
                    style={{
                      width: "100%",
                      justifyContent: "flex-start",
                      gap: 8,
                      opacity: disabled ? 0.5 : 1,
                      cursor: disabled ? "not-allowed" : "pointer"
                    }}
                  >
                    <span style={{ fontWeight: 500, color: "var(--fg)" }}>{v.name}</span>
                    <span className="badge badge-muted">{v.kind}</span>
                    {!v.live_enabled ? <span className="badge badge-gold">no live adapter</span> : null}
                    {v.live_enabled && !v.configured ? <span className="badge badge-gold">no keys</span> : null}
                    {v.configured && v.live_enabled ? <span className="badge badge-up">connected</span> : null}
                    <span className="quiet" style={{ marginLeft: "auto", fontSize: 10.5 }}>
                      taker {v.taker_fee_bps} · maker {v.maker_fee_bps} bps
                    </span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="quiet" style={{ padding: "12px 0", fontSize: 12 }}>Loading venues…</div>
          )}

          {/* Asset picker */}
          {venueInstruments.length > 0 ? (
            <>
              <div className="kpi-label" style={{ marginBottom: 6 }}>Asset</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
                {venueInstruments.map((i) => (
                  <button
                    key={i.id}
                    onClick={() => setSelectedSymbol(i.symbol)}
                    className={cn("chip", selectedSymbol === i.symbol && "active")}
                  >
                    {i.symbol}
                  </button>
                ))}
              </div>
            </>
          ) : null}

          {/* Fee display */}
          {selectedVenue ? <FeeDisplay venue={selectedVenue} /> : null}

          {/* Budget + risk settings */}
          <div className="kpi-label" style={{ marginBottom: 6, marginTop: 14 }}>Budget &amp; risk</div>
          <div className="kgrid" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <NumField label="Budget (default $100)" value={budget} onChange={setBudget} />
            <NumField label="Max daily loss" value={maxDailyLoss} onChange={setMaxDailyLoss} />
            <NumField label="Per-strategy cap" value={perStrategyCap} onChange={setPerStrategyCap} />
            <NumField label="Global cap" value={globalCap} onChange={setGlobalCap} />
          </div>

          <p className="quiet" style={{ fontSize: 11, lineHeight: 1.6, marginTop: 12 }}>
            Safety: the engine only submits a real order when live is on, execution keys are present, the gate
            has passed on real data, caps are available, and the kill-switch is clear. Otherwise it runs in
            Paper.
          </p>
        </>
      ) : null}

      {confirmed && result ? <LaunchOutcome result={result} strategyName={strategyName} /> : null}

      {note ? <div style={{ marginTop: 12, color: "var(--down)", fontSize: 12 }}>{note}</div> : null}
    </Modal>
  );
}

function FeeDisplay({ venue }: { venue: VenueFeeInfo }) {
  const hasTiers = venue.fee_tiers.length > 1;
  return (
    <div
      style={{
        border: "1px solid var(--hairline)",
        borderRadius: "var(--r-sm)",
        padding: 10,
        background: "color-mix(in oklab,var(--surf2) 70%,transparent)"
      }}
    >
      <div className="kpi-label" style={{ marginBottom: 6 }}>{venue.name} fees · real, from engine</div>
      {hasTiers ? (
        <div className="tbl-scroll">
          <table className="mini-tbl">
            <thead>
              <tr>
                <th>30d volume</th>
                <th className="r">Maker bps</th>
                <th className="r">Taker bps</th>
              </tr>
            </thead>
            <tbody>
              {venue.fee_tiers.map((t, i) => (
                <tr key={i}>
                  <td className="muted">
                    {t.min_volume_30d_usd === 0 ? "base (all accounts)" : `≥ $${(t.min_volume_30d_usd / 1_000_000).toFixed(0)}M`}
                  </td>
                  <td className="r tab">{t.maker_fee_bps}</td>
                  <td className="r tab">{t.taker_fee_bps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="muted" style={{ fontSize: 12 }}>
          Flat: maker {venue.maker_fee_bps} bps · taker {venue.taker_fee_bps} bps
        </div>
      )}
    </div>
  );
}

function LaunchOutcome({ result, strategyName }: { result: LaunchActivateResponse; strategyName: string }) {
  const proven = result.readiness === "proven";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {result.armed ? (
        <div className="up" style={{ fontSize: 12.5 }}>
          <strong>Armed — {strategyName} is live</strong>
          <div className="quiet" style={{ fontSize: 11, marginTop: 2 }}>
            {result.venue_id} · {result.symbol} · budget ${result.budget.toFixed(0)}
          </div>
        </div>
      ) : (
        <div style={{ color: "var(--down)", fontSize: 12 }}>
          {result.reason ?? "Not armed — check the interlocks."}
        </div>
      )}

      <div className={cn(proven ? "up" : "quiet")} style={{ fontSize: 11.5, lineHeight: 1.6 }}>
        <span style={{ fontWeight: 500 }}>Paper readiness: </span>
        {proven
          ? `proven — ${result.paper_days?.toFixed(0) ?? "30"}+ days net-positive in Paper`
          : result.paper_days != null
            ? `not yet proven — ${result.paper_days.toFixed(0)} days so far (needs net-positive past the Paper threshold)`
            : "no Paper track yet — not eligible to arm"}
        <span className="quiet"> · required to arm; the 5 interlocks remain the hard execution gate</span>
      </div>
    </div>
  );
}

// A compact labelled numeric field (bento). Used for the budget + risk caps.
function NumField({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label style={{ display: "block" }}>
      <span className="kpi-label" style={{ marginBottom: 4, display: "block" }}>{label}</span>
      <input
        className="search-input"
        style={{ width: "100%", height: 30 }}
        type="number"
        min={0}
        inputMode="decimal"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={label}
      />
    </label>
  );
}
