"use client";

// module: LaunchLiveModal — strategy-specific launch flow. Triggered from the /live page (per-strategy
// row) or /strategy/[id] detail page. Fetches fees live from GET /live/venue-catalog, lets the operator
// pick venue + asset, set a budget ($100 default, editable), and review the forward-test readiness
// signal. Arming calls POST /live/launch (the existing interlock path). The 5 interlocks remain the
// hard execution safety; forward-test maturity (>= FORWARD_TEST_MIN_DAYS net-positive) is now a HARD
// precondition for arming — a "not yet proven" strategy is refused unless explicitly override-launched.
//
// Venue key-gating: venues whose `configured` flag is false are greyed-out and unselectable. The
// `configured` flag comes from the engine (server-side key check) — keys are NEVER sent to the browser.

import { useEffect, useState, useTransition } from "react";
import { AlertTriangle, CheckCircle2, Info, Lock, Power, Rocket, X } from "lucide-react";
import type {
  LaunchActivateResponse,
  VenueCatalogResponse,
  VenueFeeInfo,
  VenueInstrumentInfo,
} from "./contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  const [pending, startTransition] = useTransition();

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
        // Auto-select the first configured+live_enabled venue and its first instrument.
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
  const venueInstruments =
    catalog?.instruments.filter((i) => i.venue_id === selectedVenueId) ?? [];

  function handleVenueChange(venueId: string) {
    setSelectedVenueId(venueId);
    const instr = catalog?.instruments.find((i) => i.venue_id === venueId);
    setSelectedSymbol(instr?.symbol ?? "");
    setResult(null);
    setNote(null);
  }

  function handleConfirm() {
    if (!ENGINE_CONFIGURED) {
      setNote("Engine not connected — cannot launch.");
      return;
    }
    if (!selectedVenueId || !selectedSymbol) {
      setNote("Pick a venue and asset first.");
      return;
    }
    if (!selectedVenue?.configured) {
      setNote(`Venue "${selectedVenueId}" has no API keys configured. Add them in Railway env first.`);
      return;
    }
    setNote(null);
    startTransition(async () => {
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
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({})) as { detail?: string };
          setNote(err.detail ?? `Engine error ${res.status}`);
          return;
        }
        const data = (await res.json()) as LaunchActivateResponse;
        setResult(data);
        setConfirmed(true);
        onArmed?.(data);
      } catch {
        setNote("Engine not reachable — cannot launch live.");
      }
    });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="launch-modal-title">
      {/* Backdrop */}
      <button aria-label="Close" onClick={onClose} className="animate-overlay-in absolute inset-0 bg-black/50" />

      {/* Panel */}
      <div className="glass animate-menu-in relative w-full max-w-lg rounded-2xl border border-border bg-surface p-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 id="launch-modal-title" className="flex items-center gap-2 text-base font-semibold text-foreground">
              <Rocket className="size-4 text-iris-soft" /> Launch live — {strategyName}
            </h2>
            <p className="mt-1 text-[12.5px] text-muted">
              Pick a venue + asset, set a budget, and confirm. The 5 interlocks remain the hard safety; nothing trades until all clear.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-quiet hover:text-foreground">
            <X className="size-5" />
          </button>
        </div>

        {/* Engine not connected */}
        {!catalogConnected && (
          <div className="mt-4 flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            Engine not reachable — venue catalog unavailable. Connect the engine to launch live.
          </div>
        )}

        {catalogConnected && !confirmed && (
          <div className="mt-4 space-y-4">
            {/* Venue picker */}
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">Venue</div>
              {catalog ? (
                <VenuePicker
                  venues={catalog.venues}
                  selected={selectedVenueId}
                  onChange={handleVenueChange}
                />
              ) : (
                <div className="py-4 text-center text-[12.5px] text-muted">Loading venues…</div>
              )}
            </div>

            {/* Asset picker */}
            {venueInstruments.length > 0 && (
              <div>
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">Asset</div>
                <div className="flex flex-wrap gap-2">
                  {venueInstruments.map((i) => (
                    <button
                      key={i.id}
                      onClick={() => setSelectedSymbol(i.symbol)}
                      className={cn(
                        "rounded-md border px-3 py-1.5 text-[12.5px] font-medium transition-colors",
                        selectedSymbol === i.symbol
                          ? "border-iris/60 bg-iris/10 text-iris-soft"
                          : "border-border bg-surface-2/40 text-muted hover:border-iris/30 hover:text-foreground"
                      )}
                    >
                      {i.symbol}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Fee display */}
            {selectedVenue && <FeeDisplay venue={selectedVenue} />}

            {/* Budget + risk settings */}
            <div>
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">Budget & risk</div>
              <div className="grid grid-cols-2 gap-2">
                <AmountInput label="Budget (default $100)" value={budget} onChange={(v) => setBudget(v)} />
                <AmountInput label="Max daily loss" value={maxDailyLoss} onChange={setMaxDailyLoss} />
                <AmountInput label="Per-strategy cap" value={perStrategyCap} onChange={setPerStrategyCap} />
                <AmountInput label="Global cap" value={globalCap} onChange={setGlobalCap} />
              </div>
            </div>

            {/* Safety note */}
            <p className="rounded-md border border-border/60 bg-surface-2/40 px-3 py-2 text-[11.5px] leading-relaxed text-quiet">
              Safety: the engine only submits a real order when live is on, execution keys are present, the gate has passed on real data, caps are available, and the kill-switch is clear. Otherwise it runs in Simulation.
            </p>
          </div>
        )}

        {/* Post-confirm: show outcome */}
        {confirmed && result && (
          <LaunchOutcome result={result} strategyName={strategyName} />
        )}

        {/* Inline note/error */}
        {note && (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <span>{note}</span>
          </div>
        )}

        {/* Actions */}
        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" size="md" onClick={onClose}>
            {confirmed ? "Close" : "Cancel"}
          </Button>
          {!confirmed && catalogConnected && (
            <Button
              variant="primary"
              size="md"
              onClick={handleConfirm}
              disabled={pending || !selectedVenueId || !selectedSymbol || !selectedVenue?.configured}
            >
              <Power className="size-4" /> Confirm — launch live
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────────────────────

function VenuePicker({
  venues,
  selected,
  onChange,
}: {
  venues: VenueFeeInfo[];
  selected: string;
  onChange: (id: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      {venues.map((v) => {
        const isSelected = v.id === selected;
        const disabled = !v.configured || !v.live_enabled;
        return (
          <button
            key={v.id}
            disabled={disabled}
            onClick={() => !disabled && onChange(v.id)}
            aria-pressed={isSelected}
            className={cn(
              "flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors",
              disabled
                ? "cursor-not-allowed border-border/40 bg-surface/30 opacity-50"
                : isSelected
                  ? "border-iris/60 bg-iris/10"
                  : "border-border bg-surface-2/40 hover:border-iris/30"
            )}
          >
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className={cn("text-[13px] font-medium", disabled ? "text-muted" : "text-foreground")}>
                  {v.name}
                </span>
                <Badge variant="muted">{v.kind}</Badge>
                {!v.live_enabled && <Badge variant="warn">no live adapter</Badge>}
                {v.live_enabled && !v.configured && <Badge variant="warn">no keys</Badge>}
                {v.configured && v.live_enabled && <Badge variant="up">connected</Badge>}
              </div>
              <div className="mt-0.5 text-[11px] text-quiet">
                taker {v.taker_fee_bps} bps · maker {v.maker_fee_bps} bps (base)
              </div>
            </div>
            {!v.configured && <Lock className="size-4 shrink-0 text-quiet" />}
          </button>
        );
      })}
    </div>
  );
}

function FeeDisplay({ venue }: { venue: VenueFeeInfo }) {
  const hasTiers = venue.fee_tiers.length > 1;
  return (
    <div className="rounded-md border border-border/60 bg-surface-2/30 p-3">
      <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
        <Info className="size-3" />
        {venue.name} fees (real, fetched from engine)
      </div>
      {hasTiers ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[11.5px]">
            <thead>
              <tr className="border-b border-border/50 text-[10.5px] uppercase tracking-wide text-quiet">
                <th className="py-1 text-left font-medium">30d volume</th>
                <th className="py-1 text-right font-medium">Maker bps</th>
                <th className="py-1 text-right font-medium">Taker bps</th>
              </tr>
            </thead>
            <tbody>
              {venue.fee_tiers.map((t, i) => (
                <tr key={i} className="border-b border-border/30 last:border-0">
                  <td className="py-1 text-muted">
                    {t.min_volume_30d_usd === 0 ? "base (all accounts)" : `≥ $${(t.min_volume_30d_usd / 1_000_000).toFixed(0)}M`}
                  </td>
                  <td className="py-1 text-right tabular text-foreground">{t.maker_fee_bps}</td>
                  <td className="py-1 text-right tabular text-foreground">{t.taker_fee_bps}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-[12.5px] text-muted">
          Flat: maker {venue.maker_fee_bps} bps · taker {venue.taker_fee_bps} bps
        </div>
      )}
    </div>
  );
}

function LaunchOutcome({ result, strategyName }: { result: LaunchActivateResponse; strategyName: string }) {
  const proven = result.readiness === "proven";
  return (
    <div className="mt-4 space-y-3">
      {result.armed ? (
        <div className="flex items-start gap-2 rounded-md border border-up/35 bg-up/10 px-3 py-2.5 text-[12.5px] text-up">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <div>
            <div className="font-semibold">Armed — {strategyName} is live</div>
            <div className="mt-0.5 text-[11.5px] text-up/80">
              {result.venue_id} · {result.symbol} · budget ${result.budget.toFixed(0)}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
          <span>{result.reason ?? "Not armed — check the interlocks."}</span>
        </div>
      )}

      {/* Forward-test readiness — a HARD precondition for arming (refused unless override-launched) */}
      <div className={cn(
        "flex items-start gap-2 rounded-md border px-3 py-2 text-[11.5px]",
        proven
          ? "border-up/30 bg-up/8 text-up"
          : "border-border/60 bg-surface-2/30 text-quiet"
      )}>
        <Info className="mt-0.5 size-3.5 shrink-0" />
        <div>
          <span className="font-medium">Simulation readiness: </span>
          {proven
            ? `proven — ${result.forward_test_days?.toFixed(0) ?? "30"}+ days net-positive in Simulation`
            : result.forward_test_days != null
              ? `not yet proven — ${result.forward_test_days.toFixed(0)} days so far (needs net-positive past the Simulation threshold)`
              : "no Simulation track yet — not eligible to arm"}
          <span className="ml-1 text-quiet opacity-80">· required to arm; the 5 interlocks remain the hard execution gate</span>
        </div>
      </div>
    </div>
  );
}

function AmountInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wide text-quiet">{label}</span>
      <div className="mt-1 flex items-center rounded-md border border-border bg-surface-2/40 px-2.5">
        <span className="text-[12px] text-quiet">$</span>
        <input
          type="number"
          min={0}
          value={value}
          onChange={(e) => onChange(Math.max(0, Number(e.target.value)))}
          className="w-full bg-transparent py-2 pl-1 text-[13px] tabular text-foreground outline-none"
        />
      </div>
    </label>
  );
}
