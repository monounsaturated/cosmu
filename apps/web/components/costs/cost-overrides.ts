"use client";

// Operator cost overrides — a deterministic, client-side layer over the engine/billing register, shaped
// as the v18 "Subscriptions & renewals" model (source · cadence · last paid · next renewal · /mo ·
// lifetime · proj/yr).
//
// WHY THIS EXISTS: the engine/billing APIs give a current amount for some suppliers, but NOT the renewal
// calendar (last-paid / next-renewal), the cadence, or lifetime-to-date — and several suppliers don't
// report exact spend at all (Anthropic's flat Max sub, Railway, Modal). So the operator pins those facts
// here and the table computes /mo and proj/yr live. It is honest: an operator-entered figure is labelled
// and never dressed up as a fetched "actual".
//
// PERSISTENCE: localStorage on THIS browser. There is no cost-write endpoint in the CostsResponse
// contract, so this never pretends to reach the backend. Fully reversible (reset an edit / remove a row).

import { useCallback, useEffect, useState } from "react";

const LS_KEY = "cosmu.costs.subs.v1";

export type Cadence = "monthly" | "yearly" | "usage" | "flat" | "oneoff" | "perfill";

export const CADENCE_LABEL: Record<Cadence, string> = {
  monthly: "monthly",
  yearly: "yearly",
  usage: "usage",
  flat: "flat",
  oneoff: "one-off",
  perfill: "per fill · auto",
};

// An edit of an engine-seeded subscription row (keyed by source). Any field absent ⇒ use the seed.
export type SubEdit = {
  cat?: string;
  cadence?: Cadence;
  perMo?: number | null;
  lastPaid?: string | null;
  renews?: string | null;
  lifetime?: number | null;
};

// A wholly operator-authored cost line the engine never reported.
export type ManualSub = {
  id: string;
  source: string;
  cat: string;
  cadence: Cadence;
  perMo: number | null;
  lastPaid: string | null;
  renews: string | null;
  lifetime: number | null;
};

export type CostOverrides = {
  edits: Record<string, SubEdit>;
  added: ManualSub[];
};

const EMPTY: CostOverrides = { edits: {}, added: [] };
export const subKey = (v: string) => v.trim().toLowerCase();

// The engine-seeded shape handed to the merge (built from the cost register on the server side, mapped to
// the subscriptions vocabulary on the client).
export type SubSeed = {
  source: string;
  cat: string;
  cadence: Cadence;
  perMo: number | null;
  note?: string | null;
  /** Provenance of the seed amount: live billing / engine actual / plan-tier estimate. */
  origin: "live" | "actual" | "est";
};

// A merged, displayable subscription row.
export type SubRow = {
  _id: string;
  /** engine = untouched seed · edited = operator pinned ≥1 field · manual = operator-authored. */
  _kind: "engine" | "edited" | "manual";
  source: string;
  cat: string;
  cadence: Cadence;
  perMo: number | null;
  lastPaid: string | null;
  renews: string | null;
  lifetime: number | null;
  note?: string | null;
  seedOrigin?: SubSeed["origin"];
};

function load(): CostOverrides {
  if (typeof window === "undefined") return EMPTY;
  try {
    const raw = window.localStorage.getItem(LS_KEY);
    if (!raw) return EMPTY;
    const p = JSON.parse(raw) as Partial<CostOverrides>;
    return { edits: p.edits ?? {}, added: Array.isArray(p.added) ? p.added : [] };
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

// Merge engine seeds + operator overrides into the display set.
export function mergeSubs(seeds: SubSeed[], ov: CostOverrides): SubRow[] {
  const engine: SubRow[] = seeds.map((s) => {
    const k = subKey(s.source);
    const e = ov.edits[k];
    const base: SubRow = {
      _id: k,
      _kind: "engine",
      source: s.source,
      cat: s.cat,
      cadence: s.cadence,
      perMo: s.perMo,
      lastPaid: null,
      renews: null,
      lifetime: null,
      note: s.note ?? null,
      seedOrigin: s.origin,
    };
    if (!e) return base;
    return {
      ...base,
      _kind: "edited",
      cat: e.cat ?? base.cat,
      cadence: e.cadence ?? base.cadence,
      perMo: e.perMo !== undefined ? e.perMo : base.perMo,
      lastPaid: e.lastPaid !== undefined ? e.lastPaid : base.lastPaid,
      renews: e.renews !== undefined ? e.renews : base.renews,
      lifetime: e.lifetime !== undefined ? e.lifetime : base.lifetime,
    };
  });
  const manual: SubRow[] = ov.added.map((m) => ({
    _id: m.id,
    _kind: "manual",
    source: m.source,
    cat: m.cat,
    cadence: m.cadence,
    perMo: m.perMo,
    lastPaid: m.lastPaid,
    renews: m.renews,
    lifetime: m.lifetime,
  }));
  return [...engine, ...manual];
}

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
    (source: string, patch: SubEdit) =>
      apply((prev) => {
        const k = subKey(source);
        const merged: SubEdit = { ...prev.edits[k], ...patch };
        const edits = { ...prev.edits };
        // Drop a fully-empty edit so the row cleanly reverts to the engine seed.
        const empty = Object.values(merged).every((v) => v === undefined);
        if (empty) delete edits[k];
        else edits[k] = merged;
        return { ...prev, edits };
      }),
    [apply],
  );

  const resetRow = useCallback(
    (source: string) =>
      apply((prev) => {
        const edits = { ...prev.edits };
        delete edits[subKey(source)];
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
            source: "New cost",
            cat: "infra",
            cadence: "monthly",
            perMo: 0,
            lastPaid: null,
            renews: null,
            lifetime: null,
          },
        ],
      })),
    [apply],
  );

  const editManual = useCallback(
    (id: string, patch: Partial<ManualSub>) =>
      apply((prev) => ({
        ...prev,
        added: prev.added.map((m) => (m.id === id ? { ...m, ...patch } : m)),
      })),
    [apply],
  );

  const removeManual = useCallback(
    (id: string) => apply((prev) => ({ ...prev, added: prev.added.filter((m) => m.id !== id) })),
    [apply],
  );

  const hasOverrides = ready && (Object.keys(ov.edits).length > 0 || ov.added.length > 0);

  return { ov, ready, hasOverrides, editRow, resetRow, addRow, editManual, removeManual };
}
