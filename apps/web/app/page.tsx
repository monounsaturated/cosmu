// intent: the Cosmu landing page — lean and pain-first. Hero (pain + live demo) → why traders lose and how
//   Cosmu fixes each cause → how it works (the engine's real pipeline) → any idea, numbers or news → CTA. Market numbers come from lib/showcase.json;
//   the "+89% before costs" figure comes from the archived engine's reports (archive/docs/reports).

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Studio } from "@/components/studio";
import { Icon } from "@/components/icon";
import { VerdictBadge } from "@/components/verdict-badge";
import { IDEAS, STOCK_PLATFORMS, pct, results, verdict } from "@/lib/showcase";
import ENGINE from "@/lib/engine-stats.json";

const NVDA = IDEAS.find((i) => i.key === "ai_nvda") ?? IDEAS[0];
const rN = results(NVDA, STOCK_PLATFORMS[0]);
const fmt = (n: number) => n.toLocaleString("en-US");
const COST = ENGINE.cost_example; // sourced: archive/docs/reports/edge-hunt-mktneutral-2026-06-25.md
const pctInt = (x: number) => `${x >= 0 ? "+" : "−"}${Math.round(Math.abs(x) * 100)}%`;
// The engine's real funnel (lib/engine-stats.json, snapshotted from its production DB by scripts/landing/engine_stats.py).
const FUNNEL = [
  { l: "Strategies tested", n: ENGINE.strategies_tested },
  { l: "Survived the first screen", n: ENGINE.survived_first_screen },
  { l: "Earned paper trading", n: ENGINE.paper_traded },
];
const window2 = (d: string) => new Date(d + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", timeZone: "UTC" });

// Three reasons retail traders lose, each with Cosmu's fix and one visual proof.
const PAINS = [
  {
    pain: "You buy the headline.",
    fix: "Cosmu shows what happened every time before, and whether the news or the market did the work.",
    art: (
      <div className="p-art">
        <div className="p-ask"><Icon name="spark" size={14} /> Big AI launch today. Buy Nvidia?</div>
        <div className="p-row">
          <span>After the last {NVDA.trades.length} launches</span>
          <b className="up">{pct(rN.avg)}</b>
        </div>
        <div className="p-row">
          <span>Any random month, same years</span>
          <b>{pct(rN.randomMonth)}</b>
        </div>
        <VerdictBadge v={verdict(NVDA)} />
      </div>
    ),
  },
  {
    pain: "Fees eat the edge.",
    fix: "Every result is net of your broker's real commission, currency fee and spread. Before you trade, not after.",
    art: (
      <div className="p-art p-bars">
        <div><span>Before costs</span><i className="p-track"><i style={{ width: `${COST.gross * 100}%` }} /></i><em className="up">{pctInt(COST.gross)}</em></div>
        <div><span>After costs</span><i className="p-track"><i className="neg" style={{ width: `${Math.abs(COST.net) * 100}%` }} /></i><em className="dn">{pctInt(COST.net)}</em></div>
        <small>Our own crypto momentum research · {fmt(COST.trades)} trades · fees and slippage included</small>
      </div>
    ),
  },
  {
    pain: "Luck looks like skill.",
    fix: "Every idea is checked against luck: random dates, overfitting tests, a period it never saw. Most fail. You only act on the few that don't.",
    art: (
      <div className="p-art p-funnel">
        {FUNNEL.map((f) => (
          <div key={f.l} className="fn-row">
            <span>{f.l}</span>
            <i className="p-track"><i style={{ width: `${Math.max(2.5, (f.n / FUNNEL[0].n) * 100)}%` }} /></i>
            <b>{fmt(f.n)}</b>
          </div>
        ))}
        <small>
          Our own engine, {window2(ENGINE.window[0])}–{window2(ENGINE.window[1])} 2026 · {fmt(ENGINE.backtests)} backtests ·{" "}
          {(ENGINE.simulated_trades / 1e6).toFixed(1)}M simulated trades
        </small>
      </div>
    ),
  },
];

// The pipeline the engine actually ran (archive/apps/engine): spec → backtest → gate → paper → live.
const STEPS = [
  { t: "Describe it", d: "In plain words. AI turns it into precise rules, with no peeking at the future." },
  { t: "Test it", d: "On years of real prices, news, sentiment and on-chain data, with your broker's fees." },
  { t: "Judge it", d: "Against luck: random dates, overfitting checks, an untouched test period. Most ideas die here." },
  { t: "Paper-trade it", d: "Survivors trade live prices with virtual money, each in its own account." },
  { t: "Go live, if you choose", d: "Real money only when you say so, behind five safety locks." },
];

const QUANT = ["Buy Bitcoin after a 10% daily crash", "Buy the Nasdaq when the Fed cuts rates", "Sell when a stock runs 20% above its 200-day average"];
const QUAL = ["Buy defense stocks when a war breaks out", "Buy the Nasdaq when layoff news spikes", "Buy Bitcoin when a bank collapses"];

export default function Page() {
  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <a href="#" className="brand">
            <CosmuMark size={26} /> Cosmu
          </a>
          <div className="nav-actions">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main>
        <section className="hero wrap">
          <h1>
            Most trading ideas lose money.
            <br />
            <span className="grad">Know before yours does.</span>
          </h1>
          <p className="lede">
            Describe any strategy in plain English. Cosmu tests it on real prices, with your fees, against pure luck,
            and gives you a straight answer.
          </p>
          <Studio />
        </section>

        <section className="wrap block">
          <h2>Why most traders lose.</h2>
          <div className="pains">
            {PAINS.map((p, i) => (
              <div key={p.pain} className="pain">
                <div className="pain-txt">
                  <span className="pain-n">{String(i + 1).padStart(2, "0")}</span>
                  <h3>{p.pain}</h3>
                  <p>{p.fix}</p>
                </div>
                {p.art}
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <h2>From idea to trade, safely.</h2>
          <p className="h2-sub">The pipeline our first engine ran, June to August 2026.</p>
          <ol className="steps">
            {STEPS.map((x, i) => (
              <li key={x.t} className="step">
                <span className="step-n">{i + 1}</span>
                <h3>{x.t}</h3>
                <p>{x.d}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="wrap block">
          <h2>Any idea. Numbers or news.</h2>
          <div className="kinds">
            <div className="kind">
              <div className="kind-h"><Icon name="trend" size={16} /> Quantitative</div>
              {QUANT.map((q) => <span key={q} className="kind-q">{q}</span>)}
            </div>
            <div className="kind">
              <div className="kind-h"><Icon name="clip" size={16} /> Qualitative</div>
              {QUAL.map((q) => <span key={q} className="kind-q">{q}</span>)}
            </div>
          </div>
        </section>

        <section className="wrap block">
          <div className="end">
            <h2>Stop guessing. Test it first.</h2>
          </div>
        </section>
      </main>

      <footer className="wrap foot">
        <span className="brand-sm"><CosmuMark size={18} /> Cosmu</span>
        <span>Research tool, not investment advice.</span>
      </footer>
    </>
  );
}
