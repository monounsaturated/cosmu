"use client";

// module: ExplorerClient — the interactive Strategy Explorer. Pick a strategy; optionally overlay a
// second one on the same chart. Reads STORED backtest data from /explorer (never triggers a new run).
//
// Design: calm + fast. One primary control (the strategy picker) with the chosen strategy's identity
// chips beneath it; overlay is a quiet secondary toggle. The equity curve is the hero; a sticky stats
// rail beside it groups identity → returns → gate, with the Gate verdict promoted to the top of the
// rail (it's the answer the operator came for). HONEST: every field shows "—" when there's no stored
// value; the chart renders its own honest empty state. Nothing is fabricated.

import { useCallback, useEffect, useState, type ReactNode } from "react";
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
  className,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <label className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 w-full min-w-[180px] rounded-md border border-border bg-surface-2/40 px-3 text-[13px] text-foreground outline-none transition-colors focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
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

// ── Stat (glanceable, label + value, honest "—") ──────────────────────────────

function Stat({
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
          "text-[13.5px] font-semibold tabular",
          value === null ? "text-quiet" : (toneClass[tone ?? "muted"] ?? "text-foreground")
        )}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

// Small group label inside the stats rail.
function RailGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.1em] text-quiet">{label}</div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3">{children}</div>
    </div>
  );
}

// ── Gate verdict (promoted — the answer the operator came for) ─────────────────

// (GateVerdict renders JSX only — no ReactNode prop needed.)
function GateVerdict({ decision, reason }: { decision: string | null; reason: string | null }) {
  if (!decision) {
    return (
      <div className="rounded-lg border border-border/60 bg-surface-2/30 p-3">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">Gate verdict</div>
        <div className="mt-1.5 text-[13px] font-medium text-muted">Not run yet</div>
      </div>
    );
  }
  const pass = decision === "PASS";
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        pass ? "border-up/30 bg-up/[0.07]" : "border-down/30 bg-down/[0.07]"
      )}
    >
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">Gate verdict</div>
      <div className="mt-1.5 flex items-center gap-2">
        {pass ? <CheckCircle className="size-4 text-up" /> : <AlertCircle className="size-4 text-down" />}
        <span className={cn("text-[15px] font-semibold tabular", pass ? "text-up" : "text-down")}>{decision}</span>
      </div>
      {reason ? <p className="mt-1.5 text-[11.5px] leading-relaxed text-muted">{reason}</p> : null}
    </div>
  );
}

// ── Main client component ─────────────────────────────────────────────────────

