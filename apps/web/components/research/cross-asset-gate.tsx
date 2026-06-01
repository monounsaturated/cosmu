"use client";

// module: Cross-asset gate. The four-arm verdict — price-only vs single-alt vs full cross-asset
// vs buy-and-hold — surfaced as a one-click stop-or-go with the per-source and per-asset-class
// drop-one ablations. POSTs to /research/cross-asset-gate; falls back to a demo verdict offline.
//
// Types come from the generated contracts-ts (Pydantic -> OpenAPI -> TS); never hand-typed here.
//   POST /research/cross-asset-gate  (body: {})  -> CrossAssetVerdict (snake_case)

import { useState, useTransition } from "react";
import { Check, Layers, Play, X } from "lucide-react";
import type { CrossAssetVerdict, DropOneClass, DropOneSource } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type { CrossAssetVerdict, DropOneClass, DropOneSource };

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

function pct(x: number) {
  return `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
}

function arm(label: string, value: number, tone: "iris" | "up" | "muted") {
  const toneClass = { iris: "text-iris-soft", up: "text-up", muted: "text-muted" }[tone];
  return (
    <div key={label} className="rounded-md border border-border/60 bg-surface-2/40 p-3">
      <div className="text-[11px] uppercase tracking-wide text-quiet">{label}</div>
      <div className={cn("mt-1 text-xl font-semibold tabular", toneClass)}>{pct(value)}</div>
    </div>
  );
}

export function CrossAssetGate({ compact = false }: { compact?: boolean }) {
  const [verdict, setVerdict] = useState<CrossAssetVerdict | null>(null);
  const [offline, setOffline] = useState(!ENGINE);
  const [running, startRun] = useTransition();

  function run() {
    setOffline(false);
    startRun(async () => {
      if (!ENGINE) {
        setOffline(true);
        return;
      }
      try {
        const res = await fetch(`${ENGINE}/research/cross-asset-gate`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({})
        });
        if (!res.ok) throw new Error("engine unavailable");
        setVerdict((await res.json()) as CrossAssetVerdict);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    });
  }

  const passed = verdict?.decision === "PASS";

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Layers className="size-4 text-iris-soft" /> Cross-asset gate
          </CardTitle>
          <CardDescription>
            Does mixing alt-data sources and asset classes beat price-only — and buy &amp; hold — after costs?
          </CardDescription>
        </div>
        <Button onClick={run} disabled={running} size="sm" variant="primary">
          <Play className="size-3.5" /> {running ? "Running…" : "Run cross-asset gate"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {!verdict ? (
          <p className="text-[13px] text-muted">
            {offline
              ? "Engine not connected — run the cross-asset gate once the engine is up. No demo verdict is shown."
              : "No run yet. Press “Run cross-asset gate” for a four-arm verdict."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={passed ? "up" : "down"} className="text-[12px]">
                {passed ? "PASS — cross-asset adds real edge" : "STOP-narrow — stay price-only"}
              </Badge>
              <span className="text-[12px] text-quiet">
                cross-asset dSR <span className="text-muted">{verdict.xasset_dsr.toFixed(2)}</span> · {verdict.attempts} attempts
              </span>
              <Badge variant={verdict.data_source === "live" ? "info" : "warn"}>
                {verdict.data_source === "live" ? "live data" : "synthetic data"}
              </Badge>
              {offline ? <Badge variant="warn">offline</Badge> : null}
            </div>

            {/* Four arms */}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {arm("Price only", verdict.price_only_return, "muted")}
              {arm("Single alt", verdict.single_alt_return, "muted")}
              {arm("Cross-asset", verdict.xasset_return, "iris")}
              {arm("Buy & hold", verdict.buy_and_hold_return, "up")}
            </div>

            {!compact && (
              <div className="grid gap-3 lg:grid-cols-2">
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Drop-one source</div>
                  {verdict.drop_one_source.map((d) => (
                    <DropRow key={d.source} label={d.source} sharpe={d.sharpe_without} delta={d.delta} />
                  ))}
                </div>
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Drop-one asset class</div>
                  {verdict.drop_one_class.map((d) => (
                    <DropRow key={d.asset_class} label={d.asset_class} sharpe={d.sharpe_without} delta={d.delta} />
                  ))}
                </div>
              </div>
            )}

            {!compact && (
              <p className="text-[11.5px] leading-relaxed text-quiet">
                {passed
                  ? "The full cross-asset stack clears the deterministic wall and beats both price-only and buy & hold. Drop-one shows which sources and classes carry the edge."
                  : "Mixing sources did not beat a disciplined price-only baseline after costs. Stay narrow — that is a real, honest result."}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function DropRow({ label, sharpe, delta }: { label: string; sharpe: number; delta: number }) {
  const hurts = delta < 0;
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2">
      <span className="flex items-center gap-2 text-[12.5px]">
        <span className={cn("flex size-4 shrink-0 items-center justify-center rounded-full", hurts ? "bg-up/20 text-up" : "bg-down/20 text-down")}>
          {hurts ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />}
        </span>
        <span className="capitalize text-foreground">{label.replace(/_/g, " ")}</span>
      </span>
      <span className="shrink-0 text-[12px] text-muted">
        <span className="tabular">{sharpe.toFixed(2)}</span>{" "}
        <span className={cn("tabular", hurts ? "text-down" : "text-up")}>
          ({delta >= 0 ? "+" : ""}
          {delta.toFixed(2)})
        </span>
      </span>
    </div>
  );
}
