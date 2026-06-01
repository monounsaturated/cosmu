"use client";

// module: operator universe gate. Purpose: tick which asset classes and venues the machine is
// allowed to research and trade. Invariants: writes go through the audited engine endpoint
// (/universe/venue); a class is "on" iff at least one of its venues is on; no secrets in the browser.

import { useEffect, useState, useTransition } from "react";
import { Check, Info, TriangleAlert } from "lucide-react";
import type { UniverseResponse, VenueState } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

const OFFLINE: UniverseResponse = {
  venues: [
    { id: "binance", name: "Binance", kind: "crypto", enabled: true, has_data: true },
    { id: "ibkr", name: "IBKR", kind: "equity", enabled: false, has_data: false },
    { id: "polymarket", name: "Polymarket", kind: "prediction", enabled: false, has_data: false }
  ],
  asset_classes: [
    { kind: "crypto", label: "Crypto", enabled: true, has_data: true },
    { kind: "equity", label: "Stocks", enabled: false, has_data: false },
    { kind: "prediction", label: "Prediction markets", enabled: false, has_data: false }
  ]
};

function Tick({ on, dimmed }: { on: boolean; dimmed?: boolean }) {
  return (
    <span
      className={cn(
        "flex size-[18px] items-center justify-center rounded-[5px] border transition-colors",
        on ? "border-iris/60 bg-iris/80 text-background" : "border-border-strong bg-surface-2/60 text-transparent",
        dimmed && "opacity-50"
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
    if (!ENGINE) {
      setOffline(true);
      return;
    }
    fetch(`${ENGINE}/universe`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("offline"))))
      .then((d: UniverseResponse) => setData(d))
      .catch(() => setOffline(true));
  }, []);

  function setVenue(venueId: string, enabled: boolean) {
    setError(null);
    if (!ENGINE) {
      // Offline demo: flip locally so the UI is still explorable.
      setData((prev) => recompute({ ...prev, venues: prev.venues.map((v) => (v.id === venueId ? { ...v, enabled } : v)) }));
      return;
    }
    startTransition(async () => {
      try {
        const res = await fetch(`${ENGINE}/universe/venue`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ venue_id: venueId, enabled })
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? "Could not update venue");
        }
        setData((await res.json()) as UniverseResponse);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not update venue");
      }
    });
  }

  function toggleClass(kind: string, enabled: boolean) {
    const targets = data.venues.filter((v) => v.kind === kind);
    // Flip each venue in the class; the engine guards against disabling the last venue.
    targets.forEach((v) => setVenue(v.id, enabled));
  }

  const byKind = (kind: string) => data.venues.filter((v) => v.kind === kind);

  return (
    <div className="space-y-5">
      <p className="text-[12.5px] leading-relaxed text-muted">
        Choose what the machine is allowed to research and trade. Turning a venue off removes it from every
        cohort and the live path — nothing there is screened or funded.
        <span title="A class is on when at least one of its venues is on. Venues without a live data feed are marked “no data yet” and produce no trades until wired." className="ml-1 inline-flex translate-y-[2px] cursor-help text-quiet">
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
        {data.asset_classes.map((klass) => (
          <div key={klass.kind} className="rounded-lg border border-border/60 bg-surface-2/30">
            <button
              type="button"
              disabled={pending}
              onClick={() => toggleClass(klass.kind, !klass.enabled)}
              className="flex w-full items-center justify-between gap-3 px-3.5 py-3 text-left disabled:opacity-60"
            >
              <span className="flex items-center gap-2.5">
                <Tick on={klass.enabled} />
                <span className="text-[13.5px] font-medium text-foreground">{klass.label}</span>
              </span>
              {!klass.has_data && <Badge variant="muted">no data yet</Badge>}
            </button>
            <div className="space-y-px border-t border-border/50 px-3.5 py-2">
              {byKind(klass.kind).map((venue: VenueState) => (
                <button
                  key={venue.id}
                  type="button"
                  disabled={pending}
                  onClick={() => setVenue(venue.id, !venue.enabled)}
                  className="flex w-full items-center justify-between gap-3 rounded-md px-1.5 py-2 text-left hover:bg-surface-2/50 disabled:opacity-60"
                >
                  <span className="flex items-center gap-2.5">
                    <Tick on={venue.enabled} dimmed={!venue.has_data} />
                    <span className="text-[13px] text-foreground">{venue.name}</span>
                  </span>
                  <span className="flex items-center gap-2">
                    {!venue.has_data && <span className="text-[11px] text-quiet">no data yet</span>}
                    <Badge variant={venue.enabled ? "up" : "muted"}>{venue.enabled ? "on" : "off"}</Badge>
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

function recompute(u: UniverseResponse): UniverseResponse {
  const enabledKinds = new Set(u.venues.filter((v) => v.enabled).map((v) => v.kind));
  return { ...u, asset_classes: u.asset_classes.map((c) => ({ ...c, enabled: enabledKinds.has(c.kind) })) };
}
