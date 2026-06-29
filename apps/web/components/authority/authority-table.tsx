"use client";

// module: AuthorityTable — the proprietary AUTHORITY dashboard, one composite row per account, sortable. The
// operator's spec: rank(#) · account(+roster percentile/z) · composite · hit-rate · EV · avg-move-when-right ·
// Brier · top-3 movers · #calls · last-call. Authority is RELATIVE — rank/percentile/z place an account against
// the roster (the best signal accounts rise to the top). Click a column header to re-sort (rank ascends, #1 best;
// everything else descends; UNTESTED rows — null on the sort key — always sort last). Minimal,
// uncluttered, no heavy viz. Client component only because of the interactive sort; every number is a REAL field
// off AuthorityResponse computed by the engine (the LLM only extracts the raw calls; the score is math).
//
// HONESTY: an account with no resolved calls yet is UNTESTED (composite/metrics null) — it renders a muted
// "untested", never a 0 that would read as "no skill". The web only DISPLAYS; the engine alone scores.

import { useState, type ReactNode } from "react";
import type { AuthorityResponse, AuthorityRow } from "@cosmu/contracts-ts";
import { fmtTz, timeAgo } from "@/lib/utils";

type SortKey = "rank" | "composite" | "hit_rate" | "ev" | "avg_move_when_right" | "brier" | "n_calls";

// Keys where SMALLER is better, so the click-to-sort orders them ASCENDING (rank #1 is the best account). Every
// other key sorts DESC. UNTESTED rows (null on the key) always fall last regardless of direction.
const ASC_KEYS = new Set<SortKey>(["rank"]);

const PLATFORM_BADGE: Record<string, string> = { x: "badge-iris", reddit: "badge-gold", youtube: "badge-run", telegram: "badge-iris" };

// A [0,1]-ish score → 2-decimal string, or a muted "untested" when null (no resolved calls yet). Untested is NOT
// zero — the distinction is the whole point of an honest scoreboard.
function score(v: number | null | undefined): ReactNode {
  return typeof v === "number" ? v.toFixed(2) : <span className="quiet">untested</span>;
}

// A fractional return → signed percentage, tinted up/down. null → muted dash.
function signedPct(v: number | null | undefined): ReactNode {
  if (typeof v !== "number") return <span className="quiet">—</span>;
  const pp = v * 100;
  return <span className={pp >= 0 ? "up" : "dn"}>{pp >= 0 ? "+" : ""}{pp.toFixed(1)}%</span>;
}

function pct(v: number | null | undefined): ReactNode {
  return typeof v === "number" ? `${(v * 100).toFixed(0)}%` : <span className="quiet">—</span>;
}

// The account's RELATIVE standing in the roster: percentile (1.0 = best) → "pNN", with the z-score in the tip.
// Null (untested / roster of one) → nothing. Authority is comparative — this is the "best signal account" read.
function standing(percentile: number | null | undefined, z: number | null | undefined): ReactNode {
  if (typeof percentile !== "number") return null;
  const zTip = typeof z === "number" ? ` · z ${z >= 0 ? "+" : ""}${z.toFixed(2)} vs roster` : "";
  return (
    <span className="badge badge-muted" style={{ textTransform: "none", fontSize: 9.5 }} data-tip={`Roster percentile (1.0 = best)${zTip}`}>
      p{Math.round(percentile * 100)}
    </span>
  );
}

function plain(v: number | null | undefined, digits = 2): ReactNode {
  return typeof v === "number" ? v.toFixed(digits) : <span className="quiet">—</span>;
}

// Sort by the chosen key DESC, with UNTESTED (null on that key) ALWAYS last and a stable account-name tiebreak.
// Pure + deterministic — a read-only re-sort of the engine's own rows.
function sortRows(rows: AuthorityRow[], key: SortKey): AuthorityRow[] {
  const asc = ASC_KEYS.has(key);
  return [...rows].sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    const na = typeof va === "number";
    const nb = typeof vb === "number";
    if (!na && !nb) return a.account.localeCompare(b.account);
    if (!na) return 1; // untested (null on this key) always last
    if (!nb) return -1;
    if (vb !== va) return asc ? (va as number) - (vb as number) : (vb as number) - (va as number);
    return a.account.localeCompare(b.account);
  });
}

