"use client";

// Operator cost overrides — a deterministic, client-side layer over the engine/billing register.
//
// WHY THIS EXISTS: several suppliers don't expose exact spend via API (Anthropic's flat Max subscription,
// Railway, Modal …), so the register is partly plan-tier *estimates*. This lets the operator pin a real
// figure they know, or add a cost line the engine can't see at all. It is honest precisely because an
// operator-entered number is labelled "set" (operator-entered), never dressed up as a fetched "actual".
//
// PERSISTENCE: localStorage on THIS browser. There is no cost-write endpoint in the CostsResponse
// contract, so this never pretends to reach the backend. It is fully reversible — reset an edit or remove
// a manual row and the engine figure comes back. Cross-device sync would need a real backend store.

import { useCallback, useEffect, useState } from "react";
import type { RegisterRow } from "./cost-sections";

const LS_KEY = "cosmu.costs.overrides.v1";

// An override of an engine row's numbers (keyed by vendor). null means "unset" (fall back to engine).
export type RowEdit = { amount?: number | null; budget?: number | null };

// A wholly operator-authored cost line the engine never reported.
export type ManualRow = {
  id: string;
  vendor: string;
  /** One of the four canonical buckets (infra / trading / data / ai). */
  category: string;
  amount: number | null;
  budget: number | null;
  note?: string;
};

export type CostOverrides = {
  /** Edits to engine rows, keyed by lowercased vendor. */
  edits: Record<string, RowEdit>;
  /** Operator-added cost lines. */
  added: ManualRow[];
};

const EMPTY: CostOverrides = { edits: {}, added: [] };
const keyOf = (v: string) => v.trim().toLowerCase();

function load(): CostOverrides {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return EMPTY;
    const parsed = JSON.parse(raw) as Partial<CostOverrides>;
    return { edits: parsed.edits ?? {}, added: Array.isArray(parsed.added) ? parsed.added : [] };
  } catch {
    return EMPTY;
  }
}

function persist(o: CostOverrides) {
  try {
    window.localStorage.setItem(LS_KEY, JSON.stringify(o));
  } catch {
    /* storage disabled / full — overrides simply don't persist this session */
  }
}

// A register row tagged with its provenance for the editable view.
export type DisplayRow = RegisterRow & {
  /** Stable id: lowercased vendor for engine rows, the manual id for added rows. */
  _id: string;
  /** engine = untouched · edited = operator pinned a number · manual = operator-authored line. */
  _origin: "engine" | "edited" | "manual";
};

// Merge the engine register with operator overrides into the display set.
export function mergeOverrides(register: RegisterRow[], ov: CostOverrides): DisplayRow[] {
  const engine: DisplayRow[] = register.map((r) => {
    const edit = ov.edits[keyOf(r.vendor)];
    if (!edit) return { ...r, _id: keyOf(r.vendor), _origin: "engine" };
    const amount = edit.amount ?? r.amount;
    return {
      ...r,
      amount,
      budget: edit.budget ?? r.budget,
      // A pinned amount supersedes any range — it's now a point figure.
      range: edit.amount != null ? null : r.range,
      _id: keyOf(r.vendor),
      _origin: "edited",
    };
  });
  const manual: DisplayRow[] = ov.added.map((m) => ({
    vendor: m.vendor,
    category: m.category,
    amount: m.amount,
    range: null,
    budget: m.budget,
    period: "manual",
    source: "est",
    note: m.note ?? null,
    _id: m.id,
    _origin: "manual",
  }));
  return [...engine, ...manual];
}

// The hook: reads overrides on mount (client-only, so SSR renders the plain engine view first), and
// exposes deterministic mutators that persist immediately.
export function useCostOverrides() {
  const [ov, setOv] = useState<CostOverrides>(EMPTY);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setOv(load());
    setReady(true);
  }, []);

  const apply = useCallback((mut: (prev: CostOverrides) => CostOverrides) => {
    setOv((prev) => {
      const next = mut(prev);
      persist(next);
      return next;
    });
  }, []);

  const editRow = useCallback(
    (vendor: string, patch: RowEdit) =>
      apply((prev) => {
        const k = keyOf(vendor);
        const merged: RowEdit = { ...prev.edits[k], ...patch };
        const edits = { ...prev.edits };
        // Drop a fully-empty edit so the row cleanly reverts to the engine figure.
        if (merged.amount == null && merged.budget == null) delete edits[k];
        else edits[k] = merged;
        return { ...prev, edits };
      }),
    [apply],
  );

  const resetRow = useCallback(
    (vendor: string) =>
      apply((prev) => {
        const edits = { ...prev.edits };
        delete edits[keyOf(vendor)];
        return { ...prev, edits };
      }),
    [apply],
  );

  const addRow = useCallback(
    () =>
      apply((prev) => ({
        ...prev,
        added: [
          ...prev.added,
          {
            id: `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
            vendor: "New cost",
            category: "infra",
            amount: 0,
            budget: null,
          },
        ],
      })),
    [apply],
  );

  const editManual = useCallback(
    (id: string, patch: Partial<ManualRow>) =>
      apply((prev) => ({
        ...prev,
        added: prev.added.map((m) => (m.id === id ? { ...m, ...patch } : m)),
      })),
    [apply],
  );

  const removeManual = useCallback(
    (id: string) =>
      apply((prev) => ({ ...prev, added: prev.added.filter((m) => m.id !== id) })),
    [apply],
  );

  const hasOverrides = ready && (Object.keys(ov.edits).length > 0 || ov.added.length > 0);

  return { ov, ready, hasOverrides, editRow, resetRow, addRow, editManual, removeManual };
}
