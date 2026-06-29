// Trades — the ONE feed of every execution (paper AND live) newest-first, each tagged Paper/Live so simulated
// money is never confused with real money. Off GET /executions; nothing fabricated — honest not-connected /
// empty states when there are no fills. A paper fill is SIMULATED against the venue's real fees (no real order);
// a live fill is real/testnet money. The strategy name links to its Version sheet.
//
// LOADING UX: a SYNC server component returns the instant chrome (Page + Toolbar) and streams the data region
// under <Suspense> so the toolbar paints immediately while the engine read resolves.

import { Suspense } from "react";
import Link from "next/link";
import type { ExecutionListItem } from "@cosmu/contracts-ts";
import { engineConfigured } from "../data";
import { getExecutions } from "../data/trades";
import { Page, Toolbar } from "@/components/ui/toolbar";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { fmtTz, formatUsd, formatVenue } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default function TradesPage() {
  return (
    <Page>
      <Suspense
        fallback={
          <>
            <Toolbar title="Trades" />
            <div className="skel" style={{ height: 420 }} />
          </>
        }
      >
        <TradesData />
      </Suspense>
    </Page>
  );
}

async function TradesData() {
  const { data, connected } = await getExecutions();
  const rows = data.rows;

  if (!connected) {
    return (
      <>
        <Toolbar title="Trades" />
        <NotConnected
          configured={engineConfigured}
          what="Every trade — paper (simulated) and live (real) — newest first, tagged so the two are never confused. Appears once the engine is connected; nothing is fabricated."
        />
      </>
    );
  }

  const paperN = rows.filter((r) => r.is_paper).length;
  const liveN = rows.length - paperN;

  return (
    <>
      <Toolbar
        title="Trades"
        left={
          rows.length > 0 ? (
            <span className="quiet" style={{ fontSize: 11, marginLeft: 4 }}>
              {rows.length} fills · {paperN} paper · <span style={{ color: liveN > 0 ? "var(--gold)" : undefined }}>{liveN} live</span>
            </span>
          ) : undefined
        }
      />
      <div className="card">
        <div className="card-body">
          {rows.length === 0 ? (
            <EmptyState
              title="No trades yet."
              hint="Fills appear here as strategies trade — paper (simulated against the venue's real fees) and live (real money), each tagged. The deterministic Gate alone funds; this is just the honest ledger."
            />
          ) : (
            <div className="tbl-scroll">
              <table className="mini-tbl">
                <thead>
                  <tr>
                    <th>Date · time</th>
                    <th>Strategy</th>
                    <th>Side</th>
                    <th className="r">Qty</th>
                    <th className="r">Price</th>
                    <th className="r">Fee</th>
                    <th>Venue</th>
                    <th>Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <TradeRow key={t.id} t={t} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function TradeRow({ t }: { t: ExecutionListItem }) {
  const date = fmtTz(t.ts, { month: "short", day: "2-digit" });
  const time = fmtTz(t.ts, { hour: "2-digit", minute: "2-digit", hour12: false });
  return (
    <tr>
      <td>
        {date ? (
          <>
            {date} <span className="quiet">{time}</span>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="pos-strat">
        <Link className="strat-link" href={`/strategy/${t.strategy_version_id}`} title={t.strategy_name}>
          {t.strategy_name}
        </Link>
      </td>
      <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{t.side === "buy" ? "Buy" : "Sell"}</td>
      <td className="r tab">{t.qty}</td>
      <td className="r tab">{formatUsd(t.price, 2)}</td>
      {/* A live fill's fee is REAL money — mark it gold; a paper fee is simulated. */}
      <td className="r tab" style={t.is_paper ? { color: "var(--quiet)" } : { color: "var(--gold)", fontWeight: 600 }}>
        {formatUsd(t.fee, 2)}
      </td>
      <td className="pos-venue">{formatVenue(t.venue)}</td>
      <td>
        {t.is_paper ? (
          <span className="badge badge-muted" title="Simulated paper fill — priced against the venue's real fees, but no real order was placed.">Paper</span>
        ) : (
          <span className="badge badge-gold" title="Real / testnet LIVE fill — real money at the venue.">Live</span>
        )}
      </td>
    </tr>
  );
}