export function AuthorityTable({ authority }: { authority: AuthorityResponse }) {
  const [sortKey, setSortKey] = useState<SortKey>("composite");
  const rows = sortRows(authority.rows ?? [], sortKey);
  const top = rows.find((r) => typeof r.composite === "number") ?? null;
  const freshness = timeAgo(authority.as_of);

  const Th = ({ k, label, tip }: { k: SortKey; label: string; tip: string }) => (
    <th
      className="r"
      data-tip={tip}
      aria-sort={sortKey === k ? "descending" : undefined}
      style={{ cursor: "pointer", userSelect: "none", color: sortKey === k ? "var(--iris, inherit)" : undefined }}
      onClick={() => setSortKey(k)}
    >
      {label}{sortKey === k ? " ↓" : ""}
    </th>
  );

  if ((authority.rows ?? []).length === 0) {
    return (
      <div className="card">
        <div className="card-body">
          <p className="quiet" style={{ fontSize: 12, textAlign: "center", padding: "28px 8px", lineHeight: 1.65, maxWidth: 600, margin: "0 auto" }}>
            No accounts scored yet. The Authority store is PROPRIETARY DATA — feed it account calls locally
            (a JSON dump, an xAI/Grok fetch, or a Claude-in-Chrome scrape) via{" "}
            <span className="mono">cosmu.authority</span>, then run the score pass. Each account then earns a
            composite from whether its past calls corroborated the tape — calibration, hit-rate, and PAYOFF.
            Nothing is fabricated until that data exists.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-body">
        <div className="toolbar-row" style={{ marginBottom: 8 }}>
          <span className="page-title">Authority scoreboard</span>
          <span className="quiet" style={{ fontSize: 11 }}>
            {authority.n_accounts} scored {authority.n_accounts === 1 ? "account" : "accounts"}
            {top ? <> · top {top.account}</> : null}
            {freshness ? <> · updated {freshness}</> : null}
          </span>
        </div>
        <p className="quiet" style={{ fontSize: 11, marginBottom: 8, lineHeight: 1.55 }}>
          Which accounts to trust, scored only on RESOLVED calls against the real tape and RANKED against each other
          (# / percentile / z — authority is relative, so the best signal accounts rise to the top). The composite
          weights PROFIT (EV) highest — an account wrong most of the time but huge on a few is still valuable. A
          late/echo call (the move already underway when posted) is discounted. Read-only — this never funds or
          fires; it is proprietary data that later powers a separate LLM strategy.
        </p>
        <div className="tbl-scroll">
          <table className="mini-tbl">
            <thead>
              <tr>
                <Th k="rank" label="#" tip="The account's RANK within the scored roster (1 = best). Authority is RELATIVE — rank, percentile and z are a position among peers, not an absolute. UNTESTED accounts are unranked." />
                <th>Account</th>
                <Th k="composite" label="Composite" tip="The headline [0,1] authority score: a profit-forward blend of EV, Brier skill, hit-rate excess, calibration, lead-time and consistency, shrunk for sample size." />
                <Th k="hit_rate" label="Hit-rate" tip="Fraction of resolved calls whose direction was realized. Profit can beat a low hit-rate (see EV)." />
                <Th k="ev" label="EV" tip="Cumulative return if each call were traded small — the payoff axis, weighted highest. A few huge wins can carry it." />
                <Th k="avg_move_when_right" label="Avg move" tip="Average size of the move on correct calls — magnitude, not just direction." />
                <Th k="brier" label="Brier" tip="Mean Brier score of the account's conviction forecasts (lower = better calibrated)." />
                <th className="r" data-tip="The three most profitable calls (asset + realized move). An account wrong 90% but huge on 10% shows it here.">Top movers</th>
                <Th k="n_calls" label="#Calls" tip="Calls attributed (volume, NOT skill). The resolved subset is what the metrics are scored on." />
                <th className="r" data-tip="When this account last made a call we have on record.">Last call</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const platform = (r.platform ?? "").toLowerCase();
                return (
                  <tr key={`${r.platform}:${r.account}`}>
                    <td className="r tab" style={{ fontWeight: 600, color: typeof r.rank === "number" ? undefined : "var(--muted, inherit)" }}>
                      {typeof r.rank === "number" ? r.rank : <span className="quiet">—</span>}
                    </td>
                    <td>
                      <span className="cell-name">{r.account}</span>
                      <div className="quiet" style={{ fontSize: 9.5 }}>
                        <span className={`badge ${PLATFORM_BADGE[platform] ?? "badge-muted"}`} style={{ textTransform: "none" }}>
                          {r.platform}
                        </span>
                        {standing(r.percentile, r.composite_z) ? <> {standing(r.percentile, r.composite_z)}</> : null}
                        {r.n_resolved ? <> · {r.n_resolved} resolved</> : <> · untested</>}
                        {r.n_echo ? <> · {r.n_echo} echo</> : null}
                      </div>
                    </td>
                    <td className="r tab" style={{ fontWeight: 600 }}>{score(r.composite)}</td>
                    <td className="r tab">{pct(r.hit_rate)}</td>
                    <td className="r tab">{signedPct(r.ev)}</td>
                    <td className="r tab">{pct(r.avg_move_when_right)}</td>
                    <td className="r tab">{plain(r.brier)}</td>
                    <td className="r">
                      {r.top_movers && r.top_movers.length > 0 ? (
                        <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap", justifyContent: "flex-end" }}>
                          {r.top_movers.map((m, i) => (
                            <span
                              key={i}
                              className="badge badge-muted"
                              style={{ textTransform: "none", fontSize: 9.5 }}
                              data-tip={`${m.direction} · ${(m.signed_return * 100).toFixed(0)}% move${m.is_echo ? " (echo, discounted)" : ""}`}
                            >
                              {m.asset} <span className={m.signed_return >= 0 ? "up" : "dn"}>{m.signed_return >= 0 ? "+" : ""}{(m.signed_return * 100).toFixed(0)}%</span>
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span className="quiet">—</span>
                      )}
                    </td>
                    <td className="r tab">{r.n_calls}</td>
                    <td className="r tab">
                      {r.last_call_ts && !Number.isNaN(new Date(r.last_call_ts).getTime())
                        ? fmtTz(r.last_call_ts, { month: "short", day: "2-digit" })
                        : <span className="quiet">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
