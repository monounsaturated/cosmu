// intent: the Cosmu landing page — what it does (live demo on real data), how it decides, what was built.

import { CosmuMark } from "@/components/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { HeroDemo } from "@/components/hero-demo";
import { NewsImpact } from "@/components/news-impact";
import { FeeLab } from "@/components/fee-lab";
import { Pipeline } from "@/components/pipeline";
import { Reveal } from "@/components/reveal";
import { DEMO } from "@/lib/demo";
import { FACTS, SITE } from "@/lib/site";

const GH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
    <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.5-3.9-1.5-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
  </svg>
);

const TIMELINE = [
  { d: "2026-04-10", c: "var(--quiet)", t: "First commit", chip: null, p: "FastAPI engine, typed strategy spec, TypeScript types generated from the API." },
  { d: "2026-06-03", c: "var(--iris)", t: "Autonomous loop on real data", chip: null, p: "Every 4h: ingest → author → backtest → gate → fund a sim track. Real Binance bars, 11+ point-in-time sources." },
  { d: "2026-06-04", c: "var(--down)", t: "Crypto funding-carry: killed", chip: ["dn", "failed the gate"], p: "Pass criteria written before the run. Best deflated Sharpe 0.43 vs a 0.95 bar. Dropped, not tuned until it passed." },
  { d: "2026-06-14", c: "var(--up)", t: "First strategies pass the full gate", chip: ["up", "3 passed"], p: "Defensive asset-rotation strategies (DAA, VAA, ADM) cleared the unchanged bar and beat buy & hold." },
  { d: "2026-06-16", c: "var(--iris)", t: "First real order routed", chip: ["iris", "broker paper API"], p: "A gate-passed order went through all 5 interlocks to Alpaca's paper API. It exposed a booking bug, which was fixed." },
  { d: "2026-07-06", c: "var(--quiet)", t: "Sub-hour strategies + maker lane", chip: null, p: "60 higher-frequency strategies, with fee modelling honest to the maker/taker split." },
];

const STACK = [
  ["Engine", "Python 3.12 · FastAPI · Pydantic"],
  ["Web", "Next.js · React 19 · hand-written CSS"],
  ["Data", "Postgres · pgvector · point-in-time store"],
  ["Compute", "Modal, scale-to-zero, for sweeps + ML"],
  ["LLMs", "OpenRouter gateway, propose-only"],
  ["Venues", "Binance · Alpaca · Polymarket · Kraken · IBKR"],
];

