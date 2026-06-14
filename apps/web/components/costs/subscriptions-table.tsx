"use client";

// SubscriptionsTable — the v18 "Subscriptions & renewals" register, operator-editable.
//
// Columns: Source · Cat · Cadence · Last paid · Next renewal · / mo · Lifetime · Proj / yr. The /mo seed
// is the engine's real billing figure; the renewal calendar (last-paid / next-renewal), cadence and
// lifetime are subscription facts the engine doesn't report, so they default to "—" and the operator pins
// them inline (saved to localStorage via useCostOverrides). Proj / yr computes live (= /mo × 12). Manual
// rows ("+ Add cost") are fully editable. Operator-entered rows are chipped "set" — never faked as fetched.

import { useState } from "react";
import { CatBadge } from "./cost-sections";
import { CADENCE_LABEL, type Cadence, type SubRow } from "./cost-overrides";
import { formatUsd } from "@/lib/utils";

const CATS = ["infra", "trading", "data", "ai"] as const;
const CADENCES: Cadence[] = ["monthly", "yearly", "usage", "flat", "oneoff", "perfill"];

// ── date helpers (mirror the v18 expense engine: real dates, "in Nd") ──
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

const proj = (perMo: number | null) => (perMo === null ? null : perMo * 12);
const money = (v: number | null) => (v === null ? "—" : v === 0 ? "$0" : formatUsd(Math.round(v)));

// ── inline click-to-edit primitives ──
function EditNum({ value, onCommit, tip }: { value: number | null; onCommit: (n: number | null) => void; tip?: string }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value === null ? "" : String(value));
  if (editing) {
    return (
      <input
        className="cap-in"
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const t = draft.trim();
          if (t === "") return onCommit(null);
          const n = parseFloat(t);
          if (!Number.isNaN(n) && n >= 0) onCommit(n);
          // Invalid (non-number / negative): commit NOTHING and revert the draft to the live value, so the
          // rejected text doesn't silently persist in the field and reappear on the next edit.
          else setDraft(value === null ? "" : String(value));
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") {
            setDraft(value === null ? "" : String(value));
            setEditing(false);
          }
        }}
        aria-label="amount"
      />
    );
  }
  return (
    <span
      className="cost-edit"
      data-tip={tip ?? "Click to set"}
      onClick={() => {
        setDraft(value === null ? "" : String(value));
        setEditing(true);
      }}
    >
      {money(value)}
    </span>
  );
}

function EditDate({ value, onCommit }: { value: string | null; onCommit: (iso: string | null) => void }) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <input
        type="date"
        className="cap-in cap-in-date"
        autoFocus
        defaultValue={value ?? ""}
        onChange={(e) => {
          onCommit(e.target.value || null);
        }}
        onBlur={() => setEditing(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "Escape") (e.target as HTMLInputElement).blur();
        }}
        aria-label="date"
      />
    );
  }
  const renew = inDays(value);
  return (
    <span className="cost-edit" data-tip="Click to set a date" onClick={() => setEditing(true)}>
      {value ? (
        <>
          <span className="tab">{fmtD(value)}</span>
          {renew ? <span className="muted" style={{ fontSize: 9.5 }}> {renew}</span> : null}
        </>
      ) : (
        <span className="quiet">—</span>
      )}
    </span>
  );
}

// Click-to-edit select: shows `display` (a badge / muted label) until clicked, then a native select that
// commits on change. Keeps the v18 read view clean while staying editable.
function EditSelect<T extends string>({
  value,
  options,
  labels,
  display,
  cls,
  onChange,
}: {
  value: T;
  options: readonly T[];
  labels?: Record<string, string>;
  display: React.ReactNode;
  cls: string;
  onChange: (v: T) => void;
}) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <select
        className={cls}
        autoFocus
        value={value}
        onChange={(e) => {
          onChange(e.target.value as T);
          setEditing(false);
        }}
        onBlur={() => setEditing(false)}
        aria-label="select"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {labels ? labels[o] : o}
          </option>
        ))}
      </select>
    );
  }
  return (
    <span className="cost-edit" data-tip="Click to change" onClick={() => setEditing(true)}>
      {display}
    </span>
  );
}

