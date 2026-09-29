// intent: the Cosmu landing page — a hero you can play with, a scenario gallery, how it fits a trader's
//   routine, why to trust it, one CTA. Every number shown is computed from lib/showcase.json.

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Studio } from "@/components/studio";
import { Gallery } from "@/components/gallery";
import { Icon } from "@/components/icon";
import { SITE } from "@/lib/site";
import { IDEAS, STOCK_PLATFORMS, holdWords, pct, results } from "@/lib/showcase";

const GH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

// Real numbers for the workflow mock-ups.
const byKey = (k: string) => IDEAS.find((i) => i.key === k) ?? IDEAS[0];
const LAYOFF = byKey("spike_layoffs_QQQ");
const STORM = byKey("spike_hurricane_GNRC");
const NVDA = byKey("ai_nvda");
const rL = results(LAYOFF, STOCK_PLATFORMS[0]);
const rS = results(STORM, STOCK_PLATFORMS[0]);
const rN = results(NVDA, STOCK_PLATFORMS[0]);

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
    d: "Every matching headline, real prices, your broker's fees.",
    art: (
      <div className="how-art art-steps">
        {["News found", "Prices pulled", "Backtest run", "Luck checked"].map((x) => (
          <span key={x}><b>✓</b> {x}</span>
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
        <b className="up">{pct(rN.avg)}</b>
        <span className="pill">Better than random</span>
      </div>
    ),
  },
];

const TRUST = [
  { i: "clock", t: "No hindsight", d: "Trades only on news that was already public." },
  { i: "fees", t: "Your real fees", d: "Your broker's costs, on every single trade." },
  { i: "dice", t: "Luck test", d: "10,000 random dates, every time." },
  { i: "shield", t: "Math decides", d: "The AI runs the tests. It never grades itself." },
  { i: "spark", t: "No code", d: "No spreadsheets, no scripts, no data wrangling." },
  { i: "users", t: "Every source", d: "Worldwide news, social media, macro data, crypto sentiment." },
];

const VENUES = ["Interactive Brokers", "Trade Republic", "DEGIRO", "XTB", "Binance", "Kraken", "TradingView"];

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
        </section>

        <section className="wrap block">
          <h2>Pick a scenario.</h2>
          <p className="sub">Big events or everyday news spikes. Click one to open it above.</p>
          <Gallery />
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
          <h2>Fits the way you trade.</h2>
          <div className="flow">
            <div className="flow-card">
              <div className="flow-art">
                <div className="paste">
                  <Icon name="clip" size={14} /> &ldquo;Big Tech announces another round of layoffs&rdquo;
                </div>
                <div className="answer">
                  <span className="a-l">Last {LAYOFF.trades.length} times, the Nasdaq in {holdWords(LAYOFF.hold_days)}</span>
                  <span className="a-v">
                    <b className="up">{pct(rL.avg)}</b> · {rL.wins} of {LAYOFF.trades.length} up
                  </span>
                </div>
              </div>
              <h3>Check before you click buy</h3>
              <p>Paste the headline you just read. See what happened every time before.</p>
            </div>

            <div className="flow-card">
              <div className="flow-art">
                <div className="notif">
                  <span className="n-icon"><Icon name="bell" size={16} /></span>
                  <div>
                    <div className="n-head"><b>Cosmu</b><span>now</span></div>
                    <div className="n-title">Hurricane news is spiking</div>
                    <div className="n-body">
                      Last {STORM.trades.length} times, Generac made {pct(rS.avg)} within {holdWords(STORM.hold_days)}. {rS.wins} of {STORM.trades.length} were up.
                    </div>
                  </div>
                </div>
              </div>
              <h3>Get pinged when it happens again</h3>
              <p>Save an idea. Cosmu watches the news and alerts you the moment it fires.</p>
            </div>

            <div className="flow-card">
              <div className="flow-art venues">
                {VENUES.map((v) => (
                  <span key={v}>{v}</span>
                ))}
              </div>
              <h3>Works where you already trade</h3>
              <p>Your broker&apos;s real fees. Charts and alerts in the tools you use.</p>
            </div>
          </div>
        </section>

        <section className="wrap block">
          <h2>Honest by design.</h2>
          <div className="guards">
            {TRUST.map((g) => (
              <div key={g.t} className="guard">
                <span className="g-icon2"><Icon name={g.i} size={18} /></span>
                <h3>{g.t}</h3>
                <p>{g.d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <div className="end">
            <h2>Stop guessing. Test the headline.</h2>
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
