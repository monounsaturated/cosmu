// module: SpecView — renders a Version's StrategySpec as the v18 "Building blocks" picture (Iris Bento
// `.blocks` → `.block-row` with a `.block-key` label + `.block-val` value) rather than a raw JSON dump.
// It pulls the known StrategySpec fields out of the free-form spec (universe, horizon, catalyst, entry/exit
// structure, risk, composable modules, and the fitted param_space) and lays them out as labelled rows.
// The `spec` is typed Record<string, unknown> in the contract, so every read is defensive — anything
// unrecognized is shown raw at the bottom so nothing is silently dropped. Where a block has no real value
// it reads an honest "—" in a `.quiet` span. Server-safe; no fabricated values.

type Json = Record<string, unknown>;

function isRecord(v: unknown): v is Json {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// Collect the named features a spec references: from entry/exit/setup leaf conditions (`feature`/
// `indicator` keys). Deduped, point-in-time names only.
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

// The composable modules a spec declares (multi_tp, break_even, ma_trend_filter, orb, fvg_*, …). These
// live on exit/setup as named flags or non-empty lists; we surface the ones present.
function collectModules(spec: Json): string[] {
  const mods = new Set<string>();
  const exit = isRecord(spec.exit) ? spec.exit : {};
  const setup = isRecord(spec.setup) ? spec.setup : {};
  for (const src of [exit, setup]) {
    for (const [k, v] of Object.entries(src)) {
      if (v === true || (Array.isArray(v) && v.length > 0)) mods.add(k);
    }
  }
  return [...mods].sort();
}

// One-line summaries of each lifecycle block from the real spec. null → an honest "—".
function blockSummaries(spec: Json): { signal: string | null; filter: string | null; exit: string | null; sizing: string | null } {
  const features = collectFeatures(spec);
  const modules = collectModules(spec);
  const exit = isRecord(spec.exit) ? spec.exit : null;
  const risk = isRecord(spec.risk) ? spec.risk : null;

  const signal = features.length ? features.slice(0, 3).join(" · ") + (features.length > 3 ? ` +${features.length - 3}` : "") : null;
  const filter = modules.length ? modules.map((m) => m.replace(/_/g, " ")).join(" · ") : null;

  const exitBits: string[] = [];
  if (exit) {
    if (typeof exit.stop_pct === "number") exitBits.push(`stop ${(exit.stop_pct * 100).toFixed(1)}%`);
    else if (typeof exit.stop === "number") exitBits.push(`stop ${exit.stop}`);
    if (typeof exit.take_pct === "number") exitBits.push(`take ${(exit.take_pct * 100).toFixed(1)}%`);
    else if (typeof exit.take === "number") exitBits.push(`take ${exit.take}`);
    if (typeof exit.time_stop_days === "number") exitBits.push(`time-stop ${exit.time_stop_days}d`);
  }
  const exitStr = exitBits.length ? exitBits.join(" · ") : null;

  let sizing: string | null = null;
  if (risk) {
    const bits: string[] = [];
    if (typeof risk.max_position_pct === "number") bits.push(`${Math.round(risk.max_position_pct * 100)}% size`);
    if (typeof risk.max_concurrent_positions === "number") bits.push(`max ${risk.max_concurrent_positions} pos`);
    if (bits.length) sizing = bits.join(" · ");
  }

  return { signal, filter, exit: exitStr, sizing };
}

function BlockRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="block-row">
      <span className="block-key">{label}</span>
      <span className="block-val">{value ?? <span className="quiet">—</span>}</span>
    </div>
  );
}

// The headline "Building blocks" picture — Signal · Filter · Exit · Sizing, each off the real spec.
export function SpecBlocks({ spec }: { spec: Record<string, unknown> }) {
  const b = blockSummaries(spec as Json);
  return (
    <div className="blocks">
      <BlockRow label="Signal" value={b.signal} />
      <BlockRow label="Filter" value={b.filter} />
      <BlockRow label="Exit" value={b.exit} />
      <BlockRow label="Sizing" value={b.sizing} />
    </div>
  );
}