function EditText({ value, onCommit }: { value: string; onCommit: (s: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  if (editing) {
    return (
      <input
        className="cap-in cap-in-wide"
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          setEditing(false);
          const t = draft.trim();
          if (t) onCommit(t);
          else setDraft(value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        aria-label="source name"
      />
    );
  }
  return (
    <span className="cost-edit" style={{ fontWeight: 500, color: "var(--fg)" }} data-tip="Click to rename" onClick={() => setEditing(true)}>
      {value}
    </span>
  );
}

export function SubscriptionsTable({
  rows,
  onEdit,
  onReset,
  onEditManual,
  onRemoveManual,
}: {
  rows: SubRow[];
  onEdit: (source: string, patch: Partial<Pick<SubRow, "cat" | "cadence" | "perMo" | "lastPaid" | "renews" | "lifetime">>) => void;
  onReset: (source: string) => void;
  onEditManual: (id: string, patch: Partial<SubRow>) => void;
  onRemoveManual: (id: string) => void;
}) {
  const totMo = rows.reduce((s, r) => s + (r.perMo ?? 0), 0);
  const totLife = rows.reduce((s, r) => s + (r.lifetime ?? 0), 0);
  const anyLife = rows.some((r) => r.lifetime !== null);

  // Route an edit to the right store (engine/edited rows → onEdit by source; manual → onEditManual by id).
  const put = (r: SubRow, patch: Record<string, unknown>) =>
    r._kind === "manual" ? onEditManual(r._id, patch) : onEdit(r.source, patch);

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
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r._id}>
              <td>
                {r._kind === "manual" ? (
                  <EditText value={r.source} onCommit={(v) => onEditManual(r._id, { source: v })} />
                ) : (
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.source}</span>
                )}
              </td>
              <td>
                <EditSelect
                  value={r.cat.toLowerCase() as (typeof CATS)[number]}
                  options={CATS}
                  cls="cat-select"
                  display={<CatBadge category={r.cat} />}
                  onChange={(c) => put(r, { cat: c })}
                />
              </td>
              <td className="muted">
                <EditSelect
                  value={r.cadence}
                  options={CADENCES}
                  labels={CADENCE_LABEL}
                  cls="cad-select"
                  display={<span className="muted">{CADENCE_LABEL[r.cadence]}</span>}
                  onChange={(c) => put(r, { cadence: c })}
                />
              </td>
              <td className="r muted">
                <EditDate value={r.lastPaid} onCommit={(d) => put(r, { lastPaid: d })} />
              </td>
              <td className="r">
                {r.cadence === "perfill" && !r.renews ? (
                  <span className="muted">continuous</span>
                ) : (
                  <EditDate value={r.renews} onCommit={(d) => put(r, { renews: d })} />
                )}
              </td>
              <td className="r tab">
                <EditNum value={r.perMo} onCommit={(n) => put(r, { perMo: n })} tip="Click to set the monthly run-rate" />
              </td>
              <td className="r tab run-tot">
                <EditNum value={r.lifetime} onCommit={(n) => put(r, { lifetime: n })} tip="Click to set lifetime spent" />
              </td>
              <td className="r tab muted">{money(proj(r.perMo))}</td>
              <td className="r">
                {r._kind === "edited" ? (
                  <button type="button" className="row-act" onClick={() => onReset(r.source)} data-tip="Revert to the engine figure">
                    reset
                  </button>
                ) : r._kind === "manual" ? (
                  <button type="button" className="row-act row-act-dn" onClick={() => onRemoveManual(r._id)} data-tip="Remove this line">
                    remove
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
          <tr className="sub-row">
            <td style={{ fontWeight: 600, color: "var(--fg)" }}>Total</td>
            <td colSpan={4} className="quiet" style={{ fontSize: 9.5 }}>
              {rows.length} source{rows.length === 1 ? "" : "s"} · run-rate &amp; projection compute live
            </td>
            <td className="r tab" style={{ fontWeight: 600 }}>{money(totMo)}</td>
            <td className="r tab" style={{ fontWeight: 600 }}>{anyLife ? money(totLife) : <span className="quiet">—</span>}</td>
            <td className="r tab" style={{ fontWeight: 600 }}>{money(proj(totMo))}</td>
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}
