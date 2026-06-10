// Correlations — the machine's TRACKED correlation memory, drawn LIVE from the engine's
// `correlation_findings` ledger via GET /correlations. The correlation engine "finds correlations
// (even non-causal) across all data × assets × horizons"; this surface DISPLAYS them well: an IC
// heatmap (feature × asset), a sortable/filterable findings table (with the BH-FDR survivors
// highlighted), and per-tracked-correlation decay sparklines that show whether a correlation is
// stable or fading over runs.
//
// HONESTY FIRST. A surviving IC is a *candidate hypothesis*, NEVER an edge — "scan proposes, Gate
// disposes". The deterministic Gate is the disposal layer; nothing here gates or moves money.
// Non-causal controls are flagged plainly so a strong IC on a known-false baseline reads as a
// data-snooping red flag, not a discovery. The page renders only real engine data: an honest
// "Engine not connected" state when unreachable, and a confident "no findings yet — run the sweep"
// empty state when connected-but-empty. Zero fabricated numbers.
//
// Server component: fetches the real ledger; the sortable/filterable findings table is a client
// island (components/correlations/findings-table). The heatmap + decay rail are pure server
// presentation over the fetched data.

import { ArrowLeft, Radar } from "lucide-react";
import Link from "next/link";
import { getCorrelations, engineConfigured } from "../data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section";
import { MetricCard } from "@/components/ui/viz";
import { NotConnected } from "@/components/ui/honest-state";
import { FDR_Q } from "@/components/correlations/correlation-bits";
import { HeatmapLegend, IcHeatmap } from "@/components/correlations/ic-heatmap";
import { FindingsTable } from "@/components/correlations/findings-table";
import { DecayRail } from "@/components/correlations/decay-rail";
import { CrossFeaturePairsPanel } from "@/components/correlations/cross-feature-pairs";