export function ExplorerClient({ initialList }: { initialList: ExplorerListResponse }) {
  const { versions } = initialList;

  const strategyOptions = versions.map((v) => ({
    value: v.version_id,
    label: `${v.name} (${v.signal_family_label} · ${v.status})`,
  }));

  const [selectedVersionId, setSelectedVersionId] = useState(versions[0]?.version_id ?? "");
  const [overlayVersionId, setOverlayVersionId] = useState("");
  const [overlayMode, setOverlayMode] = useState(false);

  const [detail, setDetail] = useState<ExplorerDetailResponse | null>(null);
  const [overlayDetail, setOverlayDetail] = useState<ExplorerDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [overlayLoading, setOverlayLoading] = useState(false);

  // Fetch via the Next proxy — the engine secret never reaches the browser.
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

  const selectedVersion: ExplorerVersion | undefined = versions.find((v) => v.version_id === selectedVersionId);
  const overlayVersion: ExplorerVersion | undefined = versions.find((v) => v.version_id === overlayVersionId);

  const stats = detail?.stats ?? null;

  // Empty state — no versions at all.
  if (versions.length === 0) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <div className="mx-auto flex size-11 items-center justify-center rounded-full border border-border/70 bg-surface-2/50 text-quiet">
            <ChartLine className="size-5" />
          </div>
          <div className="mt-3 text-[14px] font-medium text-foreground">No strategy versions yet</div>
          <p className="mx-auto mt-1 max-w-sm text-[12px] leading-relaxed text-muted">
            Run a cohort in the Lab (or drop an idea in the inbox) to generate strategy versions. They show up here once
            the Gate has evaluated them.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {/* ── Selector bar ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="space-y-4 pt-5">
          {/* Primary control + overlay toggle */}
          <div className="flex flex-wrap items-end gap-4">
            <Select
              label="Strategy"
              value={selectedVersionId}
              options={strategyOptions}
              onChange={setSelectedVersionId}
              placeholder="Pick a strategy…"
              className="flex-1"
            />
            <button
              type="button"
              onClick={() => setOverlayMode((v) => !v)}
              className={cn(
                "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border px-3 text-[12px] font-medium transition-colors",
                overlayMode
                  ? "border-gold/50 bg-gold/10 text-foreground"
                  : "border-border/70 bg-surface-2/30 text-muted hover:border-border hover:text-foreground"
              )}
            >
              <GitCompareArrows className="size-3.5" />
              Compare
            </button>
          </div>

          {/* Selected strategy identity chips */}
          {selectedVersion ? (
            <div className="flex flex-wrap items-center gap-2">
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

          {/* Overlay strategy selector — only when comparing */}
          {overlayMode ? (
            <div className="flex items-end gap-2 border-t border-border/50 pt-4">
              <Select
                label="Compare with"
                value={overlayVersionId}
                options={strategyOptions.filter((o) => o.value !== selectedVersionId)}
                onChange={setOverlayVersionId}
                placeholder="Pick a strategy to overlay…"
                className="flex-1"
              />
              <button
                type="button"
                onClick={() => {
                  setOverlayMode(false);
                  setOverlayVersionId("");
                }}
                className="mb-1.5 text-quiet transition-colors hover:text-foreground"
                aria-label="Remove overlay"
              >
                <X className="size-4" />
              </button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {/* ── Chart + stats rail ────────────────────────────────────────── */}
      {selectedVersionId ? (
        <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
          {/* Equity curve (the hero) */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-1.5">
                <ChartLine className="size-4 text-iris-soft" />
                Equity curve
                <Tooltip content="Cumulative realized P&L from stored simulation fills. Gross (dashed iris) = before fees, Net (solid line) = after fees. Entry ▲ and exit ▼ markers from the fill log. Nothing fabricated — honest empty state when no fills exist." />
              </CardTitle>
              {loading ? (
                <Loader className="size-4 animate-spin text-quiet" />
              ) : detail ? (
                <Badge variant={detail.available ? "muted" : "warn"}>
                  {detail.available ? "stored data" : "no data yet"}
                </Badge>
              ) : null}
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
                  overlayEquity={overlayDetail?.equity_curve?.length ? overlayDetail.equity_curve : undefined}
                  overlayLabel={overlayVersion?.name}
                  height={320}
                />
              ) : null}
            </CardContent>
          </Card>

          {/* Stats rail — sticky on desktop so it stays beside the chart while reading. */}
          <div className="lg:sticky lg:top-6 lg:self-start">
            <Card>
              <CardHeader>
                <CardTitle>Stats</CardTitle>
                {overlayLoading ? <Loader className="size-4 animate-spin text-quiet" /> : null}
              </CardHeader>
              <CardContent className="space-y-5">
                {stats ? (
                  <>
                    {/* Gate verdict — promoted to the top. */}
                    <GateVerdict decision={stats.gate_decision} reason={stats.gate_reason} />

                    {/* Thesis */}
                    {stats.thesis ? (
                      <div className="space-y-0.5">
                        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">Thesis</div>
                        <p className="text-[12.5px] leading-relaxed text-foreground">{stats.thesis}</p>
                      </div>
                    ) : null}

                    {/* Returns */}
                    <RailGroup label="Returns">
                      <Stat
                        label="Gross return"
                        value={stats.gross_return_pct !== null ? formatPct(stats.gross_return_pct) : null}
                        tone={stats.gross_return_pct !== null ? (stats.gross_return_pct >= 0 ? "up" : "down") : "muted"}
                        tooltip="OOS return before any fee deduction (stored backtest result)"
                      />
                      <Stat
                        label="Net return"
                        value={stats.net_return_pct !== null ? formatPct(stats.net_return_pct) : null}
                        tone={stats.net_return_pct !== null ? (stats.net_return_pct >= 0 ? "up" : "down") : "muted"}
                        tooltip="OOS return after subtracting assumed round-trip cost (~0.18%)"
                      />
                      <Stat
                        label="Cost ratio"
                        value={stats.cost_ratio !== null ? (stats.cost_ratio * 100).toFixed(2) + "%" : null}
                        tone="warn"
                        tooltip="Estimated total fees / gross cash out — the fee drag"
                      />
                      <Stat
                        label="# Trades"
                        value={stats.num_trades !== null ? String(stats.num_trades) : null}
                        tooltip="Number of fills recorded in the simulation track"
                      />
                    </RailGroup>

                    <div className="h-px bg-border/40" />

                    {/* Gate metrics */}
                    <RailGroup label="Gate metrics">
                      <Stat
                        label="Deflated Sharpe"
                        value={stats.deflated_sharpe !== null ? stats.deflated_sharpe.toFixed(3) : null}
                        tone={stats.deflated_sharpe !== null ? (stats.deflated_sharpe > 0.95 ? "up" : "down") : "muted"}
                        tooltip="Deflated Sharpe ratio (Bailey/Lopez de Prado). Gate threshold: 0.95. Above = PASS, below = FAIL."
                      />
                      <Stat
                        label="Max drawdown"
                        value={stats.max_dd !== null ? `${stats.max_dd.toFixed(1)}%` : null}
                        tone={stats.max_dd !== null ? (stats.max_dd < 25 ? "up" : "down") : "muted"}
                        tooltip="Peak-to-trough drawdown. Gate threshold: 25%. Below = PASS, above = FAIL."
                      />
                      <Stat
                        label="OOS holdout"
                        value={stats.oos_holdout_pct !== null ? formatPct(stats.oos_holdout_pct) : null}
                        tone={stats.oos_holdout_pct !== null ? (stats.oos_holdout_pct >= 0 ? "up" : "down") : "muted"}
                        tooltip="One-shot untouched holdout return — seen exactly once to gate promotion"
                      />
                    </RailGroup>

                    <div className="h-px bg-border/40" />

                    {/* Setup — identity / assumptions (secondary; kept last). */}
                    <RailGroup label="Setup">
                      <Stat label="Asset" value={stats.asset} tooltip="Asset class this version trades" />
                      <Stat label="Venue" value={stats.venue} tooltip="Venue + fee schedule this backtest assumed" />
                      <Stat
                        label="Fee assumed"
                        value={stats.fee_assumed_bps !== null ? `${stats.fee_assumed_bps.toFixed(1)} bps` : null}
                        tooltip="Taker fee rate baked into the net-return calculation"
                      />
                      <Stat
                        label="Data span"
                        value={stats.data_span_days !== null ? `${stats.data_span_days}d` : null}
                        tooltip="Calendar days between first and last recorded fill"
                      />
                    </RailGroup>

                    {/* Overlay comparison */}
                    {overlayDetail?.available && overlayVersion ? (
                      <div className="space-y-2.5 rounded-lg border border-gold/25 bg-gold/5 p-3">
                        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-gold">
                          Compared — {overlayVersion.name}
                        </div>
                        <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                          <Stat
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
                          <Stat
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
                          <Stat
                            label="Gate"
                            value={overlayDetail.stats.gate_decision}
                            tone={overlayDetail.stats.gate_decision === "PASS" ? "up" : "down"}
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
                  <div className="flex items-center gap-2 py-4 text-[12.5px] text-quiet">
                    <Info className="size-4" />
                    Select a strategy to see its stats.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </div>
  );
}
