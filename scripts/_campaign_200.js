export const meta = {
  name: 'hidden-edge-200',
  description: 'Author ~200 diverse crypto StrategySpecs across structural niches on the POPULATED palette, each self-contained with a disconfirmer (gated on Modal afterwards)',
  phases: [{ title: 'Author', detail: '18 niche agents × ~12 specs each on the populated crypto palette' }],
}

const PALETTE = `
POPULATED CRYPTO FEATURES ONLY (these have real PIT data + actually trade on Modal). Tagged BOUNDED (a fitted level threshold binds — use lt/gt/between) or CROSS (drifting — use ONLY cross_up/cross_down) or SIGNED (a return):
  BOUNDED: fear_greed[0-100] · vix_level[~12-80] · dxy[range] · macro_regime[composite] · funding_rate[~±0.01] · rsi[0-100] · adx · bb_z[z-score] · vol_realized
  CROSS:   defi_tvl · btc_active_addresses · btc_tx_count · btc_hashrate
  SIGNED:  ret_Nd (momentum/reversal; positive=uptrend)
DO NOT use any other feature name (credit_spread/yield_curve/putcall are equity-only; net_liquidity/stablecoin_*/cg_btc_dominance/pm_*/nfci/wiki_*/vix_term_slope are EMPTY or BROKEN and will 0-trade — banned).
TRADABLE: crypto spot only — BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT ADAUSDT AVAXUSDT LINKUSDT. Long-only (direction 1). Binance 10bps taker — prefer LOW turnover.
`

const TEMPLATE = `
Each spec is a COMPLETE inbox JSON (every threshold a {"param":"..."} ref into param_space — NEVER a literal):
{
  "name":"<unique, descriptive>", "rationale":"<thesis + the explicit disconfirmer(s)>", "catalyst":"<trigger>",
  "universe":{"venues":["binance"],"asset_classes":["crypto"],"min_liquidity_usd":10000000,"min_instruments":5},
  "horizon":{"bar_size":"1d","min_hold_days":<int>,"max_hold_days":<int>},
  "entry":[ {"feature":{"name":"<palette>"},"op":"lt|gt|cross_up|cross_down|between","threshold":{"param":"<p>"}} , ...],
  "exit":{"stop_loss":{"param":"stop"},"take_profit":{"param":"tp"},"time_stop_days":{"param":"time_stop"},"signal_exits":[ ... ]},
  "risk":{"max_concurrent_positions":5,"max_position_pct":0.2,"conviction":0.5},
  "param_space":{ "<p>":{"kind":"float","lo":..,"hi":..}, "stop":{"kind":"float","lo":0.05,"hi":0.20}, "tp":{"kind":"float","lo":0.08,"hi":0.40}, "time_stop":{"kind":"int","lo":3,"hi":25,"step":1} },
  "direction":1, "funding_feature":null
}
RULES: features ONLY from the palette; DRIFTING features ONLY via cross_up/cross_down (never lt/gt on raw level); every entry/exit threshold is a param in param_space (no magic numbers); ret_Nd takes a "lookback":{"param":"..."}. Vary horizons, exits, thresholds, and which assets-of-the-universe. Each spec needs a DISTINCT thesis + a disconfirmer (the control that proves it isn't just momentum/buy-the-dip/level-in-disguise).
`

// 18 structural niches — distinct so the 200 are diverse, not threshold clones of one idea.
const NICHES = [
  'macro_regime as a REGIME GATE that arms a momentum entry (ret_Nd) — vary the armed entry + regime band.',
  'macro_regime / vix_level DUAL regime gate arming a mean-reversion (bb_z/rsi) entry.',
  'vix_level regime: HIGH-vix-armed contrarian long vs LOW-vix-armed trend continuation — both directions of the gate.',
  'dxy regime (dollar-weak / dollar-strong) as a cross-asset gate arming crypto trend or reversion.',
  'funding_rate POSITIONING extreme (deep-negative = crowded shorts) gating a long entry — NOT funding-carry.',
  'funding_rate + fear_greed COMPOSITE (positioning + sentiment must agree) arming a long.',
  'fear_greed as a REGIME (persistent greed = risk-on trend continuation) arming ret_Nd/adx — not lone contrarian.',
  'defi_tvl CROSS (TVL expansion/contraction cross) confluence with price momentum (ret_Nd).',
  'on-chain CROSS (btc_active_addresses / btc_tx_count growth cross) confirming a momentum or breakout long.',
  'btc_hashrate CROSS as a miner-commitment regime confluence with momentum.',
  'vol_realized regime: LOW-vol-armed trend vs HIGH-vol-armed reversion (vol-of-regime).',
  'bb_z mean-reversion GATED by a sentiment (fear_greed) or vol (vix_level) regime.',
  'adx trend strength GATED by a macro/sentiment regime (only ride trends in the right regime).',
  'rsi reversion GATED by macro_regime / vix (only buy oversold in a favourable regime).',
  'TRIPLE confluence (3-of: fear_greed + vix_level + funding_rate / macro_regime) — high-conviction rare entries.',
  'ret_Nd MULTI-HORIZON confluence (short + medium lookbacks agree) gated by a regime feature.',
  'vol_realized CHANGE / vix_level cross as a volatility-regime-shift trigger arming entry.',
  'creative cross-asset + on-chain + sentiment combinations not covered above (maximize orthogonality).',
]

const SPEC_BATCH_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    specs: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          name: { type: 'string' },
          spec_json: { type: 'string', description: 'the complete inbox StrategySpec JSON as a string' },
          disconfirmer: { type: 'string' },
        },
        required: ['name', 'spec_json'],
      },
    },
  },
  required: ['specs'],
}

phase('Author')
log(`Authoring ~${NICHES.length * 12} crypto specs across ${NICHES.length} structural niches...`)
const batches = await parallel(NICHES.map((niche, i) => () =>
  agent(
    `You author quant StrategySpecs for COSMU. ${PALETTE}\n${TEMPLATE}\n\nYOUR NICHE (#${i}): ${niche}\n\nProduce 12 DISTINCT, valid specs in this niche — vary the structure (which palette features, thresholds, horizons, exits, asset subsets), each with a unique name and a real disconfirmer in the rationale. Stay strictly on the populated palette. Return all 12 via the schema (spec_json = the complete inbox JSON string).`,
    { schema: SPEC_BATCH_SCHEMA, phase: 'Author', label: `niche:${i}` }
  ).then((r) => (r && r.specs ? r.specs : []))
))

const all = batches.filter(Boolean).flat()
log(`Authored ${all.length} raw specs across ${NICHES.length} niches.`)
return { specs: all, count: all.length }
