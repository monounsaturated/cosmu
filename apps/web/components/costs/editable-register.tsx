"use client";

// EditableRegisterTable — the cost register as a deterministic, operator-editable ledger.
//
// Same `.mini-tbl` shape as the read-only RegisterTable, but Amount and Budget are click-to-edit on every
// row, and operator-added rows are fully editable (vendor / category / amount / budget). Provenance is
// always visible: engine rows keep their live/actual/est. chip; an operator-pinned figure flips to a "set"
// chip with a reset link; manual rows show "set" with a remove link. Nothing operator-entered is ever
// labelled "actual". All edits persist to localStorage via useCostOverrides (this browser only).

import { useState } from "react";
import { CatBadge, type RegisterRow } from "./cost-sections";
import type { DisplayRow } from "./cost-overrides";
import { formatUsd, formatSigned } from "@/lib/utils";

const CATS = ["infra", "trading", "data", "ai"] as const;

// A click-to-edit number cell. Renders the formatted value; clicking swaps in a `.cap-in` input that
// commits on blur / Enter. An empty input commits null (revert to engine / "—").
function NumCell({
  value,
  align = "r",
  render,
  onCommit,
  tip,
}: {
  value: number | null;
  align?: string;
  render: (v: number | null) => React.ReactNode;
  onCommit: (next: number | null) => void;
  tip?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value === null ? "" : String(value));

  function commit() {
    setEditing(false);
    const t = draft.trim();
    if (t === "") return onCommit(null);
    const n = parseFloat(t);
    if (!Number.isNaN(n) && n >= 0) onCommit(n);
  }

  if (editing) {
    return (
      <td className={`${align} tab`}>
        <input
          className="cap-in"
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            if (e.key === "Escape") {
              setDraft(value === null ? "" : String(value));
              setEditing(false);
            }
          }}
          aria-label="cost amount"
        />
      </td>
    );
  }
  return (
    <td
      className={`${align} tab cost-edit`}
      data-tip={tip ?? "Click to set a figure"}
      onClick={() => {
        setDraft(value === null ? "" : String(value));
        setEditing(true);
      }}
    >
      {render(value)}
    </td>
  );
}

// A click-to-edit text cell (vendor name on manual rows).
function TextCell({ value, onCommit }: { value: string; onCommit: (next: string) => void }) {
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
        aria-label="cost source name"
      />
    );
  }
  return (
    <span
      className="cost-edit"
      style={{ fontWeight: 500, color: "var(--fg)" }}
      data-tip="Click to rename"
      onClick={() => {
        setDraft(value);
        setEditing(true);
      }}
    >
      {value}
    </span>
  );
}

function amountNode(r: RegisterRow) {
  if (r.amount !== null) return r.amount === 0 ? <span className="quiet">$0</span> : formatUsd(r.amount, 2);
  if (r.range) return <span className="muted">{r.range}</span>;
  return <span className="quiet">—</span>;
}

export function EditableRegisterTable({
  rows,
  onEditAmount,
  onEditBudget,
  onReset,
  onEditManual,
  onRemoveManual,
}: {
  rows: DisplayRow[];
  onEditAmount: (row: DisplayRow, next: number | null) => void;
  onEditBudget: (row: DisplayRow, next: number | null) => void;
  onReset: (row: DisplayRow) => void;
  onEditManual: (id: string, patch: { vendor?: string; category?: string; amount?: number | null; budget?: number | null }) => void;
  onRemoveManual: (id: string) => void;
}) {
  const totalKnown = rows.reduce((s, r) => s + (r.amount ?? 0), 0);
  return (
    <div className="tbl-scroll">
      <table className="mini-tbl">
        <thead>
          <tr>
            <th>Source</th>
            <th>Category</th>
            <th className="r">Amount</th>
            <th className="r">Budget</th>
            <th className="r">Headroom</th>
            <th className="r">Period</th>
            <th>Origin</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const headroom = r.budget !== null && r.amount !== null ? r.budget - r.amount : null;
            const over = headroom !== null && headroom < 0;
            const manual = r._origin === "manual";
            return (
              <tr key={r._id}>
                <td>
                  {manual ? (
                    <TextCell value={r.vendor} onCommit={(v) => onEditManual(r._id, { vendor: v })} />
                  ) : (
                    <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.vendor}</span>
                  )}
                  {r.note ? (
                    <span className="quiet" style={{ display: "block", fontSize: 9.5, marginTop: 1, maxWidth: 260, whiteSpace: "normal", lineHeight: 1.35 }}>
                      {r.note}
                    </span>
                  ) : null}
                </td>
                <td>
                  {manual ? (
                    <select
                      className="cat-select"
                      value={r.category.toLowerCase()}
                      onChange={(e) => onEditManual(r._id, { category: e.target.value })}
                      aria-label="cost category"
                    >
                      {CATS.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <CatBadge category={r.category} />
                  )}
                </td>
                <NumCell
                  value={r.amount}
                  render={() => amountNode(r)}
                  onCommit={(n) => (manual ? onEditManual(r._id, { amount: n }) : onEditAmount(r, n))}
                />
                <NumCell
                  value={r.budget}
                  render={(v) => (v !== null ? <span className="muted">{formatUsd(v, 2)}</span> : <span className="quiet">—</span>)}
                  onCommit={(n) => (manual ? onEditManual(r._id, { budget: n }) : onEditBudget(r, n))}
                  tip="Click to set a budget cap"
                />
                <td className="r tab">
                  {headroom !== null ? <span className={over ? "dn" : "up"}>{formatSigned(headroom)}</span> : <span className="quiet">—</span>}
                </td>
                <td className="r muted" style={{ whiteSpace: "nowrap" }}>{r.period ?? <span className="quiet">—</span>}</td>
                <td>
                  {r._origin === "engine" ? (
                    <SourceChip source={r.source} />
                  ) : (
                    <span className="iris" style={{ fontSize: 10.5 }} data-tip="Operator-entered — stored in this browser">
                      set
                    </span>
                  )}
                </td>
                <td className="r">
                  {r._origin === "edited" ? (
                    <button type="button" className="row-act" onClick={() => onReset(r)} data-tip="Revert to the engine figure">
                      reset
                    </button>
                  ) : manual ? (
                    <button type="button" className="row-act row-act-dn" onClick={() => onRemoveManual(r._id)} data-tip="Remove this line">
                      remove
                    </button>
                  ) : null}
                </td>
              </tr>
            );
          })}
          <tr>
            <td style={{ fontWeight: 600, color: "var(--fg)" }}>Total</td>
            <td className="quiet" style={{ fontSize: 9.5 }}>known point figures</td>
            <td className="r tab" style={{ fontWeight: 600 }}>{formatUsd(totalKnown, 2)}</td>
            <td className="r" />
            <td className="r" />
            <td className="r" />
            <td />
            <td />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// Local copy of the engine-source chip (live / actual / est.) — kept here so the editable table is
// self-contained alongside the operator "set" chip.
function SourceChip({ source }: { source: RegisterRow["source"] }) {
  if (source === "live") return <span className="up" style={{ fontSize: 10.5 }}>live</span>;
  if (source === "actual") return <span className="iris" style={{ fontSize: 10.5 }}>actual</span>;
  return <span className="quiet" style={{ fontSize: 10.5 }}>est.</span>;
}
