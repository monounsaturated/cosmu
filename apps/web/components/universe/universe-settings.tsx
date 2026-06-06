"use client";

// module: operator universe gate. Tick which asset classes and venues the machine may research and
// trade. Tri-state logic: a venue keeps its own tick even when its asset class is switched off — it
// just greys out (effective = venue ticked AND class active). Writes go through the audited engine.

import { useEffect, useState, useTransition } from "react";
import { Check, Info, TriangleAlert } from "lucide-react";
import type { AssetClassState, UniverseResponse, VenueState } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { ENGINE_CONFIGURED, engineFetch, engineFetchTimeout } from "@/lib/engine";
import { cn } from "@/lib/utils";

const OFFLINE: UniverseResponse = {
  venues: [
    { id: "binance", name: "Binance", kind: "crypto", enabled: true, effective: true, has_data: true },
    { id: "ibkr", name: "IBKR", kind: "equity", enabled: false, effective: false, has_data: false },
    { id: "polymarket", name: "Polymarket", kind: "prediction", enabled: false, effective: false, has_data: false }
  ],
  asset_classes: [
    { kind: "crypto", label: "Crypto", active: true, enabled: true, has_data: true },
    { kind: "equity", label: "Stocks", active: true, enabled: false, has_data: false },
    { kind: "prediction", label: "Prediction markets", active: true, enabled: false, has_data: false }
  ]
};

function Tick({ on, dimmed }: { on: boolean; dimmed?: boolean }) {
  return (
    <span
      className={cn(
        "flex size-[18px] shrink-0 items-center justify-center rounded-[5px] border transition-colors",
        on ? "border-iris/60 bg-iris/80 text-background" : "border-border-strong bg-surface-2/60 text-transparent",
        dimmed && "opacity-40"
      )}
    >
      <Check className="size-3" strokeWidth={3} />
    </span>
  );
}

export function UniverseSettings() {
  const [data, setData] = useState<UniverseResponse>(OFFLINE);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      setOffline(true);
      return;
    }
    engineFetch("/universe")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("offline"))))
      .then((d: UniverseResponse) => setData(d))
      .catch(() => setOffline(true));
  }, []);

  function post(path: string, body: object, optimistic: (prev: UniverseResponse) => UniverseResponse) {
    setError(null);
    if (!ENGINE_CONFIGURED) {
      setData((prev) => recompute(optimistic(prev)));
      return;
    }
    startTransition(async () => {
      try {
        const res = await engineFetchTimeout(path, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(body)
        });
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          throw new Error(detail.detail ?? "Could not update");
        }
        setData((await res.json()) as UniverseResponse);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not update");
      }
    });
  }

  function setVenue(venueId: string, enabled: boolean) {
    post("/universe/venue", { venue_id: venueId, enabled }, (prev) => ({
      ...prev,
      venues: prev.venues.map((v) => (v.id === venueId ? { ...v, enabled } : v))
    }));
  }

  function setClass(kind: string, active: boolean) {
    post("/universe/class", { kind, active }, (prev) => ({
      ...prev,
      asset_classes: prev.asset_classes.map((c) => (c.kind === kind ? { ...c, active } : c))
    }));
  }

  const byKind = (kind: string) => data.venues.filter((v) => v.kind === kind);

  return (
    <div className="space-y-5">
      <p className="text-[12.5px] leading-relaxed text-muted">
        Choose what the machine may research and trade. Switching an asset class off greys out its venues but
        keeps each one&apos;s choice — turn the class back on and they return exactly as you left them.
        <span
          title="Effective = the venue is ticked AND its asset class is on. Venues without a live data feed are marked “no data yet” and produce no trades until wired."
          className="ml-1 inline-flex translate-y-[2px] cursor-help text-quiet"
        >
          <Info className="size-3.5" />
        </span>
      </p>

      {(offline || error) && (
        <div className="flex items-center gap-2 rounded-md border border-warn/30 bg-warn/5 px-3 py-2 text-[12px] text-warn">
          <TriangleAlert className="size-3.5 shrink-0" />
          {offline ? "Engine offline — showing defaults; changes are local only." : error}
        </div>
      )}

      <div className="space-y-3">
        {data.asset_classes.map((klass: AssetClassState) => (
          <div key={klass.kind} className="rounded-lg border border-border/60 bg-surface-2/30">
            <button
              type="button"
              disabled={pending}
              onClick={() => setClass(klass.kind, !klass.active)}
              className="flex w-full items-center justify-between gap-3 px-3.5 py-3 text-left disabled:opacity-60"
            >
              <span className="flex items-center gap-2.5">
                <Tick on={klass.active} />
                <span className="text-[13.5px] font-medium text-foreground">{klass.label}</span>
              </span>
              <span className="flex items-center gap-2">
                {!klass.has_data && <Badge variant="muted">no data yet</Badge>}
                {!klass.active && <span className="text-[11px] text-quiet">off</span>}
              </span>
            </button>
            <div className="space-y-px border-t border-border/50 px-3.5 py-2">
              {byKind(klass.kind).map((venue: VenueState) => (
                <button
                  key={venue.id}
                  type="button"
                  disabled={pending}
                  onClick={() => setVenue(venue.id, !venue.enabled)}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-md px-1.5 py-2 text-left hover:bg-surface-2/50 disabled:opacity-60",
                    !klass.active && "opacity-50"
                  )}
                >
                  <span className="flex items-center gap-2.5">
                    <Tick on={venue.enabled} dimmed={!klass.active || !venue.has_data} />
                    <span className="text-[13px] text-foreground">{venue.name}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {!venue.has_data && <span className="text-[11px] text-quiet">no data yet</span>}
                    <Badge variant={venue.effective ? "up" : "muted"}>{venue.effective ? "on" : "off"}</Badge>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Offline-only recompute of derived fields (effective, class.enabled) so the demo behaves like the engine.
function recompute(u: UniverseResponse): UniverseResponse {
  const activeByKind = new Map(u.asset_classes.map((c) => [c.kind, c.active]));
  const venues = u.venues.map((v) => ({ ...v, effective: v.enabled && (activeByKind.get(v.kind) ?? true) }));
  const ticked = new Set(venues.filter((v) => v.enabled).map((v) => v.kind));
  const asset_classes = u.asset_classes.map((c) => ({ ...c, enabled: c.active && ticked.has(c.kind) }));
  return { venues, asset_classes };
}
