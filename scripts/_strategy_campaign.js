export const meta = {
  name: 'hidden-edge-campaign',
  description: 'Web-grounded research across hedge-fund-blindspot themes → author 25 diverse, valid, gate-testable StrategySpecs (each with a disconfirmer)',
  phases: [
    { title: 'Research', detail: 'parallel web+data research across 6 hidden-edge themes' },
    { title: 'Author', detail: 'turn each gate-testable hypothesis into a self-validated StrategySpec' },
  ],
}

// ---- shared context handed to every agent (the gate-testable reality) ----
const CONTEXT = `
COSMU is an autonomous crypto/equity quant. A deterministic Gate (deflated-Sharpe + BH-FDR + purged holdout, NET of real fees) disposes; the LLM only PROPOSES. We are hunting edges HEDGE FUNDS CANNOT TAKE: small/low-capacity markets, un-quantified or un-automated data an LLM can bridge, hidden cross-domain correlations. NOT HFT, NOT infra-heavy, NOT latency. Profit on hidden/slow signals.

TRADABLE UNIVERSE (a spec can ONLY trade these):
- crypto spot (Binance): BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT (long-only — NO shorts on spot)
- equity (daily): SPY QQQ + sector ETFs XLE XLF XLK XLV XLY XLP XLU XLI XLB

GATE-TESTABLE FEATURES (have real PIT data NOW — a spec must use these). Each tagged BOUNDED (a fitted level threshold genuinely binds) or DRIFTING (raw level is an always-true/false TRAP — use ONLY via cross_up/cross_down, or prefer a bounded feature instead):
  crypto-usable:
    fear_greed [BOUNDED 0-100] · vix_level [BOUNDED ~10-80] · vix_term_slope [BOUNDED] · dxy [BOUNDED-ish range] · macro_regime [BOUNDED composite] · funding_rate [BOUNDED ~±0.01] · pm_risk_on [BOUNDED 0-1] · rsi [BOUNDED 0-100] · adx [BOUNDED] · bb_z [BOUNDED z-score] · vol_realized [BOUNDED-ish] · ret_Nd [return, signed] · atr [scale] · defi_tvl [DRIFTING] · dvol [BOUNDED, BTC/ETH only, THIN history]
  equity-only (use for SPY/QQQ/sector specs): credit_spread [BOUNDED, +IC in scan!] · yield_curve_2s10s [BOUNDED ~-1..3] · putcall_ratio [BOUNDED] · vix_level · dxy · macro_regime
  prediction-market: pm_implied_prob (only if the spec targets a prediction-market instrument — skip unless certain)

ALREADY EXHAUSTED — do NOT re-author these (they FAILED honestly): plain momentum/EMA-cross, Bollinger/Donchian/ATR/ADX breakout, RSI mean-reversion, dual-timeframe momentum, pure-social-level (galaxy/altrank), dollar-weakness (dxy as the sole signal), calendar/day-of-week/turn-of-month seasonality, cross-sectional momentum, funding-carry, raw on-chain levels (≤ astro control), Fear&Greed-alone contrarian, VIX-alone capitulation. Bring ORTHOGONAL structure: regime-GATING (a macro/vol regime that ARMS a different entry), cross-asset CONFLUENCE, positioning+sentiment COMPOSITES, novel combinations — not single tired signals.

PRINCIPLES: prefer LOW-TURNOVER (spot taker fee is 10bps — high churn dies). Every hypothesis MUST have a disconfirmer (the control that would prove it's just momentum/buy-the-dip/level-in-disguise). Long-only on crypto spot.
`

const HYP_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    hypotheses: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          name: { type: 'string' },
          thesis: { type: 'string', description: 'why it should work + WHY hedge funds miss/ignore it' },
          tradable_universe: { type: 'string', description: 'which of the tradable symbols' },
          features_used: { type: 'array', items: { type: 'string' }, description: 'ONLY from the gate-testable feature list' },
          entry_logic: { type: 'string' },
          exit_logic: { type: 'string' },
          disconfirmer: { type: 'string' },
          gate_testable_now: { type: 'boolean', description: 'true ONLY if every feature has real PIT data now' },
          data_needed_if_not: { type: 'string', description: 'if not testable now, what un-quantified data would unlock it (the LLM-bridge backlog)' },
          web_evidence: { type: 'string', description: 'what web research found supporting/refuting it' },
        },
        required: ['name', 'thesis', 'features_used', 'entry_logic', 'exit_logic', 'disconfirmer', 'gate_testable_now'],
      },
    },
  },
  required: ['hypotheses'],
}

