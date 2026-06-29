// module: ConvictionProposals — the propose-only authority-conviction review queue (cosmu/conviction). One card
// per proposal built from a high-authority account's fresh asset-call: the asset + direction, the capped size +
// HARD max-loss + expiry, the plain-language thesis, and the authority EVIDENCE the human weighs before arming
// (authority composite + skill + EV/magnitude + top prior calls + the source post). Server-safe (no client JS).
//
// HONESTY + SAFETY: every number is a REAL field off ConvictionProposalsResponse — never fabricated. This surface
// is PROPOSE-ONLY: it shows proposals and the evidence; it has NO arm button and CANNOT move money. Arming a
// conviction bet is a separate, explicit human action off this surface (the lane never auto-arms). Empty queue →
// the honest "nothing proposed yet" state, never a placeholder bet.

import type { ReactNode } from "react";
import type { ConvictionProposalRow, ConvictionProposalsResponse } from "@cosmu/contracts-ts";
import { fmtTz, timeAgo } from "@/lib/utils";

function num(v: number | null | undefined, digits = 2): string {
  return typeof v === "number" ? v.toFixed(digits) : "—";
}

function signedPct(v: number | null | undefined): ReactNode {
  if (typeof v !== "number") return <span className="quiet">—</span>;
  const pp = v * 100;
  return <span className={pp >= 0 ? "up" : "dn"}>{pp >= 0 ? "+" : ""}{pp.toFixed(1)}%</span>;
}

function DirectionBadge({ direction }: { direction: string }) {
  const long = direction === "long";
  return (
    <span className={`badge ${long ? "badge-up" : "badge-dn"}`} style={{ textTransform: "none" }}>
      {long ? "Long" : "Short"}
    </span>
  );
}

