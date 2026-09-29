"use client";

// intent: pick where you'd trade → the same 23 buys, re-priced with that platform's commission, FX and
//   slippage. Same data as the hero; only the cost model changes. Shows why costs decide small edges.

import { useState } from "react";
import { DEMO, PLATFORMS, applyCosts, pct, usd } from "@/lib/demo";

export function FeeLab() {
  const [id, setId] = useState(PLATFORMS[0].id);
  const p = PLATFORMS.find((x) => x.id === id)!;
  const r = applyCosts(DEMO, p);
  const lost = r.gross - r.net;
  const all = PLATFORMS.map((x) => applyCosts(DEMO, x).net);
  const best = Math.max(...all);

  return (
    <div className="cell">
      <div className="cell-label" style={{ marginBottom: 12 }}>Trade it on…</div>
      <div className="plats">
        {PLATFORMS.map((x, i) => (
          <button key={x.id} className="plat" aria-pressed={x.id === id} onClick={() => setId(x.id)} type="button">
            <div className="n">{x.name}</div>
            <div className="k">{x.kind}</div>
            <div className={`mono ${all[i] === best ? "up" : "muted"}`} style={{ fontSize: 12, marginTop: 8 }}>
              {pct(all[i])}
            </div>
          </button>
        ))}
      </div>

      <div className="fee-out">
        <div>
          <div className="cell-label">Net return, all costs in</div>
          <div className={`big ${r.net >= 0 ? "up" : "dn"}`} style={{ marginTop: 10 }}>{pct(r.net)}</div>
          <div className="muted" style={{ fontSize: 13, marginTop: 10 }}>
            Costs ate <span className="mono dn">{(lost * 100).toFixed(1)} pts</span> of the{" "}
            <span className="mono">{pct(r.gross)}</span> gross. {p.note}
          </div>
          <div className="drag" aria-hidden>
            <i style={{ width: `${Math.max(0, r.net / r.gross) * 100}%`, background: "var(--up)" }} />
            <i style={{ width: `${Math.min(1, lost / r.gross) * 100}%`, background: "var(--down)" }} />
          </div>
        </div>
        <div className="rows">
          <div><span>Cash put in ({DEMO.stats.trades} buys)</span><span>{usd(r.invested)}</span></div>
          <div><span>Commissions</span><span>{usd(DEMO.events.reduce((a, e) => a + p.commission(e.price), 0))}</span></div>
          <div><span>FX, slippage{p.carryPerYear ? ", financing" : ""}</span><span>{usd(r.fees - DEMO.events.reduce((a, e) => a + p.commission(e.price), 0))}</span></div>
          <div><span>Value on {DEMO.window[1]}</span><span>{usd(r.value)}</span></div>
        </div>
      </div>
    </div>
  );
}
