// intent: the Cosmu landing page — lean and pain-first. Hero (pain + live demo) → why traders lose and how
//   Cosmu fixes each cause → how it works (the engine's real pipeline) → any idea, numbers or news → CTA. Market numbers come from lib/showcase.json;
//   the "+89% before costs" figure comes from the archived engine's reports (archive/docs/reports).

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Studio } from "@/components/studio";
import { Icon } from "@/components/icon";
import { VerdictBadge } from "@/components/verdict-badge";
import { SITE } from "@/lib/site";
import { IDEAS, STOCK_PLATFORMS, TESTED, pct, results, verdict } from "@/lib/showcase";

const GH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

const NVDA = IDEAS.find((i) => i.key === "ai_nvda") ?? IDEAS[0];
const rN = results(NVDA, STOCK_PLATFORMS[0]);
const PASSED = TESTED.filter((t) => t.pass).length;

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
        <div><span>Before costs</span><i className="p-track"><i style={{ width: "89%" }} /></i><em className="up">+89%</em></div>
        <div><span>After costs</span><i className="p-track" /><em className="dn">below 0</em></div>
        <small>A real strategy family from our own research.</small>
      </div>
    ),
  },
  {
    pain: "Luck looks like skill.",
    fix: "Every idea is checked against 10,000 random entry dates. Most fail. You only act on the few that don't.",
    art: (
      <div className="p-art p-dots">
        <div className="dotgrid" aria-hidden>
          {TESTED.map((t) => (
            <i key={t.key} className={t.pass ? "p" : t.promising ? "m" : ""} title={t.q} />
          ))}
        </div>
        <small>
          <b>{TESTED.length}</b> ideas tested · <b className="up">{PASSED}</b> passed
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
            <a className="btn btn-sm" href={SITE.repo} target="_blank" rel="noreferrer">
              {GH} GitHub
            </a>
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
            <a className="btn btn-primary" href={SITE.repo} target="_blank" rel="noreferrer">
              {GH} View on GitHub
            </a>
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
