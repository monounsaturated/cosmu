"use client";

// module: ExplorerClient — the interactive Strategy Explorer surface. Operator picks
// a strategy + venue + asset; optionally overlays a second asset on the same chart.
// Fetches stored backtest data from the /explorer endpoint (never triggers new runs).
// Design: explicit + lean, mobile-first, reuses the design system throughout.

import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  CheckCircle,
  ChartLine,
  GitCompareArrows,
  Info,
  Loader,
  X,
} from "lucide-react";
import type {
  ExplorerDetailResponse,
  ExplorerListResponse,
  ExplorerVersion,
} from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { ExplorerChart } from "@/components/charts/explorer-chart";
import { engineFetch } from "@/lib/engine";
import { cn, formatPct } from "@/lib/utils";

// ── Selector ─────────────────────────────────────────────────────────────────

function Select({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 min-w-[160px] rounded-md border border-border bg-surface-2/40 px-3 text-[13px] text-foreground outline-none transition-colors focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
      >
        {placeholder ? (
          <option value="" disabled>
            {placeholder}
          </option>
        ) : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── Stat pill (glanceable stats panel) ───────────────────────────────────────

function StatPill({
  label,
  value,
  tone,
  tooltip,
}: {
  label: string;
  value: string | null;
  tone?: "up" | "down" | "warn" | "iris" | "muted";
  tooltip?: string;
}) {
  const toneClass: Record<string, string> = {
    up: "text-up",
    down: "text-down",
    warn: "text-warn",
    iris: "text-iris-soft",
    muted: "text-muted",
  };
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">
        {label}
        {tooltip ? <Tooltip content={tooltip} /> : null}
      </div>
      <div
        className={cn(
          "tabular text-[13.5px] font-semibold",
          value === null ? "text-quiet" : (toneClass[tone ?? "muted"] ?? "text-foreground")
        )}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

// ── Gate badge ─────────────────────────────────────────────────────────────

function GateBadge({
  decision,
  reason,
}: {
  decision: string | null;
  reason: string | null;
}) {
  if (!decision) return <Badge variant="muted">not run</Badge>;
  const pass = decision === "PASS";
  return (
    <div className="flex items-start gap-1.5">
      <Badge variant={pass ? "up" : "down"}>
        {pass ? (
          <CheckCircle className="size-3" />
        ) : (
          <AlertCircle className="size-3" />
        )}{" "}
        {decision}
      </Badge>
      {reason ? (
        <span className="text-[11px] leading-relaxed text-muted">{reason}</span>
      ) : null}
    </div>
  );
}

// ── Main client component ─────────────────────────────────────────────────────

export function ExplorerClient({ initialList }: { initialList: ExplorerListResponse }) {
  const { versions } = initialList;

  // Derived selector options
  const strategyOptions = versions.map((v) => ({
    value: v.version_id,
    label: `${v.name} (${v.signal_family_label} · ${v.status})`,
  }));

  // Selector state
  const [selectedVersionId, setSelectedVersionId] = useState(
    versions[0]?.version_id ?? ""
  );
  const [overlayVersionId, setOverlayVersionId] = useState("");
  const [overlayMode, setOverlayMode] = useState(false);

  // Data state
  const [detail, setDetail] = useState<ExplorerDetailResponse | null>(null);
  const [overlayDetail, setOverlayDetail] = useState<ExplorerDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [overlayLoading, setOverlayLoading] = useState(false);

  // Fetch primary detail (via Next proxy — secret never reaches browser)
  const fetchDetail = useCallback(async (versionId: string) => {
    if (!versionId) return;
    setLoading(true);
    try {
      const res = await engineFetch(`/explorer/${versionId}`);
      if (res.ok) setDetail(await res.json());
    } catch {
      /* network error — keep previous */
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch overlay detail
  const fetchOverlay = useCallback(async (versionId: string) => {
    if (!versionId) {
      setOverlayDetail(null);
      return;
    }
    setOverlayLoading(true);
    try {
      const res = await engineFetch(`/explorer/${versionId}`);
      if (res.ok) setOverlayDetail(await res.json());
    } catch {
      /* network error */
    } finally {
      setOverlayLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedVersionId) fetchDetail(selectedVersionId);
  }, [selectedVersionId, fetchDetail]);

  useEffect(() => {
    if (overlayMode && overlayVersionId) {
      fetchOverlay(overlayVersionId);
    } else {
      setOverlayDetail(null);
    }
  }, [overlayMode, overlayVersionId, fetchOverlay]);

  const selectedVersion: ExplorerVersion | undefined = versions.find(
    (v) => v.version_id === selectedVersionId
  );
  const overlayVersion: ExplorerVersion | undefined = versions.find(
    (v) => v.version_id === overlayVersionId
  );

  const stats = detail?.stats ?? null;

  return (
    <div className="space-y-5">
      {/* ── Selectors bar ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-4 pt-5">
          {versions.length === 0 ? (
            <div className="flex items-center gap-2 text-[13px] text-muted">
              <Info className="size-4 text-quiet" />
              No strategy versions yet — run a cohort in the Lab to get started.
            </div>
          ) : (
            <>
              <Select
                label="Strategy"
                value={selectedVersionId}
                options={strategyOptions}
                onChange={setSelectedVersionId}
                placeholder="Pick a strategy…"
              />

              {selectedVersion ? (
                <div className="flex flex-wrap items-center gap-2 pb-0.5">
                  <Badge variant="iris">{selectedVersion.signal_family_label}</Badge>
                  <Badge variant="muted">{selectedVersion.timeframe}</Badge>
                  <Badge variant="muted">{selectedVersion.venue || "—"}</Badge>
                  <Badge variant="muted">{selectedVersion.asset_class || "—"}</Badge>
                  {Number.isFinite(selectedVersion.deflated_sharpe) ? (
                    <Badge variant={selectedVersion.deflated_sharpe > 0 ? "up" : "down"}>
                      dSR {selectedVersion.deflated_sharpe.toFixed(2)}
                    </Badge>
                  ) : null}
                </div>
              ) : null}

              {/* Overlay toggle */}
              <div className="ml-auto flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setOverlayMode((v) => !v)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors",
                    overlayMode
                      ? "border-gold/50 bg-gold/10 text-foreground"
                      : "border-border/70 bg-surface-2/30 text-muted hover:border-border hover:text-foreground"
                  )}
                >
                  <GitCompareArrows className="size-3.5" />
                  Overlay
                </button>
              </div>

              {/* Overlay strategy selector */}
              {overlayMode ? (
                <div className="flex items-end gap-2">
                  <Select
                    label="Overlay strategy"
                    value={overlayVersionId}
                    options={strategyOptions.filter((o) => o.value !== selectedVersionId)}
                    onChange={setOverlayVersionId}
                    placeholder="Pick strategy to compare…"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      setOverlayMode(false);
                      setOverlayVersionId("");
                    }}
                    className="mb-0.5 text-quiet transition-colors hover:text-foreground"
                    aria-label="Remove overlay"
                  >
                    <X className="size-4" />
                  </button>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>

      {/* ── Chart + stats layout ──────────────────────────────────────── */}
      {selectedVersionId && (
        <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
          {/* Chart card */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <ChartLine className="size-4 text-iris-soft" />
                Equity curve
                <Tooltip content="Cumulative realized P&L from stored simulation fills. Gross (dashed iris) = before fees, Net (solid line) = after fees. Entry ▲ and exit ▼ markers from the fill log. Nothing fabricated — honest empty state when no fills exist." />
              </CardTitle>
              {loading ? (
                <Loader className="size-4 animate-spin text-quiet" />
              ) : (
                detail && (
                  <Badge variant={detail.available ? "muted" : "warn"}>
                    {detail.available ? "stored data" : "no data yet"}
                  </Badge>
                )
              )}
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="flex items-center justify-center py-16 text-quiet">
                  <Loader className="size-5 animate-spin" />
                </div>
              ) : detail ? (
                <ExplorerChart
                  equityCurve={detail.equity_curve}
                  trades={detail.trades}
                  overlayEquity={
                    overlayDetail?.equity_curve?.length ? overlayDetail.equity_curve : undefined
                  }
                  overlayLabel={overlayVersion?.name}
                  height={320}
                />
              ) : null}
            </CardContent>
          </Card>

          {/* Stats panel */}
          <Card>
            <CardHeader>
              <CardTitle>Stats</CardTitle>
              {overlayLoading ? <Loader className="size-4 animate-spin text-quiet" /> : null}
            </CardHeader>
            <CardContent className="space-y-5">
              {stats ? (
                <>
                  {/* Thesis */}
                  {stats.thesis ? (
                    <div className="space-y-0.5">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">
                        Thesis
                      </div>
                      <p className="text-[12.5px] leading-relaxed text-foreground">
                        {stats.thesis}
                      </p>
                    </div>
                  ) : null}

                  {/* Identity grid */}
                  <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                    <StatPill
                      label="Asset"
                      value={stats.asset}
                      tooltip="Asset class this version trades"
                    />
                    <StatPill
                      label="Venue"
                      value={stats.venue}
                      tooltip="Venue + fee schedule this backtest assumed"
                    />
                    <StatPill
                      label="Fee assumed"
                      value={
                        stats.fee_assumed_bps !== null
                          ? `${stats.fee_assumed_bps.toFixed(1)} bps`
                          : null
                      }
                      tooltip="Taker fee rate baked into the net-return calculation"
                    />
                    <StatPill
                      label="Data span"
                      value={
                        stats.data_span_days !== null
                          ? `${stats.data_span_days}d`
                          : null
                      }
                      tooltip="Calendar days between first and last recorded fill"
                    />
                  </div>

                  <div className="h-px bg-border/40" />

                  {/* Returns */}
                  <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                    <StatPill
                      label="Gross return"
                      value={
                        stats.gross_return_pct !== null
                          ? formatPct(stats.gross_return_pct)
                          : null
                      }
                      tone={
                        stats.gross_return_pct !== null
                          ? stats.gross_return_pct >= 0
                            ? "up"
                            : "down"
                          : "muted"
                      }
                      tooltip="OOS return before any fee deduction (stored backtest result)"
                    />
                    <StatPill
                      label="Net return"
                      value={
                        stats.net_return_pct !== null
                          ? formatPct(stats.net_return_pct)
                          : null
                      }
                      tone={
                        stats.net_return_pct !== null
                          ? stats.net_return_pct >= 0
                            ? "up"
                            : "down"
                          : "muted"
                      }
                      tooltip="OOS return after subtracting assumed round-trip cost (~0.18%)"
                    />
                    <StatPill
                      label="Cost ratio"
                      value={
                        stats.cost_ratio !== null
                          ? (stats.cost_ratio * 100).toFixed(2) + "%"
                          : null
                      }
                      tone="warn"
                      tooltip="Estimated total fees / gross cash out — the fee drag"
                    />
                    <StatPill
                      label="# Trades"
                      value={stats.num_trades !== null ? String(stats.num_trades) : null}
                      tooltip="Number of fills recorded in the simulation track"
                    />
                  </div>

                  <div className="h-px bg-border/40" />

                  {/* Gate metrics */}
                  <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                    <StatPill
                      label="Deflated Sharpe"
                      value={
                        stats.deflated_sharpe !== null
                          ? stats.deflated_sharpe.toFixed(3)
                          : null
                      }
                      tone={
                        stats.deflated_sharpe !== null
                          ? stats.deflated_sharpe > 0.95
                            ? "up"
                            : "down"
                          : "muted"
                      }
                      tooltip="Deflated Sharpe ratio (Bailey/Lopez de Prado). Gate threshold: 0.95. Values above = PASS, below = FAIL."
                    />
                    <StatPill
                      label="Max drawdown"
                      value={
                        stats.max_dd !== null
                          ? `${stats.max_dd.toFixed(1)}%`
                          : null
                      }
                      tone={
                        stats.max_dd !== null
                          ? stats.max_dd < 25
                            ? "up"
                            : "down"
                          : "muted"
                      }
                      tooltip="Peak-to-trough drawdown. Gate threshold: 25%. Below = PASS, above = FAIL."
                    />
                    <StatPill
                      label="OOS holdout"
                      value={
                        stats.oos_holdout_pct !== null
                          ? formatPct(stats.oos_holdout_pct)
                          : null
                      }
                      tone={
                        stats.oos_holdout_pct !== null
                          ? stats.oos_holdout_pct >= 0
                            ? "up"
                            : "down"
                          : "muted"
                      }
                      tooltip="One-shot untouched holdout return — seen exactly once to gate promotion"
                    />
                  </div>

                  {/* Gate verdict */}
                  <div className="space-y-1.5 rounded-md border border-border/50 bg-surface-2/30 p-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">
                      Gate verdict
                    </div>
                    <GateBadge
                      decision={stats.gate_decision}
                      reason={stats.gate_reason}
                    />
                  </div>

                  {/* Overlay comparison */}
                  {overlayDetail?.available && overlayVersion ? (
                    <div className="space-y-1.5 rounded-md border border-gold/25 bg-gold/5 p-3">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gold">
                        Overlay — {overlayVersion.name}
                      </div>
                      <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                        <StatPill
                          label="Net return"
                          value={
                            overlayDetail.stats.net_return_pct !== null
                              ? formatPct(overlayDetail.stats.net_return_pct)
                              : null
                          }
                          tone={
                            overlayDetail.stats.net_return_pct !== null
                              ? overlayDetail.stats.net_return_pct >= 0
                                ? "up"
                                : "down"
                              : "muted"
                          }
                        />
                        <StatPill
                          label="dSR"
                          value={
                            overlayDetail.stats.deflated_sharpe !== null
                              ? overlayDetail.stats.deflated_sharpe.toFixed(3)
                              : null
                          }
                          tone={
                            overlayDetail.stats.deflated_sharpe !== null
                              ? overlayDetail.stats.deflated_sharpe > 0.95
                                ? "up"
                                : "down"
                              : "muted"
                          }
                        />
                        <StatPill
                          label="Gate"
                          value={overlayDetail.stats.gate_decision}
                          tone={
                            overlayDetail.stats.gate_decision === "PASS" ? "up" : "down"
                          }
                        />
                      </div>
                    </div>
                  ) : null}
                </>
              ) : loading ? (
                <div className="flex items-center justify-center py-8 text-quiet">
                  <Loader className="size-5 animate-spin" />
                </div>
              ) : (
                <div className="py-4 text-center text-[12.5px] text-quiet">
                  Select a strategy to see stats.
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Empty state when no versions exist */}
      {versions.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center">
            <div className="text-[13px] text-muted">No strategy versions yet.</div>
            <div className="mx-auto mt-1.5 max-w-sm text-[11.5px] leading-relaxed text-quiet">
              Run a cohort in the Lab (or drop an idea in the inbox) to generate strategy
              versions. They will show up here once the Gate has evaluated them.
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