// The full spec view (universe/horizon/features/modules/params + raw extras) — used on the standalone
// /strategy/[id] page where there is room for the complete picture.
export function SpecView({ spec, params }: { spec: Record<string, unknown>; params: Record<string, unknown> }) {
  const hasSpec = spec && Object.keys(spec).length > 0;
  if (!hasSpec) {
    return <p className="quiet" style={{ fontSize: 11.5 }}>No spec recorded — a Version&apos;s StrategySpec appears here once it is authored.</p>;
  }

  const universe = isRecord(spec.universe) ? spec.universe : null;
  const horizon = isRecord(spec.horizon) ? spec.horizon : null;
  const risk = isRecord(spec.risk) ? spec.risk : null;
  const features = collectFeatures(spec as Json);
  const modules = collectModules(spec as Json);
  const paramSpace = isRecord(spec.param_space) ? spec.param_space : {};
  const fitted = params && Object.keys(params).length > 0 ? params : paramSpace;

  const KNOWN = new Set(["name", "rationale", "universe", "horizon", "catalyst", "entry", "exit", "risk", "param_space", "setup"]);
  const extra: Json = {};
  for (const [k, v] of Object.entries(spec)) if (!KNOWN.has(k)) extra[k] = v;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      {typeof spec.rationale === "string" && spec.rationale ? (
        <div className="psec" style={{ margin: 0 }}>
          <div className="psec-title">Thesis</div>
          <p className="ai-body">{spec.rationale}</p>
        </div>
      ) : null}

      <div className="blocks">
        {universe ? (
          <div className="block-row">
            <span className="block-key">Universe</span>
            <span className="block-val">
              {Array.isArray(universe.asset_classes) ? (universe.asset_classes as string[]).join(", ") : "—"}
              {Array.isArray(universe.venues) && universe.venues.length ? ` · ${(universe.venues as string[]).join(", ")}` : ""}
            </span>
          </div>
        ) : null}
        {horizon ? (
          <div className="block-row">
            <span className="block-key">Horizon</span>
            <span className="block-val">
              {String(horizon.min_hold_days ?? "?")}–{String(horizon.max_hold_days ?? "?")} days
            </span>
          </div>
        ) : null}
        {typeof spec.catalyst === "string" && spec.catalyst ? (
          <div className="block-row">
            <span className="block-key">Catalyst</span>
            <span className="block-val">{spec.catalyst}</span>
          </div>
        ) : null}
        {risk ? (
          <div className="block-row">
            <span className="block-key">Risk</span>
            <span className="block-val">
              max {String(risk.max_concurrent_positions ?? "?")} pos · {Math.round(Number(risk.max_position_pct ?? 0) * 100)}% size
            </span>
          </div>
        ) : null}
      </div>

      <div>
        <div className="psec-title" style={{ marginBottom: 6 }}>Features</div>
        {features.length ? (
          <div className="chip-row">
            {features.map((f) => (
              <span key={f} className="badge badge-iris">{f}</span>
            ))}
          </div>
        ) : (
          <p className="quiet" style={{ fontSize: 11 }}>No named features referenced.</p>
        )}
      </div>

      <div>
        <div className="psec-title" style={{ marginBottom: 6 }}>Composable modules</div>
        {modules.length ? (
          <div className="chip-row">
            {modules.map((m) => (
              <span key={m} className="badge badge-run">{m.replace(/_/g, " ")}</span>
            ))}
          </div>
        ) : (
          <p className="quiet" style={{ fontSize: 11 }}>No composable modules declared (single stop/take only).</p>
        )}
      </div>

      <div>
        <div className="psec-title" style={{ marginBottom: 6 }}>
          Params {params && Object.keys(params).length ? "(fitted)" : "(search space)"}
        </div>
        {Object.keys(fitted).length ? (
          <div className="tbl-scroll">
            <table className="mini-tbl">
              <thead>
                <tr>
                  <th>Param</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(fitted).map(([k, v]) => (
                  <tr key={k}>
                    <td className="mono">{k}</td>
                    <td className="mono muted">{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="quiet" style={{ fontSize: 11 }}>No params — thresholds are not parameterized.</p>
        )}
      </div>

      {Object.keys(extra).length ? (
        <details className="psec" style={{ margin: 0 }}>
          <summary className="quiet" style={{ cursor: "pointer", fontSize: 11.5 }}>Other spec fields</summary>
          <pre className="mono iris" style={{ overflowX: "auto", fontSize: 11, marginTop: 8 }}>
            {JSON.stringify(extra, null, 2)}
          </pre>
        </details>
      ) : null}
    </div>
  );
}