export default async function CorrelationsPage() {
  const { correlations, connected } = await getCorrelations();
  // Generated-contract shape: `latest` is the most-recent run's findings, `survivors` the BH-FDR
  // subset (queried directly so survivors outside the top-N window still count), `stability` the
  // per-feature IC-across-runs series the decay rail draws.
  const { latest: findings, stability } = correlations;

  const sources = Array.from(new Set(findings.map((f) => f.source))).sort();
  const survivors = correlations.survivors.length;
  const nonCausal = findings.filter((f) => f.non_causal).length;
  const assetCount = new Set(findings.map((f) => f.asset)).size;
  // featureCount excludes pair features (A~B) — pairs are shown in their own panel below.
  const pairFindings = findings.filter((f) => f.feature.includes("~"));
  const singleFindings = findings.filter((f) => !f.feature.includes("~"));
  const featureCount = new Set(singleFindings.map((f) => f.feature)).size;
  // latest_findings is newest-first, so the first row's ts dates the latest scan.
  const scanDate = findings[0]?.ts ? findings[0].ts.slice(0, 10) : null;

  return (
    <div className="mx-auto max-w-[1100px] space-y-5 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      {/* ── Header ──────────────────────────────────────────────────────────────────────── */}
      <div className="flex items-start gap-3">
        <Link
          href="/"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Overview
        </Link>
        <SectionHeader
          eyebrow="correlations · tracked memory"
          title="What the machine has correlated"
          aside={
            connected && findings.length > 0 ? (
              <div className="flex items-center gap-2">
                <Badge variant="up">{survivors.toLocaleString()} FDR survivors</Badge>
                {nonCausal > 0 ? <Badge variant="warn">{nonCausal.toLocaleString()} non-causal</Badge> : null}
              </div>
            ) : null
          }
          className="flex-1"
        />
      </div>

      {/* Plain framing, shown only when there is a scan to frame. Scan proposes, Gate disposes. */}
      {connected && findings.length > 0 ? (
        <p className="max-w-2xl text-[12.5px] leading-relaxed text-muted">
          The point-in-time information coefficient (IC) for every feature against every asset and
          forward horizon — the feature known at <span className="tabular">t</span> vs the strictly
          future return. A BH-FDR pass (q={FDR_Q}) flags which correlations survive multiple testing.
          A surviving IC is a <span className="text-foreground">candidate hypothesis, never an edge</span>:
          the scan proposes, the deterministic Gate disposes. Non-causal controls are flagged plainly.
        </p>
      ) : null}

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="This surface shows the machine's tracked correlation memory — every point-in-time IC across features, assets, and horizons. Connect the engine to see the live findings."
        />
      ) : findings.length === 0 ? (
        // Honest, confident empty state. Zero findings is not a blank page — it's an un-run sweep.
        <Card>
          <CardContent className="flex flex-col items-center gap-4 py-14 text-center">
            <div className="flex size-12 items-center justify-center rounded-full border border-iris/30 bg-iris/10 text-iris-soft">
              <Radar className="size-5" />
            </div>
            <div className="space-y-1.5">
              <div className="text-[15px] font-semibold text-foreground">No findings yet — run the sweep.</div>
              <p className="mx-auto max-w-md text-[12.5px] leading-relaxed text-muted">
                The correlation scan lands every (feature × asset × horizon) IC here the moment it
                runs — with its n, p, and BH-FDR survival, tracked across runs so you can watch a
                correlation stay or fade. Run the scan to fill this memory. Nothing here is fabricated.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* ── Summary strip ───────────────────────────────────────────────────────────────
              The four numbers that frame the scan. FDR survivors is the hero — the candidate count
              the Gate will dispose of next. */}
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <MetricCard
              label="Findings"
              value={findings.length.toLocaleString()}
              tone="iris"
              hint={scanDate ? `last scan ${scanDate}` : `${pairFindings.length > 0 ? `${pairFindings.length} cross-feature pairs · ` : ""}across all features`}
            />
            <MetricCard
              label="FDR survivors"
              value={survivors.toLocaleString()}
              tone={survivors > 0 ? "up" : "muted"}
              hint={`candidate hypotheses at q=${FDR_Q} · Gate disposes`}
            />
            <MetricCard
              label="Features × assets"
              value={`${featureCount} × ${assetCount}`}
              tone="info"
              hint="the correlation grid"
            />
            <MetricCard
              label="Non-causal flagged"
              value={nonCausal.toLocaleString()}
              tone={nonCausal > 0 ? "warn" : "muted"}
              hint="known-false controls — a strong IC here is a red flag"
            />
          </section>

          {/* ── IC heatmap ──────────────────────────────────────────────────────────────────
              Feature × asset, diverging color for the sign of the strongest-magnitude IC per pair.
              Uses single-feature findings only (pair findings "A~B" are shown in their own panel). */}
          <Card>
            <CardContent className="space-y-3 p-4 sm:p-5">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <div>
                  <div className="label-eyebrow text-iris-soft">IC heatmap</div>
                  <p className="mt-1 text-[12px] text-muted">
                    Strongest-magnitude IC per feature × asset. Green positive, red negative, calm near zero.
                  </p>
                </div>
                <HeatmapLegend />
              </div>
              <IcHeatmap findings={singleFindings} />
            </CardContent>
          </Card>

          {/* ── Cross-feature pairs ──────────────────────────────────────────────────────────
              Which data sources move together — "crossing" findings encoded as "A~B" feature names.
              Shows lag/lead, IC, FDR survival, and non-causal flags. Always rendered (honest empty
              state when the crossing engine has not yet run). */}
          <Card>
            <CardContent className="space-y-4 p-4 sm:p-5">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="label-eyebrow text-iris-soft">Cross-feature pairs</div>
                  <p className="mt-1 text-[12px] text-muted">
                    Data sources that move together — the IC between feature A and feature B, not a
                    price return. Lagged/lead shown plainly. Non-causal controls flagged. Propose-only.
                  </p>
                </div>
                {pairFindings.length > 0 ? (
                  <span className="shrink-0 rounded-full border border-iris/25 bg-iris/[0.08] px-2.5 py-0.5 text-[11px] font-medium text-iris-soft">
                    {pairFindings.length.toLocaleString()} pair{pairFindings.length === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
              <CrossFeaturePairsPanel findings={findings} />
            </CardContent>
          </Card>

          {/* ── Findings table ──────────────────────────────────────────────────────────────
              The dense, sortable/filterable core. FDR survivors highlighted; non-causal flagged.
              Shows all findings (single-feature + pairs) so nothing is hidden from the full ledger. */}
          <Card>
            <CardContent className="space-y-4 p-4 sm:p-5">
              <div>
                <div className="label-eyebrow text-iris-soft">Findings</div>
                <p className="mt-1 text-[12px] text-muted">
                  Every IC the scan recorded — feature, source, asset, horizon, IC, n, p, and FDR survival.
                </p>
              </div>
              <FindingsTable findings={findings} sources={sources} />
            </CardContent>
          </Card>

          {/* ── Decay rail ──────────────────────────────────────────────────────────────────
              Per-tracked-correlation IC sparklines: stable, strengthening, or decaying over runs. */}
          {stability.length > 0 ? (
            <Card>
              <CardContent className="space-y-4 p-4 sm:p-5">
                <div>
                  <div className="label-eyebrow text-iris-soft">Stability over runs</div>
                  <p className="mt-1 text-[12px] text-muted">
                    How each tracked correlation&apos;s IC moves run-over-run. A strong IC that fades is
                    the tell a single scan can&apos;t show — the honest counterweight to a one-shot number.
                  </p>
                </div>
                <DecayRail stability={stability} />
              </CardContent>
            </Card>
          ) : null}
        </>
      )}
    </div>
  );
}
