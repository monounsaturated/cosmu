// SubscriptionsTable — the "Subscriptions & renewals" register.
//
// READ-ONLY mirror of the code-maintained cost register (apps/web/app/data/cost-register.ts). Costs are
// edited in code (by Claude Code), never in the browser — so there is no inline editing, no override
// layer and no "Refresh" column (every line is operator-maintained). Columns: Source · Cat · Cadence ·
// Last paid · Next renewal · / mo · Lifetime · Proj / yr. Proj / yr = /mo × 12.

import { CatBadge } from "./cost-sections";
import { CADENCE_LABEL, type CostLine } from "@/app/data/cost-register";
import { formatUsd } from "@/lib/utils";

// ── date helpers (real dates, "in Nd") ──
function dParse(iso: string) {
  return new Date(iso + "T00:00:00");
}
function fmtD(iso: string | null): string {
  if (!iso) return "—";
  return dParse(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
function daysAway(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((dParse(iso).getTime() - today.getTime()) / 86400000);
}
function inDays(iso: string | null): string {
  if (!iso) return "";
  const n = daysAway(iso);
  return n < 0 ? `${-n}d ago` : n === 0 ? "today" : `in ${n}d`;
}

// Whole-dollar display throughout. Project from the ROUNDED monthly so each row reads /mo × 12, and
// totals sum the rounded per-line values — keeping the table, the tiles and the headline boxes in lockstep.
const money = (v: number) => (Math.round(v) === 0 ? "$0" : formatUsd(Math.round(v)));
const proj = (perMo: number) => Math.round(perMo) * 12;

function DateCell({ value }: { value: string | null }) {
  if (!value) return <span className="quiet">—</span>;
  const away = inDays(value);
  return (
    <>
      <span className="tab">{fmtD(value)}</span>
      {away ? (
        <span className="muted" style={{ fontSize: 9.5 }}>
          {" "}
          {away}
        </span>
      ) : null}
    </>
  );
}

export function SubscriptionsTable({ rows }: { rows: CostLine[] }) {
  const totMo = rows.reduce((s, r) => s + Math.round(r.perMo), 0);
  const totLife = rows.reduce((s, r) => s + Math.round(r.lifetime), 0);

  return (
    <div className="tbl-scroll">
      <table className="mini-tbl subs-tbl">
        <thead>
          <tr>
            <th>Source</th>
            <th>Cat</th>
            <th>Cadence</th>
            <th className="r">Last paid</th>
            <th className="r">Next renewal</th>
            <th className="r">/ mo</th>
            <th className="r">Lifetime</th>
            <th className="r">Proj / yr</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.source}>
              <td>
                <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.source}</span>
                <span className="quiet" style={{ display: "block", fontSize: 9.5, marginTop: 1 }}>
                  {r.note}
                </span>
              </td>
              <td>
                {r.category === "other" ? (
                  <span className="muted" style={{ fontSize: 11 }}>Other</span>
                ) : (
                  <CatBadge category={r.category} />
                )}
              </td>
              <td className="muted">{CADENCE_LABEL[r.cadence]}</td>
              <td className="r muted">
                <DateCell value={r.lastPaid} />
              </td>
              <td className="r">
                <DateCell value={r.renews} />
              </td>
              <td className="r tab">{money(r.perMo)}</td>
              <td className="r tab run-tot">{money(r.lifetime)}</td>
              <td className="r tab muted">{money(proj(r.perMo))}</td>
            </tr>
          ))}
          <tr className="sub-row">
            <td style={{ fontWeight: 600, color: "var(--fg)" }}>Total</td>
            <td colSpan={4} className="quiet" style={{ fontSize: 9.5 }}>
              {rows.length} source{rows.length === 1 ? "" : "s"} · maintained in code
            </td>
            <td className="r tab" style={{ fontWeight: 600 }}>
              {money(totMo)}
            </td>
            <td className="r tab" style={{ fontWeight: 600 }}>
              {money(totLife)}
            </td>
            <td className="r tab" style={{ fontWeight: 600 }}>
              {money(proj(totMo))}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