const SPEC_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    name: { type: 'string' },
    theme: { type: 'string' },
    spec_json: { type: 'string', description: 'the COMPLETE inbox StrategySpec as a JSON string' },
    features_used: { type: 'array', items: { type: 'string' } },
    disconfirmer: { type: 'string' },
    honest_prior: { type: 'string', description: 'likely-fail | maybe — your honest expectation' },
    valid: { type: 'boolean', description: 'true ONLY if validate_spec returned [] (no issues)' },
    issues: { type: 'string', description: 'validator output' },
  },
  required: ['name', 'spec_json', 'valid', 'features_used'],
}

const THEMES = [
  { key: 'cross-asset-macro', brief: 'Cross-asset macro lead-lag & regime: does an equity-vol / dollar / yield-curve / credit / gold-oil REGIME (used as a GATE that arms a crypto or sector-ETF entry, not as a lone signal) carry orthogonal info? e.g. "only take the crypto trend when macro_regime is risk-on AND vix_term_slope is in contango". Web: documented macro→crypto and macro→sector lead-lags, risk-on/off regime timing.' },
  { key: 'vol-positioning', brief: 'Volatility & positioning structure: vix_term_slope (backwardation = stress), dvol vs realized vol carry, funding_rate as a POSITIONING extreme that GATES a momentum/reversion entry (not funding-carry, which failed). Web: vol-risk-premium, vol term-structure timing, funding-as-crowding done right.' },
  { key: 'sentiment-regime', brief: 'Sentiment as a REGIME GATE (not a lone contrarian): fear_greed / pm_risk_on / macro_regime defining WHEN a trend or breakout is tradable vs noise. Composites: sentiment + vol confluence arming a position. Web: sentiment-conditioned momentum, crowd-regime studies.' },
  { key: 'prediction-market', brief: 'Prediction-market & crowd-belief signals (the HEDGE-FUND-BLINDSPOT small market): pm_risk_on / pm_implied_prob as a leading macro-risk gauge for crypto. Web: prediction-market mispricing, Polymarket as a leading indicator, retail-crowd-belief edges. Flag honestly if data is too thin (only ~1yr).' },
  { key: 'equity-macro-timing', brief: 'Equity-ETF macro-regime timing (unlocks the equity-only features): credit_spread (scan showed +IC!), yield_curve_2s10s, putcall_ratio, vix as REGIME GATES timing SPY/QQQ/sector-ETF exposure. e.g. de-risk SPY when credit_spread spikes + curve inverts. Web: credit-spread/curve as equity regime signals, defensive timing.' },
  { key: 'llm-bridge-novel', brief: 'The genuinely-NOVEL LLM-bridge / un-quantified-data plays: weather→energy/ag, news-event→asset, niche-social→small-cap-attention, OSINT, qualitative→quantitative scoring. MOST will NOT be gate-testable now (no PIT data) — that is EXPECTED: return them with gate_testable_now=false and data_needed_if_not filled in, as the LLM-bridge backlog. Author only the rare one with existing data. Web: what un-automated/un-quantified signals exist that an LLM could read but no quant feed captures.' },
]

phase('Research')
log('Researching 6 hedge-fund-blindspot themes (web + our data inventory)...')
const research = await parallel(THEMES.map((t) => () =>
  agent(
    `${CONTEXT}\n\nYou are a quant researcher. THEME: ${t.brief}\n\nUse WebSearch/WebFetch (load them via ToolSearch query "WebSearch,WebFetch") to find DOCUMENTED or HIDDEN correlations / anomalies for this theme — especially small-market or un-quantified ones a hedge fund would ignore. Then propose 4-6 CONCRETE, distinct hypotheses on our TRADABLE universe. For each: be specific about entry/exit and the disconfirmer. Set gate_testable_now=true ONLY if every feature you name is in the gate-testable list with real data; otherwise false + fill data_needed_if_not. Prefer regime-GATING / confluence / composites over the exhausted single signals. Return via the schema.`,
    { schema: HYP_SCHEMA, phase: 'Research', label: `research:${t.key}` }
  ).then((r) => ({ theme: t.key, ...(r || { hypotheses: [] }) }))
))

