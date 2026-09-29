// intent: the Cosmu landing page — a hero you can play with, how it fits a trader's routine, the story of
//   how it came to be, why to trust it, one CTA. Market numbers come from lib/showcase.json; the story's
//   numbers come from the archived engine's reports (archive/docs/reports).

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { Studio } from "@/components/studio";
import { Icon } from "@/components/icon";
import { VerdictBadge } from "@/components/verdict-badge";
import { SITE } from "@/lib/site";
import { CRYPTO_PLATFORMS, IDEAS, RULE, STOCK_PLATFORMS, TESTED, holdWords, pct, results, verdict } from "@/lib/showcase";

const GH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

// Real numbers for the workflow mock-ups.
const byKey = (k: string) => IDEAS.find((i) => i.key === k) ?? IDEAS[0];
const LAYOFF = byKey("spike_layoffs_QQQ");
const NVDA = byKey("ai_nvda");
const rL = results(LAYOFF, STOCK_PLATFORMS[0]);
const rN = results(NVDA, STOCK_PLATFORMS[0]);
const PASSED = TESTED.filter((t) => t.pass).length;
const PROMISING = TESTED.filter((t) => t.promising).length;

// The story: from a trading robot to an honest judge. Figures from archive/docs/reports.
const STORY = [
  {
    k: "The idea",
    t: "A robot that trades on its own.",
    d: "Software wrote hundreds of strategies, backtested them and paper-traded the survivors every day, chasing the next 100×.",
    art: (
      <div className="st-art">
        <b>400+</b>
        <span>strategies written and tested</span>
      </div>
    ),
  },
  {
    k: "The test",
    t: "A strict judge said no.",
    d: "Every idea had to beat luck after real fees. One family made up to +89% before costs. Costs took more than all of it.",
    art: (
      <div className="st-art st-bars">
        <div><span>Before costs</span><i className="st-track"><i className="st-up" style={{ width: "89%" }} /></i><em className="up">+89%</em></div>
        <div><span>After costs</span><i className="st-track" /><em className="dn">below 0</em></div>
      </div>
    ),
  },
  {
    k: "The product",
    t: "The judge was the valuable part.",
    d: "So Cosmu puts that judge in front of every trader: an honest answer before they risk a cent.",
    art: (
      <div className="st-art">
        <div className="st-dots" aria-hidden>
          {TESTED.map((t) => (
            <i key={t.key} className={t.pass ? "p" : t.promising ? "m" : ""} title={t.q} />
          ))}
        </div>
        <span>{TESTED.length} ideas tested · {PASSED} passed · {PROMISING} promising</span>
      </div>
    ),
  },
];

const TRUST = [
  { i: "clock", t: "No hindsight", d: "Buys only after the news was public, at the next close." },
  { i: "fees", t: "Your real fees", d: "Every trade pays your broker's commission, currency fee and spread." },
  { i: "dice", t: "Luck test", d: `Compared with 10,000 random dates from the same years. To pass: ${RULE.min_n}+ events, better than ${Math.round(RULE.pass * 100)}% of them.` },
  { i: "shield", t: "Math decides", d: "The verdict comes from statistics, never from an AI's opinion." },
  { i: "spark", t: "Plain words", d: "Ask like you'd text a friend. No spreadsheets, no code." },
  { i: "clip", t: "Failures included", d: "Every idea tested stays on the record, not just the winners." },
]

const VENUES = ["Interactive Brokers", "Trade Republic", "DEGIRO", "XTB", "Binance", "Kraken"];

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
          <span className="badge"><i /> Early preview</span>
          <h1>
            Turn any headline
            <br />
            <span className="grad">into a backtest.</span>
          </h1>
          <p className="lede">Ask in plain English. Cosmu finds the news, tests it on real prices, and tells you if it would have made money.</p>
          <Studio />
          <div className="proof">
            <span><b>{TESTED.length}</b> ideas tested</span>
            <span><b>6 years</b> of daily prices</span>
            <span><b>10,000</b> random dates per verdict</span>
            <span><b>{STOCK_PLATFORMS.length + CRYPTO_PLATFORMS.length}</b> platforms&apos; real fees</span>
          </div>
        </section>

        <section className="wrap block">
          <h2>Fits the way you trade.</h2>
          <div className="flow">
            <div className="flow-card">
              <div className="flow-art">
                <div className="paste">
                  <Icon name="spark" size={14} /> Big AI model launched today. Buy Nvidia?
                </div>
                <div className="answer">
                  <span className="a-l">Last {NVDA.trades.length} launches · Nvidia 1 month later</span>
                  <span className="a-v">
                    <b className="up">{pct(rN.avg)}</b> vs {pct(rN.randomMonth)} on a random month
                  </span>
                  <VerdictBadge v={verdict(NVDA)} />
                </div>
              </div>
              <h3>Check before you click buy</h3>
              <p>Ask about the headline you just read. See what really happened every time before.</p>
            </div>

            <div className="flow-card">
              <div className="flow-art">
                <div className="notif">
                  <span className="n-icon"><Icon name="bell" size={16} /></span>
                  <div>
                    <div className="n-head"><b>Cosmu</b><span>now</span></div>
                    <div className="n-title">Layoff news is spiking</div>
                    <div className="n-body">
                      Last {LAYOFF.trades.length} times, the Nasdaq averaged {pct(rL.avg)} over {holdWords(LAYOFF.hold_days)}.
                    </div>
                    <VerdictBadge v={verdict(LAYOFF)} />
                  </div>
                </div>
              </div>
              <h3>Get pinged when it happens again <span className="soon">Soon</span></h3>
              <p>Save an idea that passed. Cosmu watches the news and tells you when it fires.</p>
            </div>

            <div className="flow-card">
              <div className="flow-art venues">
                {VENUES.map((v) => (
                  <span key={v}>{v}</span>
                ))}
              </div>
              <h3>Your broker&apos;s fees, built in</h3>
              <p>Pick where you trade. Every result is net of its real costs.</p>
            </div>
          </div>
        </section>

        <section className="wrap block">
          <h2>Built on a hard lesson.</h2>
          <div className="story">
            {STORY.map((x, i) => (
              <div key={x.k} className="st-card">
                {x.art}
                <div className="st-k"><span>{String(i + 1).padStart(2, "0")}</span> {x.k}</div>
                <h3>{x.t}</h3>
                <p>{x.d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <h2>Honest by design.</h2>
          <div className="guards">
            {TRUST.map((g) => (
              <div key={g.t} className="guard">
                <h3><span className="g-icon"><Icon name={g.i} size={16} /></span>{g.t}</h3>
                <p>{g.d}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="wrap block">
          <div className="end">
            <div>
              <h2>Stop guessing. Test the headline.</h2>
              <p className="end-sub">See exactly how every number on this page is made.</p>
            </div>
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
