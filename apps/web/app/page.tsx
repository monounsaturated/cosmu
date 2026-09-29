// intent: the Cosmu landing page — a hero you can play with, three steps, four guardrails, one CTA.

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Studio } from "@/components/studio";
import { SITE } from "@/lib/site";
import { IDEAS, STOCK_PLATFORMS, pct, results } from "@/lib/showcase";

const SAMPLE = results(IDEAS[0], STOCK_PLATFORMS[0]).avg;

const GH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

const HOW = [
  {
    n: "1",
    t: "Ask",
    d: "Type an idea the way you'd say it.",
    art: (
      <div className="how-art art-ask">
        <span>Buy gold when…</span>
      </div>
    ),
  },
  {
    n: "2",
    t: "Cosmu tests it",
    d: "Every matching headline, real prices, your tools.",
    art: (
      <div className="how-art art-tools">
        {["MetaTrader 5", "TradingView", "Interactive Brokers", "Binance"].map((x) => (
          <span key={x}>{x}</span>
        ))}
      </div>
    ),
  },
  {
    n: "3",
    t: "You get the answer",
    d: "Profit after fees, and whether it beats luck.",
    art: (
      <div className="how-art art-answer">
        <b className="up">{pct(SAMPLE)}</b>
        <span className="pill">Better than random</span>
      </div>
    ),
  },
];

const GUARDS = [
  { i: "M12 8v5l3 2M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", t: "No hindsight", d: "Trades only on news that was already public." },
  { i: "M4 7h16M4 12h10M4 17h7", t: "Real fees", d: "Your broker's costs, on every single trade." },
  { i: "M4 20V10M10 20V4M16 20v-7M22 20H2", t: "Luck test", d: "10,000 random dates, every time." },
  { i: "M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z", t: "Math decides", d: "The AI runs the tests. It never grades itself." },
];

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
            Turn any headline
            <br />
            <span className="grad">into a backtest.</span>
          </h1>
          <p className="lede">Ask in plain English. Cosmu finds the news, tests it on real prices, and tells you if it would have made money.</p>
          <Studio />
          <p className="fine">Real daily prices, 2020–2025. Past results don&apos;t predict future ones.</p>
        </section>

        <section className="wrap block">
          <h2>As simple as asking.</h2>
          <div className="how">
            {HOW.map((h) => (
              <div key={h.n} className="how-card">
                {h.art}
                <div className="how-txt">
                  <span className="how-n">{h.n}</span>
                  <div>
                    <h3>{h.t}</h3>
                    <p>{h.d}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <h2>Honest by design.</h2>
          <div className="guards">
            {GUARDS.map((g) => (
              <div key={g.t} className="guard">
                <span className="g-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d={g.i} />
                  </svg>
                </span>
                <h3>{g.t}</h3>
                <p>{g.d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <div className="end">
            <h2>Your next idea, tested in seconds.</h2>
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