const allHyps = research.filter(Boolean).flatMap((r) => (r.hypotheses || []).map((h) => ({ ...h, theme: r.theme })))
const testable = allHyps.filter((h) => h.gate_testable_now)
const backlog = allHyps.filter((h) => !h.gate_testable_now)
log(`Got ${allHyps.length} hypotheses — ${testable.length} gate-testable now, ${backlog.length} need-new-data (LLM-bridge backlog).`)
const toAuthor = testable.slice(0, 28)

phase('Author')
log(`Authoring ${toAuthor.length} StrategySpecs (each self-validated against the real compiler)...`)
const SPEC_RULES = `
Author ONE typed StrategySpec as a COMPLETE inbox JSON. EXACT shape (mirror this; every threshold is a {"param": "..."} ref into param_space — NEVER a literal number in entry/exit):
{
  "name": "...", "rationale": "thesis + the explicit disconfirmer(s)", "catalyst": "...",
  "universe": {"venues": ["binance"], "asset_classes": ["crypto"], "min_liquidity_usd": 10000000, "min_instruments": 5},
  "horizon": {"bar_size": "1d", "min_hold_days": 2, "max_hold_days": 20},
  "entry": [ {"feature": {"name": "<gate-testable feature>"}, "op": "lt|gt|cross_up|cross_down|between", "threshold": {"param": "<p>"}} ],
  "exit": {"stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"}, "time_stop_days": {"param": "time_stop"}, "signal_exits": [ ... ]},
  "risk": {"max_concurrent_positions": 5, "max_position_pct": 0.2, "conviction": 0.5},
  "param_space": { "<p>": {"kind": "float","lo": .., "hi": ..}, "stop": {"kind":"float","lo":0.06,"hi":0.20}, "tp": {"kind":"float","lo":0.08,"hi":0.35}, "time_stop": {"kind":"int","lo":5,"hi":25,"step":1} },
  "direction": 1, "funding_feature": null
}
RULES: features ONLY from the gate-testable list. For DRIFTING features use cross_up/cross_down, never lt/gt on the raw level. For equity specs set asset_classes:["equity"] + venues:["yahoo"] and universe over SPY/QQQ/sector ETFs. Long-only on crypto (direction 1). Keep param_space ranges economically sane so the feature actually binds. EVERY entry/exit threshold must be a param in param_space (validate_spec rejects magic numbers).

SELF-VALIDATE before returning: write your JSON to /tmp/spec_<short-slug>.json, then run from the repo root:
  PYTHONPATH=apps/engine python3 -c "import json; from cosmu.strategy.spec import StrategySpec; from cosmu.strategy.static_check import validate_spec; print(validate_spec(StrategySpec.model_validate(json.load(open('/tmp/spec_<short-slug>.json')))))"
If it prints [] the spec is valid (set valid=true). If it prints issues, FIX the JSON and re-run until []. Return the final JSON string in spec_json, valid=true/false, and the validator output in issues.
`
const specs = await parallel(toAuthor.map((h, i) => () =>
  agent(
    `${CONTEXT}\n\n${SPEC_RULES}\n\nHYPOTHESIS to author (#${i}):\n${JSON.stringify(h, null, 2)}\n\nAuthor the spec, self-validate, and return via the schema. Make the name descriptive and unique.`,
    { schema: SPEC_SCHEMA, phase: 'Author', label: `author:${(h.name || i).toString().slice(0, 22)}` }
  )
))

const valid = specs.filter(Boolean).filter((s) => s.valid)
log(`Authored ${specs.filter(Boolean).length} specs, ${valid.length} self-validated OK.`)
return { backlog, hypotheses_count: allHyps.length, specs: specs.filter(Boolean), valid_count: valid.length }
