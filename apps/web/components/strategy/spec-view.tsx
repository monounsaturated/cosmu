// module: SpecView — renders a Version's StrategySpec as a readable, named picture rather than a raw
// JSON dump (Deliverable #4). It pulls the known StrategySpec fields out of the free-form spec
// (rationale, universe, horizon, catalyst, entry/exit structure, risk, composable modules, and the
// fitted param_space) and lays them out as labelled groups. The `spec` is typed Record<string,
// unknown> in the contract, so every read is defensive — anything unrecognized is shown as raw JSON
// at the bottom so nothing is silently dropped. Server component; no fabricated values.

import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/honest-state";

type Json = Record<string, unknown>;

function isRecord(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Collect the named features a spec references: from entry/exit/setup leaf conditions (`feature`/
// `param`/`indicator` keys) plus param_space keys. Deduped, point-in-time names only.
function collectFeatures(spec: Json): string[] {
  const found = new Set<string>();
  const walk = (node: unknown) => {
    if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (isRecord(node)) {
      for (const [k, v] of Object.entries(node)) {
        if ((k === "feature" || k === "indicator") && typeof v === "string") found.add(v);
        else walk(v);
      }
    }
  };
  walk(spec.entry);
  walk(spec.exit);
  walk(spec.setup);
  return [...found].sort();
}

// The composable modules a spec declares (multi_tp, break_even, ma_trend_filter, orb, fvg_*, …).
// These live on exit/setup as either named flags or non-empty lists. We surface the ones that are
// present so the operator sees the building blocks without reading code.
function collectModules(spec: Json): string[] {
  const mods = new Set<string>();
  const exit = isRecord(spec.exit) ? spec.exit : {};
  const setup = isRecord(spec.setup) ? spec.setup : {};
  for (const src of [exit, setup]) {
    for (const [k, v] of Object.entries(src)) {
      const present =
        v === true || (Array.isArray(v) && v.length > 0) || (typeof v === "number" && v !== 0) || (typeof v === "string" && v.length > 0);
      // Skip plain scalars that are just thresholds (stop/take) — those are params, not modules.
      if (present && (Array.isArray(v) || v === true)) mods.add(k);
    }
  }
  return [...mods].sort();
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">{label}</span>
      <span className="text-[12.5px] text-foreground">{children}</span>
    </div>
  );
}

export function SpecView({ spec, params }: { spec: Record<string, unknown>; params: Record<string, unknown> }) {
  const hasSpec = spec && Object.keys(spec).length > 0;
  if (!hasSpec) {
    return <EmptyState title="No spec recorded." hint="A Version's StrategySpec — features, modules, and fitted params — appears here once it is authored." />;
  }

  const universe = isRecord(spec.universe) ? spec.universe : null;
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const risk = isRecord(spec.risk) ? spec.risk : null;
  const features = collectFeatures(spec);
  const modules = collectModules(spec);
  // Fitted params: prefer the resolved `params` map (concrete fitted values); fall back to the
  // spec's param_space (the search bounds) so we always show what's being tuned.
  const paramSpace = isRecord(spec.param_space) ? spec.param_space : {};
  const fitted = params && Object.keys(params).length > 0 ? params : paramSpace;

  // Known fields we render as named groups — the rest is shown raw so nothing is hidden.
  const KNOWN = new Set(["name", "rationale", "universe", "horizon", "catalyst", "entry", "exit", "risk", "param_space", "setup"]);
  const extra: Json = {};
  for (const [k, v] of Object.entries(spec)) if (!KNOWN.has(k)) extra[k] = v;

  return (
    <div className="space-y-5">
      {typeof spec.rationale === "string" && spec.rationale ? (
        <div className="rounded-md border border-border/50 bg-surface-2/30 p-3">
          <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">thesis</span>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted">{spec.rationale}</p>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {universe ? (
          <Field label="Universe">
            {Array.isArray(universe.asset_classes) ? (universe.asset_classes as string[]).join(", ") : "—"}
            {Array.isArray(universe.venues) && universe.venues.length ? (
              <span className="text-quiet"> · {(universe.venues as string[]).join(", ")}</span>
            ) : null}
          </Field>
        ) : null}
        {horizon ? (
          <Field label="Horizon">
            {String(horizon.min_hold_days ?? "?")}–{String(horizon.max_hold_days ?? "?")} days
          </Field>
        ) : null}
        {typeof spec.catalyst === "string" && spec.catalyst ? <Field label="Catalyst">{spec.catalyst}</Field> : null}
        {risk ? (
          <Field label="Risk">
            max {String(risk.max_concurrent_positions ?? "?")} pos · {Math.round(Number(risk.max_position_pct ?? 0) * 100)}% size
          </Field>
        ) : null}
      </div>

      {/* Named features referenced by the spec */}
      <div className="space-y-1.5">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">Features</span>
        {features.length ? (
          <div className="flex flex-wrap gap-1.5">
            {features.map((f) => (
              <Badge key={f} variant="iris">
                {f}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-[12px] text-quiet">No named features referenced.</p>
        )}
      </div>

      {/* Composable modules declared */}
      <div className="space-y-1.5">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">Composable modules</span>
        {modules.length ? (
          <div className="flex flex-wrap gap-1.5">
            {modules.map((m) => (
              <Badge key={m} variant="info">
                {m.replace(/_/g, " ")}
              </Badge>
            ))}
          </div>
        ) : (
          <p className="text-[12px] text-quiet">No composable modules declared (single stop/take only).</p>
        )}
      </div>

      {/* Fitted params (or the param_space search bounds) */}
      <div className="space-y-1.5">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">
          Params {params && Object.keys(params).length ? "(fitted)" : "(search space)"}
        </span>
        {Object.keys(fitted).length ? (
          <Table>
            <THead>
              <TR>
                <TH className="sticky-col">Param</TH>
                <TH>Value</TH>
              </TR>
            </THead>
            <TBody>
              {Object.entries(fitted).map(([k, v]) => (
                <TR key={k}>
                  <TD className="sticky-col font-mono text-[12px] text-foreground">{k}</TD>
                  <TD className="font-mono text-[12px] text-muted">{typeof v === "object" ? JSON.stringify(v) : String(v)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="text-[12px] text-quiet">No params — thresholds are not parameterized.</p>
        )}
      </div>

      {/* Anything unrecognized in the spec — shown raw so nothing is silently dropped. */}
      {Object.keys(extra).length ? (
        <details className="rounded-md border border-border/50 bg-surface-2/20">
          <summary className="cursor-pointer px-3 py-2 text-[11.5px] text-quiet">Other spec fields</summary>
          <pre className="overflow-x-auto px-3 pb-3 font-mono text-[11.5px] leading-relaxed text-iris-soft">
            {JSON.stringify(extra, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
