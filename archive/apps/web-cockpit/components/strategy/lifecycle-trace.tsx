"use client";

// module: LifecycleTrace — the per-Version lifecycle READ-OUT for the strategy sheet. It fetches the engine's
// composed readiness verdict (GET /readiness/{version_id}) — the SAME deterministic verdicts the live-arming
// gate uses (live_eligibility = paper_maturity + current_regime), so this surface can never disagree with the
// money path — and renders:
//   • a 4-stop lifecycle rail  Backtest → Paper → Forward-ready → Live-ready, lit to the stage reached;
//   • the paper-maturity proof  (forward days vs the min, net-of-fee %), the honest live-eligibility reason;
//   • the ordered audit trace off the events ledger (oldest→newest), each mark plain-language.
//
// HONESTY: this is an ADVISORY read — it never arms money (the 5 interlocks remain the sole authority). Every
// number is bound to a real field off ReadinessResponse; honest loading / empty / error states throughout, and
// nothing is fabricated when the engine has no trace yet.

import { useEffect, useState } from "react";
import type { ReadinessResponse } from "@cosmu/contracts-ts";
import { engineGetJson, enginePeek } from "@/lib/engine";
import { cn, timeAgo } from "@/lib/utils";

// The four lifecycle stops, in order. A version's `stage` (and its paper/eligibility verdicts) light the rail.
type Stop = { key: string; label: string };
const STOPS: Stop[] = [
  { key: "backtest", label: "Backtest" },
  { key: "paper", label: "Paper" },
  { key: "forward", label: "Forward-ready" },
  { key: "live", label: "Live-ready" }
];

// How far along the rail this version is, from the composed verdict. We derive the lit-index from the real
// fields rather than trusting a single free-text stage string: a backtest always exists once it's on the board;
// any paper age means it reached Paper; forward_ready (matured + net-positive) lights Forward-ready; an eligible
// verdict (all interlocks bar the human) lights Live-ready. Killed/queued degrade gracefully to the earliest lit.
function litIndex(r: ReadinessResponse): number {
  const stage = (r.stage ?? "").toLowerCase();
  if (r.eligible) return 3; // live-ready (everything but the human toggle)
  if (r.live_eligibility.forward_ready) return 2; // matured + net-positive forward
  if (r.paper_maturity.paper_age_days > 0 || stage === "paper" || stage === "live") return 1; // reached paper
  return 0; // backtest only
}

