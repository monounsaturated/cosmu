// Index detail — the definitive view of ONE index: what it measures (rationale + the kind-specific definition:
// topic / prompt / handles), its health (freshness · reliability · stability · transform version), the scored
// point-in-time series per symbol, and the strategies built on it. All from GET /indexes/{id}; honest empties
// throughout (a never-computed index shows "—"/"never", never a fabricated curve).

import { Suspense } from "react";
import Link from "next/link";
import type { IndexCard } from "@cosmu/contracts-ts";
import { engineConfigured, getIndex } from "../../data";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { EquityChart } from "@/components/charts/equity-chart";
import { cn, fmtTz } from "@/lib/utils";

export const dynamic = "force-dynamic";

const KIND_LABEL: Record<string, string> = {
  single_account: "Single account", social_bucket: "Social bucket", event_topic: "Event topic", prompt_rubric: "Prompt rubric",
};
const FRESHNESS_BADGE: Record<string, string> = { fresh: "badge-up", stale: "badge-gold", never: "badge-muted" };
const RELIABILITY_BADGE: Record<string, string> = { stable: "badge-up", moderate: "badge-iris", volatile: "badge-dn", untested: "badge-muted" };
const STATUS_BADGE: Record<string, string> = { active: "badge-up", paused: "badge-gold", draft: "badge-muted" };

export default async function IndexDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Page>
      <Toolbar title="Index" left={<Link href="/indexes" className="seeall-btn" style={{ marginLeft: 10 }}>← Indexes</Link>} />
      <Suspense fallback={<div className="skel" style={{ height: 420 }} />}>
        <IndexDetailBody id={id} />
      </Suspense>
    </Page>
  );
}

function defLine(card: IndexCard): { label: string; value: string } {
  const d = card.definition as Record<string, unknown>;
  if (card.kind === "event_topic") return { label: "Topic", value: String(d.topic ?? "—") };
  if (card.kind === "prompt_rubric") return { label: "Scoring prompt", value: String(d.prompt ?? "—") };
  const handles = Array.isArray(d.handles) ? (d.handles as string[]) : [];
  return { label: card.kind === "single_account" ? "Account" : "Accounts", value: handles.join(" · ") || "—" };
}

async function IndexDetailBody({ id }: { id: string }) {
  const { detail, connected } = await getIndex(id);

  if (!connected) {
    return <NotConnected configured={engineConfigured} what="This index's definition, health, and scored series come from the live engine. Nothing is fabricated." />;
  }
  if (!detail.available) {
    return <EmptyState title="Index registry not active yet" hint="Apply the 2026-06-15_indexes migration on the store to enable indexes." />;
  }
  const card = detail.index;
  if (!card) {
    return <EmptyState title={`No index "${id}"`} hint="It may have been removed, or the id is wrong." />;
  }

  const def = defLine(card);
  const h = card.health;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--gap)" }}>
      {/* Header */}
      <div className="card">
        <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: "var(--fg)", margin: 0 }}>{card.name}</h1>
            <span className="badge badge-run" style={{ textTransform: "none" }}>{KIND_LABEL[card.kind] ?? card.kind}</span>
            <span className={cn("badge", STATUS_BADGE[card.status] ?? "badge-muted")} style={{ textTransform: "capitalize" }}>{card.status}</span>
            <span className="quiet mono" style={{ fontSize: 10.5 }}>{card.metric}</span>
          </div>
          <p className="ai-body" style={{ margin: 0 }}>{card.rationale}</p>
          <div className="blocks" style={{ marginTop: 4 }}>
            <div className="block-row"><span className="block-key">{def.label}</span><span className="block-val">{def.value}</span></div>
            <div className="block-row"><span className="block-key">Scope</span><span className="block-val">{card.market_wide ? "market-wide (one series)" : card.entities.join(", ")}</span></div>
            <div className="block-row"><span className="block-key">Scoring</span><span className="block-val">deterministic · frozen {h.transform_version} · cadence {card.cadence_minutes}m</span></div>
          </div>
        </div>
      </div>

      {/* Health */}
      <div className="card">
        <div className="card-hdr"><span className="card-lbl">Health · monitored every pass</span></div>
        <div className="card-body">
          <div className="kpi-grid" style={{ marginBottom: 0 }}>
            <div className="kpi-box">
              <div className="kpi-label">Current value</div>
              <div className="kpi-val">{h.latest_value === null ? "—" : h.latest_value.toFixed(3)}</div>
              <div className="kpi-sub">{h.n_points} point{h.n_points === 1 ? "" : "s"}</div>
            </div>
            <div className="kpi-box">
              <div className="kpi-label">Freshness</div>
              <div className="kpi-val" style={{ fontSize: 18 }}><span className={cn("badge", FRESHNESS_BADGE[h.freshness] ?? "badge-muted")} style={{ textTransform: "capitalize" }}>{h.freshness}</span></div>
              <div className="kpi-sub">{h.latest_at ? fmtTz(h.latest_at, { dateStyle: "medium", timeStyle: "short" }) : "never computed"}</div>
            </div>
            <div className="kpi-box">
              <div className="kpi-label">Reliability</div>
              <div className="kpi-val" style={{ fontSize: 18 }}><span className={cn("badge", RELIABILITY_BADGE[h.reliability] ?? "badge-muted")} style={{ textTransform: "capitalize" }}>{h.reliability}</span></div>
              <div className="kpi-sub">{h.stability === null ? "needs ≥3 points" : `stdev ${h.stability.toFixed(3)}`}</div>
            </div>
            <div className="kpi-box">
              <div className="kpi-label">Used by</div>
              <div className="kpi-val">{card.n_strategies_using}</div>
              <div className="kpi-sub">strategies key off it</div>
            </div>
          </div>
        </div>
      </div>

      {/* Series */}
      <div className="card">
        <div className="card-hdr"><span className="card-lbl">Scored series</span></div>
        <div className="card-body">
          {detail.series.length === 0 ? (
            <p className="quiet" style={{ fontSize: 11.5, padding: "8px 0", lineHeight: 1.6 }}>
              No points yet. The compute pass (cron / Modal) populates this once the index is active and its source is reachable.
              Nothing is plotted until there is a real series.
            </p>
          ) : (
            detail.series.map((s) => {
              const values = s.points.map((p) => p.value);
              const labels = s.points.map((p) => fmtTz(p.ts, { month: "short", day: "numeric" }));
              return (
                <div key={s.symbol} style={{ marginBottom: 10 }}>
                  <div className="psec-title" style={{ marginBottom: 4 }}>{s.symbol} · {s.points.length} points</div>
                  <EquityChart values={values} labels={labels} axis valueFormat={(i) => values[i].toFixed(3)} color="var(--iris)" />
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Strategies built on it */}
      <div className="card">
        <div className="card-hdr"><span className="card-lbl">Strategies built on this index</span></div>
        <div className="card-body">
          {detail.strategies_using.length === 0 ? (
            <p className="quiet" style={{ fontSize: 11.5 }}>
              None yet. A strategy keys off this index by referencing <span className="mono">{card.metric}</span> as a feature.
            </p>
          ) : (
            <div className="similar-list">
              {detail.strategies_using.map((s) => (
                <Link key={s.version_id} href={`/strategies?v=${s.version_id}`} className="similar-row">
                  <span className="similar-name">{s.name}</span>
                  <span className="similar-meta"><span className="badge badge-muted" style={{ textTransform: "capitalize" }}>{s.status || "—"}</span></span>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