function ProposalCard({ p }: { p: ConvictionProposalRow }) {
  const ev = p.evidence;
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <div className="card-body">
        {/* headline: account · asset · direction · size · max-loss */}
        <div className="toolbar-row" style={{ marginBottom: 6, alignItems: "baseline" }}>
          <span className="page-title" style={{ fontSize: 13 }}>
            {ev.account} <span className="quiet">·</span> {p.asset} <DirectionBadge direction={p.direction} />
          </span>
          <span className="quiet tab" style={{ fontSize: 11 }}>
            size <strong>${p.size_usd}</strong> <span className="quiet">·</span> max-loss{" "}
            <strong className="dn">${p.max_loss_usd}</strong>
          </span>
        </div>

        {/* authority evidence — the WHY, the part the human weighs before arming */}
        <div className="tbl-scroll">
          <table className="mini-tbl">
            <thead>
              <tr>
                <th className="r" data-tip="Authority composite the lane gated + sized on (skill-anchored, [0,1]). The bigger this is, the bigger the (still-capped) bet.">Authority</th>
                <th className="r" data-tip="Deflated Brier skill on resolved calls — calibration vs the base rate, shrunk for sample size.">Skill</th>
                <th className="r" data-tip="Excess-hit × magnitude — the PROFIT proxy. A few-but-huge caller scores high here on its big calls (profit > hit-rate).">EV/call</th>
                <th className="r" data-tip="Mean |move| on the account's correct calls — does it call BIG moves, not just any move.">Magnitude</th>
                <th className="r" data-tip="Resolved calls — the sample size behind the score. Small = read with caution.">Resolved</th>
                <th className="r" data-tip="Citation-PageRank (influence), shown alongside — NOT the gate (influence ≠ authority).">Citation</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="r tab" style={{ fontWeight: 600 }}>{num(ev.authority_score)}</td>
                <td className="r tab">{num(ev.skill)}</td>
                <td className="r tab">{num(ev.ev_per_call, 3)}</td>
                <td className="r tab">{signedPct(ev.avg_hit_magnitude)}</td>
                <td className="r tab">{ev.n_resolved || <span className="quiet">0</span>}</td>
                <td className="r tab">{num(ev.citation_authority)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* the disconfirmer context + the thesis */}
        <p className="quiet" style={{ fontSize: 11, marginTop: 8, lineHeight: 1.55 }}>
          <span className={`badge ${ev.is_primary ? "badge-iris" : "badge-muted"}`} style={{ textTransform: "none" }}>
            {ev.is_primary ? "primary" : "echo"}
          </span>{" "}
          <span className={`badge ${ev.lead_lag === "evidence" ? "badge-up" : ev.lead_lag === "echo" ? "badge-dn" : "badge-muted"}`} style={{ textTransform: "none" }}>
            lead-lag: {ev.lead_lag}
          </span>{" "}
          {p.thesis}
        </p>

        {/* the source post the call came from */}
        {ev.source_quote ? (
          <blockquote className="quiet" style={{ fontSize: 11, margin: "6px 0 0", paddingLeft: 8, borderLeft: "2px solid var(--line, #333)", fontStyle: "italic" }}>
            “{ev.source_quote}”
            {ev.source_url ? (
              <>
                {" "}
                <a href={ev.source_url} target="_blank" rel="noreferrer noopener" className="mono" style={{ fontStyle: "normal" }}>
                  source ↗
                </a>
              </>
            ) : null}
          </blockquote>
        ) : null}

        {/* top prior correct calls — the magnitude track record */}
        {ev.top_movers.length ? (
          <p className="quiet" style={{ fontSize: 10.5, marginTop: 6 }}>
            Top prior calls:{" "}
            {ev.top_movers.map((m, i) => (
              <span key={`${m.entity}-${i}`}>
                {i > 0 ? " · " : ""}
                {m.entity} {m.direction} {signedPct(m.realized_return)}
              </span>
            ))}
          </p>
        ) : null}

        {/* propose-only: the human arms — there is no arm button here */}
        <div className="toolbar-row" style={{ marginTop: 8, alignItems: "center" }}>
          <span className="badge badge-gold" style={{ textTransform: "none" }} data-tip="Propose-only. The conviction lane never auto-arms — a human reviews this evidence and arms the bet off this surface. Nothing here moves money.">
            Awaiting human · not armed
          </span>
          <span className="quiet" style={{ fontSize: 10.5 }}>
            expires {fmtTz(p.expiry, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      </div>
    </div>
  );
}

export function ConvictionProposals({ conviction }: { conviction: ConvictionProposalsResponse }) {
  const proposals = conviction.proposals ?? [];

  return (
    <>
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <span className="page-title">Conviction proposals</span>
        <span className="quiet" style={{ fontSize: 11 }}>
          {proposals.length === 0
            ? "none proposed"
            : `${proposals.length} awaiting review`}
          {proposals[0] ? <> · top {proposals[0].account}</> : null}
        </span>
      </div>

      {proposals.length === 0 ? (
        <div className="card">
          <div className="card-body">
            <p className="quiet" style={{ fontSize: 12, textAlign: "center", padding: "28px 8px", lineHeight: 1.65, maxWidth: 580, margin: "0 auto" }}>
              No conviction proposals yet. When a followed account whose <em>authority</em> clears the threshold
              posts a fresh, actionable, non-echo asset-call, the engine sizes a capped conviction bet (authority ×
              EV, hard max-loss) and queues it here for you to review and arm. Propose-only — nothing is armed or
              funded until you act. Register voices in <span className="mono">cosmu/config/voices.py</span> and run
              the credibility pass to start the flow.
            </p>
          </div>
        </div>
      ) : (
        <>
          <p className="quiet" style={{ fontSize: 11, marginBottom: 10, lineHeight: 1.55 }}>
            Each proposal follows a high-authority account's fresh call. Sizing scales with the account&apos;s
            authority and EV (profit &gt; hit-rate) under a hard per-bet + max-loss cap. This is the LLM/Conviction
            lane — guardrails, small size, <strong>human-armed</strong>; it never touches the deterministic quant
            Gate and never moves money on its own.
          </p>
          {proposals.map((p) => (
            <ProposalCard key={p.proposal_id} p={p} />
          ))}
        </>
      )}
    </>
  );
}