export function LifecycleTrace({ versionId }: { versionId: string }) {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [state, setState] = useState<"loading" | "idle" | "error">("loading");

  useEffect(() => {
    const path = `/readiness/${versionId}`;
    const cached = enginePeek<ReadinessResponse>(path);
    if (cached) {
      setData(cached);
      setState("idle");
      return;
    }
    let cancelled = false;
    setState("loading");
    engineGetJson<ReadinessResponse>(path)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [versionId]);

  return (
    <div className="psec" id="sheet-lifecycle">
      <div className="psec-title" data-tip="The version's lifecycle — composed from the SAME deterministic verdicts the live-arming gate uses (paper maturity + regime). Advisory: it never arms money.">
        Lifecycle trace
      </div>
      {state === "loading" ? (
        <div className="skel" style={{ height: 64 }} />
      ) : state === "error" || (data && (!data.paper_maturity || !data.live_eligibility)) ? (
        // A partial readiness payload (the contract types the nested verdicts non-null, but the engine can omit
        // them) would white-screen LifecycleBody/litIndex on deref — fall back to the honest could-not-load note.
        <p className="quiet" style={{ fontSize: 11 }}>Could not load the lifecycle trace — the engine did not respond. Nothing is fabricated.</p>
      ) : data ? (
        <LifecycleBody data={data} />
      ) : null}
    </div>
  );
}

function LifecycleBody({ data }: { data: ReadinessResponse }) {
  const lit = litIndex(data);
  const mat = data.paper_maturity;
  const elig = data.live_eligibility;
  const fwdDays = Math.floor(mat.paper_age_days);
  const netPct = mat.net_return_pct;

  return (
    <>
      {/* the 4-stop rail — a lit dot per stop reached, the current stop glows; the connecting line lights up to
          the current stop (mirrors the screener's lifecycle glyph mechanics). */}
      <div className="glyph" aria-label={`lifecycle stage ${data.stage ?? "unknown"}`} style={{ marginBottom: 8, gap: 0 }}>
        {STOPS.map((s, i) => {
          const reached = i < lit;
          const current = i === lit;
          return (
            <span key={s.key} style={{ display: "inline-flex", alignItems: "center", gap: 0 }}>
              <span className={cn("g-dot", reached && "done", current && "cur")} data-tip={s.label} />
              {i < STOPS.length - 1 ? <span className={cn("g-line", i < lit && "done")} style={{ width: 24 }} /> : null}
            </span>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        {STOPS.map((s, i) => (
          <span
            key={s.key}
            className={cn("badge", i === lit ? "badge-iris" : i < lit ? "badge-up" : "badge-muted")}
            style={i > lit ? { opacity: 0.5 } : undefined}
          >
            {s.label}
          </span>
        ))}
      </div>

      {/* the paper-maturity proof + the honest live-eligibility reason — the forward number that proves the edge. */}
      <div className="blocks">
        <div className="block-row">
          <span className="block-key" style={{ width: 130 }} data-tip="Calendar days the forward (paper) clock has run since the track's first mark.">
            Forward days
          </span>
          <span className="block-val">
            {fwdDays > 0 ? <span className="tab">{fwdDays}d</span> : <span className="quiet">— not started</span>}
            <span className="quiet"> / {mat.min_days}d min</span>
          </span>
        </div>
        <div className="block-row">
          <span className="block-key" style={{ width: 130 }} data-tip="Net-of-fee forward return on the live-marked paper track — the only number that proves the edge forward.">
            Forward net
          </span>
          <span className={cn("block-val", "tab", netPct > 0 ? "up" : netPct < 0 ? "dn" : "")}>
            {Number.isFinite(netPct) ? `${netPct >= 0 ? "+" : ""}${netPct.toFixed(2)}%` : <span className="quiet">—</span>}
          </span>
        </div>
        <div className="block-row">
          <span className="block-key" style={{ width: 130 }} data-tip="Whether the version has cleared the forward-readiness bar (matured AND net-of-fee positive).">
            Forward-ready
          </span>
          <span className={cn("block-val", elig.forward_ready ? "up" : "")}>
            {elig.forward_ready ? "yes" : <span className="quiet">not yet</span>}
          </span>
        </div>
        <div className="block-row">
          <span className="block-key" style={{ width: 130 }} data-tip="The composed live-eligibility verdict — every interlock bar the human toggle. This NEVER arms money.">
            Live-ready
          </span>
          <span className={cn("block-val", data.eligible ? "up" : "")}>
            {data.eligible ? "eligible" : <span className="quiet">not yet</span>}
            {elig.overridden ? <span className="quiet"> · overridden</span> : null}
          </span>
        </div>
      </div>
      {elig.reason ? (
        <p className="quiet" style={{ fontSize: 11, marginTop: 6 }}>{elig.reason}</p>
      ) : null}

      {/* the ordered audit trace off the events ledger — oldest first, each mark plain. Honest empty otherwise. */}
      <TraceList data={data} />
    </>
  );
}

// One audit mark per row: a plain-language verb for the ledger `kind`, the actor, and "how long ago".
const TRACE_VERB: Record<string, string> = {
  created: "Authored",
  version_created: "Authored",
  backtested: "Backtested",
  gate_passed: "Cleared the Gate",
  gate_failed: "Blocked by the Gate",
  promoted: "Promoted to Paper",
  track_opened: "Paper track opened",
  paper_filled: "First paper fill",
  forward_ready: "Forward-ready",
  live_armed: "Armed live",
  live_launched: "Launched live",
  killed: "Killed",
  graveyard: "Graveyarded"
};

function TraceList({ data }: { data: ReadinessResponse }) {
  const marks = Array.isArray(data.trace) ? data.trace : [];
  if (marks.length === 0) {
    return <p className="quiet" style={{ fontSize: 11, marginTop: 8 }}>No lifecycle events recorded yet — marks appear here as the version is backtested, promoted, and traded.</p>;
  }
  return (
    <div className="act-list" style={{ marginTop: 8 }}>
      {marks.map((m, i) => {
        const verb = TRACE_VERB[(m.kind ?? "").toLowerCase()] ?? (m.kind ? m.kind.replace(/_/g, " ") : "Event");
        const ago = timeAgo(m.ts);
        return (
          <div key={`${m.kind}-${m.ts}-${i}`} className={i === marks.length - 1 ? "act-row cur-ev" : "act-row"}>
            <span className="act-time">{ago ?? "—"}</span>
            <span className="act-text">
              <strong>{verb}</strong>
              {m.actor ? <span className="quiet"> · {m.actor}</span> : null}
            </span>
          </div>
        );
      })}
    </div>
  );
}
