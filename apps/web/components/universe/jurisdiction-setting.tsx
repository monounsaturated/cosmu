"use client";

// module: operating-jurisdiction picker. One standardized setting that decides which venues can move REAL
// money (live-legality is a venue+country fact — e.g. Binance isn't US-legal). Reads the curated list from
// the engine, writes the pick through the audited POST /live/jurisdiction (event-backed, no schema change).

import { useEffect, useState, useTransition } from "react";
import { Check, Globe, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ENGINE_CONFIGURED, engineFetch, engineFetchTimeout } from "@/lib/engine";

interface JurisdictionOption {
  code: string;
  label: string;
  legal_venue_ids: string[];
}
interface JurisdictionsResponse {
  current: string;
  options: JurisdictionOption[];
}

export function JurisdictionSetting() {
  const [data, setData] = useState<JurisdictionsResponse | null>(null);
  const [connected, setConnected] = useState(true);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      setConnected(false);
      return;
    }
    engineFetch("/live/jurisdictions")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: JurisdictionsResponse) => {
        setData(d);
        setConnected(true);
      })
      .catch(() => setConnected(false));
  }, []);

  function pick(code: string) {
    if (!ENGINE_CONFIGURED || code === data?.current) return;
    setData((d) => (d ? { ...d, current: code } : d)); // optimistic
    startTransition(async () => {
      try {
        const res = await engineFetchTimeout("/live/jurisdiction", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ code })
        });
        if (res.ok) setData((await res.json()) as JurisdictionsResponse);
      } catch {
        setConnected(false);
      }
    });
  }

  if (!connected || !data) {
    return (
      <div className="flex items-center gap-2 text-[12.5px] text-quiet">
        <TriangleAlert className="size-3.5" /> Engine not connected — the jurisdiction picker appears once it’s reachable.
      </div>
    );
  }

  const current = data.options.find((o) => o.code === data.current);

  return (
    <div className="space-y-3">
      <label className="flex flex-wrap items-center gap-2 text-[13px] text-foreground">
        <Globe className="size-4 text-iris-soft" />
        <span>Operating jurisdiction</span>
        <select
          value={data.current}
          disabled={pending}
          onChange={(e) => pick(e.target.value)}
          className="rounded-md border border-border bg-surface-2/50 px-2.5 py-1.5 text-[13px] text-foreground outline-none focus-visible:border-iris/60"
        >
          {data.options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label} ({o.code})
            </option>
          ))}
        </select>
      </label>
      <p className="text-[11.5px] text-quiet">
        Live-legal venues here:{" "}
        {current && current.legal_venue_ids.length > 0 ? (
          <span className="inline-flex flex-wrap gap-1 align-middle">
            {current.legal_venue_ids.map((id) => (
              <Badge key={id} variant="muted">
                <Check className="size-3" /> {id}
              </Badge>
            ))}
          </span>
        ) : (
          <span className="text-warn">none — no venue is live-legal here</span>
        )}
      </p>
    </div>
  );
}
