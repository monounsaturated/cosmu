// Composition — the population-wide "how strategies are built and how the pipeline flows" surface, one layer
// beneath the Strategies screener (reached from its toolbar; the Strategies nav item stays active). It answers
// two questions the per-row sheet can't: (1) the PIPELINE FUNNEL — how many ideas the machine authored and how
// they attrited through Backtest → Paper → Live (with the Killed graveyard and kill-rate), broken down by lane
// (exploit/explore/seed) and origin; (2) the INGREDIENT leaderboard — which building blocks recur and how often
// each survives the Gate (mix-and-match observed across the whole population).
//
// HONESTY: every count is a real GROUP BY off strategy_versions / the block registry. Not-connected → the
// honest engine-not-connected state; the ingredient registry renders its own "migration not applied" state.
// Nothing is fabricated, and recurrence/funded-rate is observational — the deterministic Gate alone funds.

import { Suspense } from "react";
import Link from "next/link";
import type { PopulationResponse } from "@cosmu/contracts-ts";
import { engineConfigured, getBlocks, getPopulation } from "../../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected } from "@/components/ui/honest-state";
import { IngredientTable } from "@/components/research/ingredient-table";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

const BackToStrategies = (
  <Link href="/strategies" className="seeall-btn" style={{ marginLeft: 10 }}>
    ← Strategies
  </Link>
);

export default function CompositionPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Composition" left={BackToStrategies} />
            <div className="skel" style={{ height: 360 }} />
          </>
        }
      >
        <CompositionData />
      </Suspense>
    </Page>
  );
}

async function CompositionData() {
  const [{ population, connected }, { blocks }] = await Promise.all([getPopulation(), getBlocks()]);

  if (!connected) {
    return (
      <>
        <Toolbar title="Composition" left={BackToStrategies} />
        <NotConnected
          configured={engineConfigured}
          what="The pipeline funnel (how many strategies the machine authored and how they flowed through Backtest → Paper → Live) and the building-block leaderboard appear here once the engine is connected — no demo counts."
        />
      </>
    );
  }

  return (
    <>
      <Toolbar title="Composition" left={BackToStrategies} />
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
        <div className="card">
          <div className="card-hdr">
            <span className="card-lbl">Pipeline funnel</span>
            <span className="quiet" style={{ fontSize: 10.5 }}>
              {population.total} authored · {(population.kill_rate * 100).toFixed(0)}% killed
            </span>
          </div>
          <div className="card-body">
            <PipelineFunnel population={population} />
            <LaneOriginBreakdown population={population} />
          </div>
        </div>

        <div className="card">
          <div className="card-hdr">
            <span className="card-lbl">Mix-and-match — building-block leaderboard</span>
          </div>
          <div className="card-body" style={{ paddingTop: 6 }}>
            <p className="quiet" style={{ fontSize: 11, lineHeight: 1.6, marginBottom: 10 }}>
              Every strategy is decomposed into reusable blocks (signal · filter · exit · sizing). This ranks them by
              how often each ingredient survives the Gate across the whole population — what keeps showing up in
              funded strategies. Observational only; the deterministic FDR Gate is the sole funder.
            </p>
            <IngredientTable available={blocks.available} rows={blocks.rows} />
          </div>
        </div>
      </div>
    </>
  );
}

// ── The funnel: Authored → Backtest/Queued → Paper → Live, bars sized by count, with the Killed graveyard
// shown as the attrition branch. `paper` from the contract already includes live; we split them honestly. ──
function PipelineFunnel({ population }: { population: PopulationResponse }) {
  const total = Math.max(0, population.total);
  const live = Math.max(0, population.live);
  const paperIncl = Math.max(0, population.paper); // paper + forward_test + live
  const paperOnly = Math.max(0, paperIncl - live);
  const killed = Math.max(0, population.killed);
  const prePaper = Math.max(0, total - paperIncl - killed); // queued + backtest, still alive

  const stages: { key: string; label: string; count: number; tip: string; tone?: string }[] = [
    { key: "authored", label: "Authored", count: total, tip: "Every strategy-version the machine has ever authored (alive + killed). The top of the funnel." },
    { key: "prepaper", label: "Backtest · Queued", count: prePaper, tip: "Alive but not yet on a paper track — queued or in backtest/screening." },
    { key: "paper", label: "Paper", count: paperIncl, tip: "On a standalone paper track (includes those launched live). Proving the edge on real prices, net of costs.", tone: "iris" },
    { key: "live", label: "Live", count: live, tip: "Launched live with real, capped capital. The 5 interlocks are the hard gate.", tone: "up" },
  ];

  const denom = total > 0 ? total : 1;

  return (
    <div className="funnel">
      {stages.map((s) => {
        const widthPct = Math.max(s.count > 0 ? 14 : 7, (s.count / denom) * 100);
        return (
          <div key={s.key} className="funnel-stage">
            <div
              className={cn("funnel-bar", s.tone === "iris" && "fn-iris", s.tone === "up" && "fn-up")}
              style={{ width: `${widthPct}%` }}
              data-tip={s.tip}
            >
              <span className="fn-count tab">{s.count}</span>
              <span className="fn-label">{s.label}</span>
            </div>
          </div>
        );
      })}
      <div className="funnel-stage">
        <div className="funnel-bar fn-dead" style={{ width: `${Math.max(killed > 0 ? 14 : 7, (killed / denom) * 100)}%` }} data-tip="The graveyard — strategies the Gate killed. Kept visible (no survivorship bias): a dead strategy stays in the record forever.">
          <span className="fn-count tab">{killed}</span>
          <span className="fn-label">Killed</span>
        </div>
      </div>
    </div>
  );
}

// Coerce the contract's Record<string, unknown> count maps into sorted [label, count] pairs.
function pairs(rec: Record<string, unknown>): [string, number][] {
  return Object.entries(rec)
    .map(([k, v]) => [k, typeof v === "number" ? v : Number(v) || 0] as [string, number])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
}

function LaneOriginBreakdown({ population }: { population: PopulationResponse }) {
  const lanes = pairs(population.by_lane);
  const origins = pairs(population.by_origin);
  if (lanes.length === 0 && origins.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 24, marginTop: 16 }}>
      {lanes.length > 0 ? (
        <div>
          <div className="psec-title" style={{ marginBottom: 6 }} data-tip="Exploit = mutate/recombine current survivors (clean attribution). Explore = high-variance wildcards reaching outside the population. Seed = starting templates.">
            By lane
          </div>
          <div className="chip-row">
            {lanes.map(([k, n]) => (
              <span key={k} className="badge badge-iris" style={{ textTransform: "capitalize" }}>
                {k} · {n}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {origins.length > 0 ? (
        <div>
          <div className="psec-title" style={{ marginBottom: 6 }} data-tip="How each strategy was born: seed template, mutation, wildcard, Pine import, or LLM-authored.">
            By origin
          </div>
          <div className="chip-row">
            {origins.map(([k, n]) => (
              <span key={k} className="badge badge-run" style={{ textTransform: "capitalize" }}>
                {k} · {n}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
