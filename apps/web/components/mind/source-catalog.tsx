// Source catalog — static declarative registry of every alt-data source the engine knows about.
// Sectioned by type, each card shows: name, plain description, PIT/trust note, coverage/staleness,
// key-gated flag (greyed when key absent), and non-causal/control flag shown honestly.
// This is NOT live data — it is the declarative "what sources exist" surface.
// Live freshness and trust scores are in the trust scoreboard above this component.

import { AlertTriangle, CheckCircle, Key, Lock, ShieldOff, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PITHonesty = "clean" | "revision-hazard" | "live-snapshot" | "deterministic";
type KeyGate = "none" | "optional" | "required";

interface SourceEntry {
  name: string;
  provider: string;
  what: string;
  pitNote: string;
  pitHonesty: PITHonesty;
  coverage: string;
  keyGate: KeyGate;
  keyEnvVar?: string;
  nonCausal?: boolean;
  metrics: string[];
}

interface SourceSection {
  id: string;
  label: string;
  description: string;
  sources: SourceEntry[];
}

// ---------------------------------------------------------------------------
// Source definitions — every managed source, one entry each.
// Notes are plain, honest, and match the actual adapter docs.
// ---------------------------------------------------------------------------

const SECTIONS: SourceSection[] = [
  {
    id: "market",
    label: "Market data",
    description: "Price bars, funding rates, open interest, basis, and liquidations — the structural spine of the backtest.",
    sources: [
      {
        name: "funding",
        provider: "Binance",
        what: "Perpetual contract funding rate per symbol. High positive funding = longs pay shorts (bullish crowding). Negative = shorts pay longs.",
        pitNote: "PIT: each funding event timestamped when it settles (every 8 h). Paginated history from Binance. No revision after settlement.",
        pitHonesty: "clean",
        coverage: "BTCUSDT, ETHUSDT and configured perp pairs. History from exchange launch. Daily-or-better update.",
        keyGate: "none",
        metrics: ["funding_rate"],
      },
      {
        name: "open_interest",
        provider: "Binance",
        what: "Total open contracts in USD notional per perp symbol. A proxy for levered positioning and conviction of the crowd.",
        pitNote: "PIT: point-in-time snapshot stamped at fetch time. No gap-filling.",
        pitHonesty: "live-snapshot",
        coverage: "Configured perp symbols. Snapshot only — no deep paginated history.",
        keyGate: "none",
        metrics: ["open_interest"],
      },
      {
        name: "basis",
        provider: "Binance",
        what: "Perp minus spot price differential. Positive basis = premium; negative = discount vs spot.",
        pitNote: "PIT: snapshot per fetch. No look-ahead.",
        pitHonesty: "live-snapshot",
        coverage: "Configured perp/spot pairs.",
        keyGate: "none",
        metrics: ["perp_spot_basis"],
      },
      {
        name: "netflow",
        provider: "Binance",
        what: "Exchange net inflow/outflow of coins. Positive = net deposits (selling pressure); negative = net withdrawals (accumulation signal).",
        pitNote: "PIT: snapshot stamped at fetch time.",
        pitHonesty: "live-snapshot",
        coverage: "Configured symbols. History depth depends on Binance endpoint availability.",
        keyGate: "none",
        metrics: ["exchange_netflow"],
      },
      {
        name: "liquidation_cascade",
        provider: "Binance",
        what: "Forced liquidation volume per symbol (USD). A spike = a cascade unwind — a stress signal for trend continuation or reversal.",
        pitNote: "PIT: each liquidation event is timestamped by the exchange.",
        pitHonesty: "clean",
        coverage: "Configured perp symbols. Real-time event stream, not a daily aggregate.",
        keyGate: "none",
        metrics: ["liquidation_cascade"],
      },
      {
        name: "venue_fees",
        provider: "Binance",
        what: "Maker and taker fee tiers per venue:symbol pair. Used by the backtest to net realistic costs out of every trade.",
        pitNote: "PIT: snapshot of current fee schedule. Fee changes are not retroactively applied to history.",
        pitHonesty: "live-snapshot",
        coverage: "All configured venue:symbol pairs.",
        keyGate: "none",
        metrics: ["venue_fees_maker", "venue_fees_taker"],
      },
    ],
  },
  {
    id: "sentiment",
    label: "Sentiment and social",
    description: "Crowd sentiment, news votes, social volume, and attention signals. All key-gated sources return empty without a key — never fabricated.",
    sources: [
      {
        name: "fear_greed",
        provider: "alternative.me",
        what: "The Alternative.me Crypto Fear and Greed Index — a composite 0–100 score built from volatility, momentum, social volume, and surveys. 0 = extreme fear.",
        pitNote: "PIT: published daily at approximately 00:00 UTC for the previous day. No revision; each day's score is immutable once published.",
        pitHonesty: "clean",
        coverage: "Single market-wide score. Daily history from 2018. Free, no key.",
        keyGate: "none",
        metrics: ["fear_greed"],
      },
      {
        name: "reddit",
        provider: "Reddit (PRAW)",
        what: "Market sentiment score derived from post titles and comments in major crypto subreddits. Distinct from reddit_volume (which counts posts, not scores).",
        pitNote: "PIT: available_at stamped at fetch time. Reddit vote counts drift after publication; early snapshots undercount late-breaking votes.",
        pitHonesty: "live-snapshot",
        coverage: "Crypto subreddits: r/cryptocurrency, r/bitcoin, r/ethfinance, r/wallstreetbets, r/investing. Market-wide score only.",
        keyGate: "required",
        keyEnvVar: "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET",
        metrics: ["reddit_sentiment"],
      },
      {
        name: "reddit_volume",
        provider: "Reddit API v2",
        what: "Daily post and comment count across the same subreddits — a pure attention proxy with no sentiment scoring.",
        pitNote: "PIT: available_at = midnight UTC of day D+1 (a full calendar day must close before it can be counted). Gaps are absent, never zero-filled.",
        pitHonesty: "clean",
        coverage: "Same five subreddits. Market-wide daily counts. History limited by Reddit API. Key required.",
        keyGate: "required",
        keyEnvVar: "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET",
        metrics: ["reddit_post_volume", "reddit_comment_volume"],
      },
      {
        name: "cryptopanic",
        provider: "CryptoPanic",
        what: "Per-coin bullish and bearish vote counts on news posts, aggregated over a 24 h window. A direct measure of crowd news sentiment.",
        pitNote: "PIT: ts = article published_at; available_at = fetch time. Vote counts accumulate over time — early snapshots undercount later votes. Append-only store; never rewrites rows.",
        pitHonesty: "live-snapshot",
        coverage: "Configured crypto symbols. 24 h rolling window. Thin history for new symbols. Key required.",
        keyGate: "required",
        keyEnvVar: "CRYPTOPANIC_API_KEY",
        metrics: ["cryptopanic_bullish_votes", "cryptopanic_bearish_votes"],
      },
      {
        name: "xai",
        provider: "xAI Grok API",
        what: "Twitter/X sentiment derived from xAI's Grok live feed. Two signals: broad crypto sentiment and influencer-weighted sentiment.",
        pitNote: "PIT: market-wide snapshot stamped at fetch time. Available_at = fetch time.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide only. Coverage since xAI API launch. Key required.",
        keyGate: "required",
        keyEnvVar: "XAI_API_KEY",
        metrics: ["twitter_sentiment", "twitter_influencer_sentiment"],
      },
      {
        name: "lunarcrush",
        provider: "LunarCrush",
        what: "Twelve crypto social metrics per coin: social volume, galaxy score, alt rank, sentiment, market dominance, post and contributor counts, and spam flags.",
        pitNote: "PIT: each metric stamped with its API observation time. No revision once stored.",
        pitHonesty: "live-snapshot",
        coverage: "Per configured symbol. Twelve fields fetched in one call per symbol. Key required.",
        keyGate: "required",
        keyEnvVar: "LUNARCRUSH_API_KEY",
        metrics: ["social_volume", "social_sentiment", "galaxy_score", "alt_rank", "social_dominance", "market_dominance", "contributors_active", "posts_active", "spam", "market_cap_usd", "volume_24h_usd", "price_usd"],
      },
      {
        name: "wikipedia",
        provider: "Wikimedia REST API",
        what: "Daily Wikipedia pageview counts for the article matching each crypto entity (e.g. BTCUSDT → 'Bitcoin'). Three derived features: raw count, log count, and 30-day trailing z-score.",
        pitNote: "PIT: available_at = midnight UTC of D+1 (the Wikimedia API publishes day D counts with ~1 day lag). Counts are immutable — Wikimedia never revises historical pageviews. One of the cleanest PIT sources.",
        pitHonesty: "clean",
        coverage: "Per symbol with a known Wikipedia article. 30-day z-score requires 30 days of history. Free, no key. History from 2015.",
        keyGate: "none",
        metrics: ["wiki_pageviews", "wiki_pageviews_log", "wiki_pageviews_zscore"],
      },
    ],
  },
  {
    id: "macro",
    label: "Macro and market-structure",
    description: "FRED macro bundle, financial conditions, cross-asset prices, options market structure, and derivatives sentiment.",
    sources: [
      {
        name: "macro",
        provider: "FRED (Federal Reserve)",
        what: "The FRED macro bundle: VIX level, fed funds rate, DXY dollar index, 2s10s yield curve, high-yield credit spread, macro regime series, and VIX term slope — all memoized so a shared native series is fetched once.",
        pitNote: "PIT: ALFRED initial-release vintages where available — each row carries the value that was first-released on that date, not the retroactively revised value. No look-ahead.",
        pitHonesty: "clean",
        coverage: "Market-wide. Daily FRED series from the 1960s–1980s depending on the series. VIX from 1990.",
        keyGate: "none",
        metrics: ["macro_regime", "vix_level", "fed_funds_rate", "dxy", "yield_curve_2s10s", "credit_spread", "vix_term_slope"],
      },
      {
        name: "macro_extra",
        provider: "FRED (ALFRED)",
        what: "Extended FRED macro: National Financial Conditions Index (NFCI) and initial jobless claims — both pulled as ALFRED initial-release vintages so available_at equals the first-release date, not the revision date.",
        pitNote: "PIT: ALFRED initial-release — each value available_at is the date FRED first published it. No look-ahead from revisions.",
        pitHonesty: "clean",
        coverage: "Market-wide. NFCI from 1973; initial claims from 1967. Weekly series, updated Thursdays.",
        keyGate: "none",
        metrics: ["nfci", "initial_claims"],
      },
      {
        name: "multiasset",
        provider: "Stooq / Yahoo Finance",
        what: "Daily close prices for cross-asset reference series: gold (XAU/USD), silver (XAG/USD), WTI crude, S&P 500, Nasdaq 100, EUR/USD, and USD/JPY.",
        pitNote: "PIT: each daily bar is available at market close of that day. No revision once a day closes (Stooq does not backfill splits for these macro instruments).",
        pitHonesty: "clean",
        coverage: "Market-wide. Daily bars. Long history for equity indexes and FX (30–50+ years). Free, no key.",
        keyGate: "none",
        metrics: ["gold_xau", "silver_xag", "wti_crude", "spx_index", "ndx_index", "eurusd", "usdjpy"],
      },
      {
        name: "putcall",
        provider: "CBOE",
        what: "CBOE equity put/call ratio — a market-wide options sentiment gauge. A high ratio = more puts than calls = investors hedging (bearish lean).",
        pitNote: "PIT: published daily after market close. Market-wide only.",
        pitHonesty: "clean",
        coverage: "Market-wide. US equities options market. Daily, free.",
        keyGate: "none",
        metrics: ["putcall_ratio"],
      },
      {
        name: "dvol",
        provider: "Deribit",
        what: "Deribit DVOL implied volatility index for BTC and ETH — derived from option prices, analogous to the VIX for crypto.",
        pitNote: "PIT: each snapshot stamped at fetch time. Deribit publishes DVOL continuously; we snapshot it daily.",
        pitHonesty: "live-snapshot",
        coverage: "BTC and ETH only. Available from Deribit launch (~2016). Free, no key. EU-accessible.",
        keyGate: "none",
        metrics: ["dvol"],
      },
      {
        name: "defi",
        provider: "DeFiLlama",
        what: "Total Value Locked (TVL) across DeFi protocols — a proxy for on-chain capital deployment and ecosystem health.",
        pitNote: "PIT: daily snapshot from DeFiLlama's public API. Market-wide.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide TVL aggregate. Free, no key. History from 2019.",
        keyGate: "none",
        metrics: ["defi_tvl"],
      },
    ],
  },
  {
    id: "news",
    label: "News and text signals",
    description: "GDELT geopolitical news tone, public RSS headline counts, and LLM-derived index scores. LLM is key-gated and used only at ingest, not at inference.",
    sources: [
      {
        name: "news",
        provider: "GDELT (LLM optional)",
        what: "GDELT headline stream processed into per-symbol sentiment scores and typed event scores (e.g. regulatory, partnership, technical). LLM is used only at ingest for scoring — inference is deterministic thereafter.",
        pitNote: "PIT: each event carries its GDELT publication timestamp. LLM scoring at ingest is flagged; without an LLM key a lexicon fallback is used instead.",
        pitHonesty: "clean",
        coverage: "Per configured symbol. Free, no key for GDELT fetch. LLM key optional (improves scoring).",
        keyGate: "optional",
        keyEnvVar: "OPENROUTER_API_KEY (optional, for LLM event scoring)",
        metrics: ["news_sentiment", "news_event_score"],
      },
      {
        name: "gdelt_tone",
        provider: "GDELT Project",
        what: "Daily aggregate geopolitical news tone from the GDELT dataset — a market-wide 'mood of the world' signal derived from global news coverage.",
        pitNote: "PIT: GDELT updates continuously; our daily aggregate stamps available_at at the close of the UTC day.",
        pitHonesty: "clean",
        coverage: "Market-wide. Keyless, EU-accessible. History from 1979. Daily.",
        keyGate: "none",
        metrics: ["gdelt_tone"],
      },
      {
        name: "rss",
        provider: "Public RSS feeds",
        what: "Count of relevant headlines published in a 24 h trailing window from CoinTelegraph, Decrypt, CoinDesk, and Bitcoin.com. LLM-free — counts only, no scoring.",
        pitNote: "PIT: each item's available_at = its RSS pubDate (the moment the publisher made it public). No revision: RSS feeds are append-only.",
        pitHonesty: "clean",
        coverage: "Market-wide topic counts (crypto, regulation, macro risk). Free, no key. Real-time.",
        keyGate: "none",
        metrics: ["rss_news_count"],
      },
      {
        name: "llm_index",
        provider: "LLM via OpenRouter",
        what: "LLM-derived qualitative-to-quantitative index scores for regulatory risk, risk-on/off climate, and other rubric-anchored dimensions. Each score is a rubric-anchored number the LLM proposes at ingest — inference uses the stored number, not a fresh LLM call.",
        pitNote: "PIT: available_at = fetch time. The LLM's answer is ephemeral at ingest; the stored number is stable. Without a key the provider returns empty — never fabricated.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide index scores. Key required; returns empty without it.",
        keyGate: "required",
        keyEnvVar: "OPENROUTER_API_KEY",
        metrics: ["regulatory_risk_score", "risk_on_off_score"],
      },
    ],
  },
  {
    id: "predictions",
    label: "Prediction markets",
    description: "Real-money prediction market probabilities — the most honest forward-looking signal when a market is liquid.",
    sources: [
      {
        name: "pm_risk_on",
        provider: "Polymarket",
        what: "Implied probability from a specific Polymarket CLOB market designated as a 'risk-on' proxy (configurable via POLYMARKET_TOKEN). Liquid markets reflect genuine probabilistic beliefs.",
        pitNote: "PIT: last-trade probability at fetch time. Market-wide.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide. One configured token. Free API. History from market open.",
        keyGate: "none",
        metrics: ["pm_risk_on"],
      },
      {
        name: "polymarket_clob",
        provider: "Polymarket CLOB",
        what: "Three signals from the Polymarket central-limit order book: implied probability, probability velocity (rate of change), and book depth (liquidity proxy).",
        pitNote: "PIT: snapshot at fetch time for the three order book metrics.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide. Configured token. Free API.",
        keyGate: "none",
        metrics: ["pm_implied_prob", "pm_prob_velocity", "pm_book_depth"],
      },
    ],
  },
  {
    id: "osint",
    label: "OSINT and real-world activity",
    description: "Open-source intelligence feeds tracking physical-world signals. Low confidence — coverage is thin and causal paths are speculative. All require Gate validation.",
    sources: [
      {
        name: "osint",
        provider: "OpenSky Network (live)",
        what: "Live air-traffic snapshot — instantaneous count of unique aircraft in a bounding box. A real-world activity proxy used as a broad geopolitical stress indicator.",
        pitNote: "PIT: available_at = as_of (the moment of the snapshot). Live only; no deep historical archive via this adapter.",
        pitHonesty: "live-snapshot",
        coverage: "Configurable bounding box. Market-wide. No key required for the public anonymous tier. Very thin history.",
        keyGate: "none",
        metrics: ["osint_air_activity"],
      },
      {
        name: "opensky_daily",
        provider: "OpenSky Network (historical)",
        what: "Daily count of unique aircraft (by ICAO-24 code) seen across a UTC day — a global aviation-activity proxy. Distinct from 'osint' which is an instantaneous live snapshot.",
        pitNote: "PIT: available_at = flight_date + 1 day 00:00 UTC. OpenSky publishes historical aggregates with at least a 1-day lag. Gaps are absent, not zero-filled.",
        pitHonesty: "clean",
        coverage: "Market-wide daily count. OpenSky free tier: max ~30-day lookback. History before 2019 may be absent or incomplete. Low confidence (0.10) — thin history, untested on long backtests.",
        keyGate: "none",
        metrics: ["opensky_daily_flights"],
      },
      {
        name: "gtrends",
        provider: "Google Trends (pytrends)",
        what: "Search interest for crypto keywords (0–100 normalised by Google). A retail attention proxy: search spikes often coincide with price extremes.",
        pitNote: "REVISION HAZARD: Google Trends rescales all historical values whenever the query window changes. A score for 2022-09 fetched today may differ from a score fetched in 2022 — look-ahead contamination is real. Available_at = UTC timestamp of the actual fetch, not the week end. Forward-test only until Gate-validated on truly out-of-sample data with a fixed rolling window.",
        pitHonesty: "revision-hazard",
        coverage: "Market-wide. Weekly buckets. History from 2004. Free, no key. Requires pytrends pip package.",
        keyGate: "none",
        metrics: ["gtrends_search_interest"],
      },
    ],
  },
  {
    id: "controls",
    label: "Non-causal controls",
    description: "Sources with no plausible causal path to crypto prices, wired honestly so the Gate can confirm it finds no edge. If a strategy relies on these, that is a data-snooping flag.",
    sources: [
      {
        name: "weather",
        provider: "Open-Meteo Archive",
        what: "A composite 'financial-hub weather stress' scalar (cold + wet + windy) averaged across New York, London, Tokyo, and Shanghai. Wired as a non-causal speculative macro feature to let the Gate falsify it.",
        pitNote: "PIT: available_at = obs_date + 1 day 06:00 UTC (Open-Meteo reanalysis finishes ~06:00 UTC on D+1). Gaps are absent, not zero-filled. Occasional minor revisions from Open-Meteo QC — treated as append-only at ingest.",
        pitHonesty: "clean",
        coverage: "Market-wide daily composite. Free, no key. Archive from approximately 2015.",
        keyGate: "none",
        nonCausal: true,
        metrics: ["weather_hub_stress"],
      },
      {
        name: "astro",
        provider: "Stdlib (closed-form math)",
        what: "Deterministic lunar and planetary ephemeris: lunar phase fraction, Sun ecliptic longitude (season proxy), Jupiter longitude (~12-year cycle), Saturn longitude (~29-year cycle), and Sun–Jupiter angular separation. Pure stdlib math — no network, no key.",
        pitNote: "PIT: available_at = midnight UTC of the day (the geometry is knowable at the start of any calendar day — deterministic, no revision, no look-ahead). Computable for any date from 1000–3000 CE.",
        pitHonesty: "deterministic",
        coverage: "Market-wide. Any date, instant computation, no staleness possible.",
        keyGate: "none",
        nonCausal: true,
        metrics: ["astro_lunar_phase", "astro_sun_longitude", "astro_jupiter_longitude", "astro_saturn_longitude", "astro_sun_jupiter_aspect"],
      },
      {
        name: "exotic_controls",
        provider: "USGS + NOAA",
        what: "Two geophysical series: USGS earthquake count and maximum magnitude (past 24 h), and NOAA planetary Kp index (geomagnetic storm intensity). Purposely chosen because they carry zero plausible causal path to crypto prices.",
        pitNote: "PIT: available_at = as_of (live snapshot at fetch time). USGS revises magnitudes retrospectively — treat as live-revised. NOAA Kp is 'estimated' at publication; definitive values arrive later.",
        pitHonesty: "live-snapshot",
        coverage: "Market-wide daily. Free, no key. USGS 'all day' feed: last 24 h only. NOAA Kp: recent history.",
        keyGate: "none",
        nonCausal: true,
        metrics: ["usgs_earthquake_count", "usgs_max_magnitude", "noaa_kp_index"],
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// PIT honesty badge
// ---------------------------------------------------------------------------

const PIT_LABELS: Record<PITHonesty, { label: string; variant: "up" | "warn" | "iris" | "muted" }> = {
  clean: { label: "PIT clean", variant: "up" },
  "revision-hazard": { label: "revision hazard", variant: "warn" },
  "live-snapshot": { label: "live snapshot", variant: "iris" },
  deterministic: { label: "deterministic", variant: "up" },
};

// ---------------------------------------------------------------------------
// Source card
// ---------------------------------------------------------------------------

function SourceCard({ s }: { s: SourceEntry }) {
  const keyGated = s.keyGate === "required";
  const keyOptional = s.keyGate === "optional";
  const pit = PIT_LABELS[s.pitHonesty];

  return (
    <div
      className={cn(
        "rounded-lg border border-border/50 bg-surface-2/10 p-4 space-y-3 transition-colors hover:bg-surface-2/20",
        keyGated && "opacity-70"
      )}
    >
      {/* Header row */}
      <div className="flex flex-wrap items-start gap-2">
        <span className="font-mono text-[12.5px] font-semibold text-foreground leading-none mt-0.5">
          {s.name}
        </span>
        <div className="flex flex-wrap items-center gap-1.5 ml-auto">
          {s.nonCausal && (
            <Badge variant="warn" className="text-[9.5px]">
              <ShieldOff className="size-2.5" /> non-causal control
            </Badge>
          )}
          {pit && (
            <Badge variant={pit.variant} className="text-[9.5px]">
              {pit.label}
            </Badge>
          )}
          {keyGated ? (
            <Badge variant="muted" className="text-[9.5px]">
              <Lock className="size-2.5" /> key required
            </Badge>
          ) : keyOptional ? (
            <Badge variant="iris" className="text-[9.5px]">
              <Key className="size-2.5" /> key optional
            </Badge>
          ) : (
            <Badge variant="up" className="text-[9.5px]">
              <CheckCircle className="size-2.5" /> free
            </Badge>
          )}
        </div>
      </div>

      {/* Provider */}
      <div className="text-[10.5px] text-quiet uppercase tracking-[0.06em]">{s.provider}</div>

      {/* What it is */}
      <p className="text-[12px] leading-relaxed text-muted">{s.what}</p>

      {/* PIT / trust note */}
      <div
        className={cn(
          "rounded-md border px-2.5 py-1.5 text-[11px] leading-relaxed",
          s.pitHonesty === "revision-hazard"
            ? "border-warn/30 bg-warn/[0.04] text-warn"
            : s.nonCausal
            ? "border-warn/20 bg-warn/[0.03] text-muted"
            : "border-border/40 bg-background/40 text-muted"
        )}
      >
        {s.pitHonesty === "revision-hazard" && (
          <AlertTriangle className="mb-0.5 mr-1 inline size-3 shrink-0 align-middle" />
        )}
        {s.nonCausal && (
          <ShieldOff className="mb-0.5 mr-1 inline size-3 shrink-0 align-middle text-warn/70" />
        )}
        {s.pitNote}
      </div>

      {/* Coverage */}
      <div className="space-y-0.5">
        <div className="text-[10px] uppercase tracking-[0.06em] text-quiet">Coverage</div>
        <div className="text-[11.5px] leading-relaxed text-muted">{s.coverage}</div>
      </div>

      {/* Key env var */}
      {s.keyEnvVar && (
        <div className="flex items-center gap-1.5 text-[10.5px] text-quiet">
          <Key className="size-3 shrink-0" />
          <code className="font-mono text-iris-soft">{s.keyEnvVar}</code>
        </div>
      )}

      {/* Metrics chips */}
      <div className="flex flex-wrap gap-1">
        {s.metrics.map((m) => (
          <span
            key={m}
            className="rounded border border-border/40 bg-background/40 px-1.5 font-mono text-[9.5px] text-quiet"
          >
            {m}
          </span>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section
// ---------------------------------------------------------------------------

function CatalogSection({ section }: { section: SourceSection }) {
  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-[13px] font-semibold text-foreground">{section.label}</h3>
        <p className="mt-0.5 text-[11.5px] leading-relaxed text-muted">{section.description}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {section.sources.map((s) => (
          <SourceCard key={s.name} s={s} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function SourceCatalog() {
  const totalSources = SECTIONS.reduce((n, s) => n + s.sources.length, 0);
  const freeCount = SECTIONS.flatMap((s) => s.sources).filter((s) => s.keyGate === "none").length;
  const keyGatedCount = SECTIONS.flatMap((s) => s.sources).filter((s) => s.keyGate === "required").length;
  const nonCausalCount = SECTIONS.flatMap((s) => s.sources).filter((s) => s.nonCausal).length;

  return (
    <div className="space-y-8">
      {/* Summary row */}
      <div className="flex flex-wrap gap-3">
        <Badge variant="muted">
          <Zap className="size-3" /> {totalSources} sources registered
        </Badge>
        <Badge variant="up">
          <CheckCircle className="size-3" /> {freeCount} free / no key
        </Badge>
        <Badge variant="muted">
          <Lock className="size-3" /> {keyGatedCount} key-gated
        </Badge>
        <Badge variant="warn">
          <ShieldOff className="size-3" /> {nonCausalCount} non-causal controls
        </Badge>
      </div>

      {SECTIONS.map((section) => (
        <CatalogSection key={section.id} section={section} />
      ))}

      {/* Honest footer */}
      <p className="border-t border-border/30 pt-4 text-[11px] leading-relaxed text-quiet">
        This catalog is the static declarative registry — it describes what sources are wired, not live
        freshness or trust scores. Live data appears in the trust scoreboard above. Sources shown greyed
        require an API key; without it the engine returns empty data for that source and the Gate runs
        without it. Non-causal controls are wired honestly so the Gate can falsify them — if a strategy
        relies on weather or lunar phase, treat that as a data-snooping flag.
      </p>
    </div>
  );
}