export default function Page() {
  const st = DEMO.stats;
  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <a href="#" className="brand">
            <CosmuMark size={26} /> Cosmu
          </a>
          <nav className="nav-links" aria-label="Sections">
            <a href="#features">Features</a>
            <a href="#impact">News impact</a>
            <a href="#gate">How it decides</a>
            <a href="#built">What I built</a>
          </nav>
          <div className="nav-actions">
            <ThemeToggle />
            <a className="btn btn-sm" href={SITE.repo} target="_blank" rel="noreferrer">
              {GH} Code
            </a>
          </div>
        </div>
      </header>

      <main className="wrap">
        {/* ── hero ── */}
        <div className="hero">
          <span className="chip iris">
            <span className="dot pulse" /> Quant research engine · built in {FACTS.days} days
          </span>
          <h1>
            Ask a trading question. <span className="grad">Get an honest answer.</span>
          </h1>
          <p className="lede">
            Cosmu turns plain English into a testable strategy, backtests it on real prices and real news net of
            every fee, and lets statistics, not the AI, decide whether the edge is real.
          </p>
          <div className="hero-ctas">
            <a className="btn btn-primary" href="#impact">Explore the data</a>
            <a className="btn" href="#built">See what I built</a>
          </div>
          <div className="hero-meta">
            <span><b>{FACTS.prs}</b> merged PRs</span>
            <span><b>{FACTS.tests.toLocaleString("en-US")}</b> tests</span>
            <span><b>{FACTS.pyLines}</b> lines of Python</span>
            <span><b>0</b> synthetic numbers on this page</span>
          </div>
          <HeroDemo />
        </div>

        {/* ── features ── */}
        <section id="features">
          <Reveal className="sec-head">
            <div className="eyebrow"><span className="n">01</span> What it does</div>
            <h2>Two questions every trader asks, answered with data.</h2>
          </Reveal>
          <div className="bento">
            <Reveal className="cell feat span-6">
              <span className="num">A · natural language → backtest</span>
              <h3>&ldquo;What if I had…&rdquo;, tested in seconds.</h3>
              <p>
                Describe an idea the way you&apos;d say it out loud. An LLM drafts a typed strategy. A compiler
                rejects anything vague, magic-numbered, or able to see the future. Then it runs.
              </p>
              <ul>
                <li>Every rule has a stated reason and fitted thresholds, not hand-picked ones</li>
                <li>Imports TradingView Pine scripts; next step is plugging into MetaTrader 5 and existing backtest engines</li>
                <li>Results are net of commission, FX and slippage for the platform you pick</li>
              </ul>
            </Reveal>
            <Reveal className="cell feat span-6" delay={80}>
              <span className="num">B · news → price impact</span>
              <h3>Did the headline actually move the price?</h3>
              <p>
                Headlines, press and social posts become dated, point-in-time events. Each one is lined up with
                what the price did next, and compared with an ordinary day.
              </p>
              <ul>
                <li>Sources wired: GDELT news, Reddit, X/Twitter, Polymarket odds, FRED macro, on-chain flows</li>
                <li>Signals are only used at the moment they were public, so the backtest never sees the future</li>
                <li>Every effect is tested against random dates: luck gets named as luck</li>
              </ul>
            </Reveal>
          </div>
        </section>

        {/* ── news impact ── */}
        <section id="impact">
          <Reveal className="sec-head">
            <div className="eyebrow"><span className="n">02</span> Real example · {DEMO.window[0].slice(0, 4)}–{DEMO.window[1].slice(0, 4)}</div>
            <h2>{st.trades} major hacks. What did cybersecurity stocks do next?</h2>
            <p className="lede">
              Every point is a real headline, placed on the first trading day after it broke. Prices are real
              {" "}{DEMO.asset} closes, dividends included.
            </p>
          </Reveal>
          <Reveal>
            <NewsImpact />
          </Reveal>
        </section>

        {/* ── costs ── */}
        <section id="costs">
          <Reveal className="sec-head">
            <div className="eyebrow"><span className="n">03</span> Costs are part of the strategy</div>
            <h2>Same trades, different platform, different result.</h2>
            <p className="lede">
              Small edges live or die on fees. Pick where you&apos;d place the {st.trades} orders and the
              backtest re-prices every one.
            </p>
          </Reveal>
          <Reveal>
            <FeeLab />
          </Reveal>
        </section>

        {/* ── gate ── */}
        <section id="gate">
          <Reveal className="sec-head">
            <div className="eyebrow"><span className="n">04</span> How it decides</div>
            <h2>The AI can propose. It can never fund.</h2>
            <p className="lede">
              LLMs are good at ideas and bad at telling luck from skill. So every idea passes through a fixed
              statistical gate written in code, and real money needs five independent switches all on.
            </p>
          </Reveal>
          <Reveal>
            <Pipeline />
          </Reveal>
        </section>

        {/* ── built ── */}
        <section id="built">
          <Reveal className="sec-head">
            <div className="eyebrow"><span className="n">05</span> What I built</div>
            <h2>One person, a team of AI agents, {FACTS.days} days.</h2>
            <p className="lede">
              A full autonomous research engine and trading cockpit, built by directing parallel coding agents,
              each on its own branch, merged through a review train.
            </p>
          </Reveal>

          <div className="bento">
            {[
              [FACTS.prs.toString(), "merged pull requests", `${FACTS.commits.toLocaleString("en-US")} commits`],
              [FACTS.tests.toLocaleString("en-US"), "automated tests", "offline, no API keys needed"],
              [FACTS.specs.toString(), "strategy specs authored", "each checked by the real compiler"],
              [FACTS.skills.toString(), "agent playbooks", "runnable skills for every recurring task"],
            ].map(([v, l, d], i) => (
              <Reveal key={l} className="cell stat span-3" delay={i * 60}>
                <div className="cell-label">{l}</div>
                <div className="v">{v}</div>
                <div className="d">{d}</div>
              </Reveal>
            ))}

            <Reveal className="cell span-7">
              <div className="cell-label" style={{ marginBottom: 18 }}>Milestones · 2026 · including the failures</div>
              <div className="tl">
                {TIMELINE.map((m) => (
                  <div key={m.d} className="tl-item">
                    <div className="tl-date">{m.d.slice(5).replace("-", "/")}</div>
                    <div className="tl-rail"><i style={{ background: m.c }} /></div>
                    <div className="tl-body">
                      <h4>
                        {m.t}
                        {m.chip && <span className={`chip ${m.chip[0]}`}>{m.chip[1]}</span>}
                      </h4>
                      <p>{m.p}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Reveal>

            <Reveal className="cell span-5" delay={80}>
              <div className="cell-label">Architecture</div>
              <div className="stack" style={{ gridTemplateColumns: "1fr 1fr" }}>
                {STACK.map(([n, w]) => (
                  <div key={n} className="layer">
                    <div className="n">{n}</div>
                    <div className="w">{w}</div>
                  </div>
                ))}
              </div>
              <div className="cell-label" style={{ marginTop: 22 }}>Rules the design enforces</div>
              <ul style={{ listStyle: "none", display: "grid", gap: 8, marginTop: 12, fontSize: 13 }} className="muted">
                <li>✓ Signal and fill stored as separate records</li>
                <li>✓ Dead strategies stay visible (no survivor bias)</li>
                <li>✓ Live trading off by default, per-strategy caps</li>
                <li>✓ No martingale, no revenge sizing, no pooled wallet</li>
              </ul>
            </Reveal>
          </div>
        </section>

        {/* ── end ── */}
        <Reveal className="cell cta-end">
          <h2>Most trading ideas don&apos;t survive contact with data.</h2>
          <p className="lede">Cosmu was built to find that out quickly, cheaply, and honestly.</p>
          <div className="hero-ctas">
            <a className="btn btn-primary" href={SITE.repo} target="_blank" rel="noreferrer">{GH} Read the code</a>
            <a className="btn" href={SITE.contact} target="_blank" rel="noreferrer">Get in touch</a>
          </div>
        </Reveal>

        <footer>
          <span>
            <b style={{ color: "var(--fg)" }}>Cosmu</b> · research project, not investment advice.
          </span>
          <span>
            Data: {DEMO.source} Fee schedules: published retail rates, 2025.
          </span>
        </footer>
      </main>
    </>
  );
}
