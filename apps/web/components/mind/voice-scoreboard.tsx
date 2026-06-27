// module: VoiceScoreboard — the followed-voices credibility read-out (realtime-data-lane P2). One row per
// pre-registered voice the Mind follows, with its citation AUTHORITY (the headline the operator asked for)
// and its underlying Brier SKILL, sorted authority-first. Server-safe (no client JS); every tooltip is the
// CSS `data-tip` affordance used across the app.
//
// HONESTY: every number is a REAL field off CredibilityResponse — never fabricated. A voice with no resolved
// claims yet is UNTESTED (skill/authority null): it renders a muted "untested", NEVER a 0 that would read as
// "no skill". The web only DISPLAYS this scoreboard; the engine alone scores a voice (no LLM on this path).

import type { ReactNode } from "react";
import type { CredibilityResponse, CredibilityRow } from "@cosmu/contracts-ts";
import { fmtTz, timeAgo } from "@/lib/utils";

const PLATFORM_BADGE: Record<string, string> = { x: "badge-iris", reddit: "badge-gold", rss: "badge-run" };
const PLATFORM_LABEL: Record<string, string> = { x: "X", reddit: "Reddit", rss: "RSS" };

// A [0,1] score → 2-decimal string, or a muted "untested" when null (no resolved claims yet). Untested is NOT
// zero — the distinction is the whole point of an honest scoreboard.
function score(v: number | null | undefined): ReactNode {
  return typeof v === "number" ? v.toFixed(2) : <span className="quiet">untested</span>;
}

// A skill-above-chance fraction → signed percentage points, tinted up/down. null → "—".
function excess(v: number | null | undefined): ReactNode {
  if (typeof v !== "number") return <span className="quiet">—</span>;
  const pp = v * 100;
  return <span className={pp >= 0 ? "up" : "dn"}>{pp >= 0 ? "+" : ""}{pp.toFixed(1)}pp</span>;
}

function pct(v: number | null | undefined): ReactNode {
  return typeof v === "number" ? `${(v * 100).toFixed(0)}%` : <span className="quiet">—</span>;
}

// Authority-first ordering (the operator's ask: "their authority score, sorted"), with untested voices last and
// a stable skill→handle tiebreak. Pure + deterministic — a read-only re-sort of the engine's own rows.
function byAuthority(rows: CredibilityRow[]): CredibilityRow[] {
  const rank = (r: CredibilityRow) => (typeof r.authority === "number" ? r.authority : typeof r.skill === "number" ? r.skill : null);
  return [...rows].sort((a, b) => {
    const ra = rank(a);
    const rb = rank(b);
    if (ra === null && rb === null) return a.handle.localeCompare(b.handle);
    if (ra === null) return 1;
    if (rb === null) return -1;
    if (rb !== ra) return rb - ra;
    return a.handle.localeCompare(b.handle);
  });
}

export function VoiceScoreboard({ credibility }: { credibility: CredibilityResponse }) {
  const rows = byAuthority(credibility.rows ?? []);
  const top = rows.find((r) => typeof r.authority === "number" || typeof r.skill === "number") ?? null;
  const freshness = timeAgo(credibility.as_of);

  return (
    <>
      <div className="toolbar-row" style={{ marginBottom: 8 }}>
        <span className="page-title">Voice scoreboard</span>
        <span className="quiet" style={{ fontSize: 11 }}>
          {credibility.panel_size === 0
            ? "no voices registered"
            : `${credibility.panel_size} followed ${credibility.panel_size === 1 ? "voice" : "voices"}`}
          {top ? <> · top {top.handle}</> : null}
          {freshness ? <> · updated {freshness}</> : null}
        </span>
      </div>

      {rows.length === 0 ? (
        <div className="card">
          <div className="card-body">
            <p className="quiet" style={{ fontSize: 12, textAlign: "center", padding: "28px 8px", lineHeight: 1.65, maxWidth: 560, margin: "0 auto" }}>
              No voices on the scoreboard yet. Register the panel in <span className="mono">apps/engine/cosmu/config/voices.py</span>{" "}
              and run the credibility pass — each followed voice then earns a Brier-skill and a citation-authority
              from its <em>resolved</em> claims against the tape. Nothing is fabricated until that data exists.
            </p>
          </div>
        </div>
      ) : (
        <div className="card">
          <div className="card-body">
            <p className="quiet" style={{ fontSize: 11, marginBottom: 8, lineHeight: 1.55 }}>
              Who the Mind follows and how much to trust them — scored only on <em>resolved</em> claims against the
              real tape. Authority is citation-weight anchored to skill (influence ≠ authority); an untested voice
              stays untested, never a zero. Read-only — this never funds or fires; the deterministic Gate alone disposes.
            </p>
            <div className="tbl-scroll">
              <table className="mini-tbl">
                <thead>
                  <tr>
                    <th>Voice</th>
                    <th className="r" data-tip="Citation-weighted authority anchored to skill (a PageRank over who cites whom). The headline trust score — influence is not the same as authority.">Authority</th>
                    <th className="r" data-tip="Brier skill on resolved claims — the [0,1] headline accuracy after shrinking for small samples. > base rate = real skill.">Skill</th>
                    <th className="r" data-tip="Hit-rate above the coin-at-base-rate baseline, in percentage points. The edge over chance.">Excess hit</th>
                    <th className="r" data-tip="Resolved claims — calls old enough to be scored against the tape. The sample size behind skill; small = read with caution.">Resolved</th>
                    <th className="r" data-tip="How often this voice is FIRST on a claim — a breaker (high) vs an echo (low).">Primacy</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const platform = (r.platform ?? "").toLowerCase();
                    return (
                      <tr key={`${r.platform}:${r.handle}`}>
                        <td>
                          <span className="cell-name">{r.handle}</span>
                          <div className="quiet" style={{ fontSize: 9.5 }}>
                            <span className={`badge ${PLATFORM_BADGE[platform] ?? "badge-muted"}`} style={{ textTransform: "none" }}>
                              {PLATFORM_LABEL[platform] ?? r.platform}
                            </span>
                            {r.n_claims ? <> · {r.n_claims} claims</> : null}
                            {r.updated_at && !Number.isNaN(new Date(r.updated_at).getTime())
                              ? <> · {fmtTz(r.updated_at, { month: "short", day: "2-digit" })}</>
                              : null}
                          </div>
                        </td>
                        <td className="r tab" style={{ fontWeight: 600 }}>{score(r.authority)}</td>
                        <td className="r tab">{score(r.skill)}</td>
                        <td className="r tab">{excess(r.excess_hit_rate)}</td>
                        <td className="r tab">{r.n_resolved || <span className="quiet">0</span>}</td>
                        <td className="r tab">{pct(r.primacy_rate)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
