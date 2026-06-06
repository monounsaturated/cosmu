# intent: define the named feature vocabulary the lab agent may reference; inputs: config/static seed; outputs: FeatureDefinition list; invariants: every feature has as-of semantics and a prior hypothesis.

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# Pinned transform version for the xAI/Grok Twitter sentiment source.  Bump this string whenever
# the scoring prompt or weighting logic changes so a gate-passed survivor remains re-runnable.
TWITTER_TRANSFORM_VERSION = "xai-twitter-sentiment-v1"

# Pinned transform version for the social-authority features ("PageRank for credibility"). Bump when the
# claim-extraction prompt, the deterministic resolver/scoring, or the authority fusion changes, so a gate-passed
# survivor that depends on author authority stays re-runnable. Kept here (not imported from cosmu.mind) to avoid
# an import cycle; cosmu.mind.authority.AUTHORITY_VERSION carries the same string.
AUTHORITY_TRANSFORM_VERSION = "social-authority-v1"


class FeatureDefinition(BaseModel):
    name: str
    source: str
    tier: Literal["tier0", "tier1"]
    asset_classes: list[str]
    asof_semantics: str
    prior: str
    enabled: bool = True
    # Pins the (frozen, versioned) ingest transform a feature depends on, so a survivor is
    # re-runnable byte-for-byte. None = pure price/registry feature, no ingest transform.
    transform_version: str | None = None


FEATURE_REGISTRY: tuple[FeatureDefinition, ...] = (
    FeatureDefinition(name="funding_rate", source="ccxt", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Funding extremes proxy crowded leverage; used as a long filter (spot, long-only).", transform_version="funding-zscore-v1"),
    FeatureDefinition(name="fear_greed", source="alternative.me", tier="tier0", asset_classes=["crypto"], asof_semantics="daily publication time (next-day availability)", prior="Crowd fear mean-reverts at swing horizon — buy fear, fade greed.", transform_version="feargreed-regime-v1"),
    FeatureDefinition(name="news_sentiment", source="news_headlines", tier="tier1", asset_classes=["crypto"], asof_semantics="LLM-standardized at headline availability time", prior="A positive news-flow shift precedes multi-day continuation before it is fully priced.", transform_version="news-sentiment-v1"),
    # --- cross-asset transfer features (Phase 1.6): one market's price IS another's feature. ---
    FeatureDefinition(name="pm_risk_on", source="polymarket", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="CLOB midpoint at quote time (no lag)", prior="Prediction-market odds on macro/risk events price the risk regime before it shows in any single asset's own price — a cross-asset risk-on/off tag.", transform_version="pm-riskon-v1"),
    FeatureDefinition(name="xasset_risk_appetite", source="ccxt", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="exchange publication time", prior="Crypto perp funding is a fast, 24/7 read on speculative risk appetite that leads slower equity/macro signals — transfer crypto's read onto equities.", transform_version="xasset-funding-v1"),
    FeatureDefinition(name="macro_regime", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Macro regime (curve slope, real rates, liquidity) conditions risk premia across every asset class — a shared regime tag, not a single-market signal.", transform_version="macro-regime-v1"),
    FeatureDefinition(name="vix_level", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="VIX measures implied volatility; extremes signal regime shifts and mean-revert at swing horizon", transform_version="vix-level-v1"),
    FeatureDefinition(name="fed_funds_rate", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="FRED release time (next-day availability floor)", prior="Federal funds rate changes drive risk premia across all asset classes", transform_version="fed-funds-v1"),
    FeatureDefinition(name="defi_tvl", source="defillama", tier="tier0", asset_classes=["crypto"], asof_semantics="daily publication time (next-day availability floor)", prior="DeFi TVL flows indicate risk appetite and liquidity across crypto protocols", transform_version="defi-tvl-v1"),
    FeatureDefinition(name="open_interest", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="OI changes reveal leverage build-up."),
    FeatureDefinition(name="perp_spot_basis", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="exchange publication time", prior="Basis captures risk appetite and carry."),
    FeatureDefinition(name="exchange_netflow", source="exchange", tier="tier0", asset_classes=["crypto"], asof_semantics="provider knowledge time", prior="Net inflows can precede sell pressure."),
    FeatureDefinition(name="vix_term_slope", source="fred/cboe", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Term slope encodes risk regime."),
    FeatureDefinition(name="putcall_ratio", source="cboe", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time (next-day availability floor)", prior="Sentiment extremes mean-revert at swing horizon.", transform_version="putcall-zscore-v1"),
    FeatureDefinition(name="liquidation_cascade", source="coinglass", tier="tier0", asset_classes=["crypto"], asof_semantics="liquidation bucket close time (next-bucket availability floor)", prior="A spike in total long+short liquidations marks forced deleveraging that overshoots — a cascade exhausts sellers and mean-reverts at the swing horizon.", transform_version="liquidation-cascade-zscore-v1"),
    # Best-effort OSINT ("watching planes"): aircraft activity from the free OpenSky Network as a crude,
    # LOW-CONFIDENCE macro-risk-appetite proxy. Availability == observation time (a live snapshot is only
    # knowable when taken — no look-ahead). tier1 + the explicit low-confidence prior mean it must earn its
    # place via out-of-sample; the gate down-weights it until it pays.
    FeatureDefinition(name="osint_air_activity", source="opensky", tier="tier1", asset_classes=["crypto", "equity"], asof_semantics="live ADS-B snapshot time (availability == observation, no look-ahead)", prior="Aircraft activity is a crude, low-confidence macro risk-appetite/economic-activity proxy (best-effort OSINT); must earn its place via OOS — flag low-confidence.", transform_version="osint-adsb-v1"),
    FeatureDefinition(name="cftc_net_positioning", source="cftc", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="CFTC release time", prior="Crowded positioning can unwind."),
    FeatureDefinition(name="dxy", source="fred", tier="tier0", asset_classes=["equity", "crypto"], asof_semantics="daily publication time", prior="Dollar strength changes risk appetite."),
    FeatureDefinition(name="yield_curve_2s10s", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Curve slope tracks macro regime."),
    FeatureDefinition(name="credit_spread", source="fred", tier="tier0", asset_classes=["equity"], asof_semantics="daily publication time", prior="Credit stress drives equity risk premia."),
    FeatureDefinition(name="days_to_earnings", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="Earnings windows alter drift and volatility."),
    FeatureDefinition(name="insider_buy_ratio", source="sec_edgar", tier="tier0", asset_classes=["equity"], asof_semantics="Form 4 publication time", prior="Insider buying can signal undervaluation."),
    FeatureDefinition(name="short_interest_ratio", source="fundamentals_vendor", tier="tier0", asset_classes=["equity"], asof_semantics="vendor availability time", prior="High short interest can fuel squeezes."),
    FeatureDefinition(name="ret_Nd", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity", "prediction"], asof_semantics="bar close time", prior="Medium-term return captures momentum/reversal."),
    # Cross-sectional rank of N-day return across the universe at bar-close time: 0 = worst, 1 = best.
    # Computed from parquet_bars (same source as ret_Nd) at the bar close so it is point-in-time: rank is
    # derived only from instruments present at that bar (no survivorship look-ahead).  A high rank (near 1)
    # identifies the cross-sectional momentum leaders; a low rank (near 0) identifies the laggards.  The
    # lookback window mirrors ret_Nd (a fitted ParamRef in each strategy) so the rank is consistent with the
    # raw return it is derived from.  transform_version pins the ranking method (percentile, not ordinal) so a
    # gate-passed survivor is re-runnable byte-for-byte.
    FeatureDefinition(
        name="xsec_momentum_rank",
        source="parquet_bars",
        tier="tier0",
        asset_classes=["crypto", "equity"],
        asof_semantics="bar close time (cross-sectional rank computed over instruments present at bar close — point-in-time, no survivorship look-ahead)",
        prior=(
            "Cross-sectional percentile rank [0, 1] of N-day return across the screened universe at each bar close. "
            "High rank (→ 1) = relative momentum leader; low rank (→ 0) = relative momentum laggard. "
            "Ranking longs by top-rank and shorts by bottom-rank constructs a market-neutral book whose beta to the "
            "market cancels — the residual is pure cross-sectional momentum premium (documented in AQR / Jegadeesh–Titman). "
            "Must earn its place via OOS."
        ),
        transform_version="xsec-momentum-rank-v1",
    ),
    FeatureDefinition(name="atr", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ATR normalizes risk and stop distance."),
    FeatureDefinition(name="rsi", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="RSI captures overextension."),
    FeatureDefinition(name="adx", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="ADX separates trend from chop."),
    FeatureDefinition(name="bb_z", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Band z-score captures statistically unusual price."),
    FeatureDefinition(name="vol_realized", source="parquet_bars", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="bar close time", prior="Realized vol gates capacity and risk."),
    # --- social feeds (tier1, low-confidence until validated OOS): Reddit crowd sentiment (free, no key) and
    # LunarCrush social metrics (key-gated; empty without a key). The gate down-weights tier1 until it pays. ---
    FeatureDefinition(name="reddit_sentiment", source="reddit", tier="tier1", asset_classes=["crypto"], asof_semantics="public hot.json read time (availability == observation, no look-ahead)", prior="Reddit crowd chatter (bull vs bear post mix) is a fast, low-confidence sentiment proxy — extremes may mean-revert at the swing horizon; must earn its place via OOS.", transform_version="reddit-sentiment-v1"),
    FeatureDefinition(name="social_volume", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="A surge in social volume can mark crowd attention that precedes (or exhausts) a move — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="social_sentiment", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush social sentiment is a crowd-mood proxy; a positive shift may precede continuation before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="galaxy_score", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush Galaxy Score blends price + social health into one rank; extremes are a low-confidence regime tag — must earn its place via OOS.", transform_version="lunarcrush-v1"),
    # The four remaining LunarCrush coin time-series fields, hoarded per coin alongside the three above
    # (scripts/lunarcrush_max_extract.py pulls all seven in one call). Same daily next-day-availability PIT
    # semantics; tier1 + low-confidence until validated OOS. alt_rank is LunarCrush's combined social+market
    # rank (1 = best, so a FALLING alt_rank = improving). market_cap_usd / volume_24h_usd / price_usd are the
    # vendor's own market series (distinct from the Binance bars — usable as cross-checks or scale normalizers).
    FeatureDefinition(name="alt_rank", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush AltRank blends social activity and market performance into one cross-sectional rank (1 = best); an IMPROVING rank (falling number) may flag an asset gaining relative social+price strength before it is priced — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="market_cap_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's daily market-cap series; a size/scale normalizer and capacity guard rather than a directional signal — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="volume_24h_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's daily 24h traded-volume series; the dollar-volume denominator for excess-attention measures and a liquidity gate — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    FeatureDefinition(name="price_usd", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor)", prior="LunarCrush's own daily price series; a vendor cross-check of the Binance bars and a base for vendor-side return computations — low-confidence until validated OOS.", transform_version="lunarcrush-v1"),
    # --- NORMALIZED LunarCrush derivations (cosmu/research/social_norm.py): scale-stable, within-asset, PIT.
    # The raw levels above drift ~160x over 2020-26, so a fitted level threshold is always-true (the phase0
    # social-signal §4 trap). These decompose attention into CHANGE (leads +) vs ALTITUDE (leads -), which the
    # lead-lag probe shows carry OPPOSITE-signed information. tier1, low-confidence until validated OOS. ---
    FeatureDefinition(name="social_volume_accel", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); ln(v_t/v_{t-1}), available_at of the later point", prior="A FRESH jump in social attention (day-over-day log-change of social_volume) leads price up at k=1-3d (attention momentum) — distinct from, and opposite to, the elevated LEVEL.", transform_version="social-norm-v1"),
    FeatureDefinition(name="social_attention_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of social_volume", prior="SUSTAINED elevated social_volume (within-asset z of the level) leads price DOWN, worse with horizon — the crowd is already piled in. Used as a 'too crowded' altitude guard, not a long trigger.", transform_version="social-norm-v1"),
    FeatureDefinition(name="social_excess_attention_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of ln(social_volume)-ln(dollar_volume)", prior="Crowd loudness RELATIVE to money traded (social/dollar-volume) leads price UP at the ~1-week horizon (k=7 decile spread +1.8%, t=+5.77) — robust longer-horizon continuation the absolute-volume specs missed.", transform_version="social-norm-v1"),
    FeatureDefinition(name="galaxy_score_z", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="daily social bucket (next-day availability floor); trailing 30d within-asset z of galaxy_score", prior="Within-asset z of galaxy_score crowd-health; a low-confidence regime tag (the top-decile drawdown asymmetry seen on a short sample did NOT robustly replicate on the full sample — registered for completeness, no spec rests on it).", transform_version="social-norm-v1"),
    FeatureDefinition(name="btc_social_accel", source="lunarcrush", tier="tier1", asset_classes=["crypto"], asof_semantics="BTC daily social bucket (next-day availability floor); BTC social_volume log-change broadcast to all symbols", prior="A BTC social-attention spike leads the mean-ALT return at k=1d (cross-asset attention contagion) — BTC's crowd, read on the alts.", transform_version="social-norm-v1"),
    # xAI/Grok Twitter sentiment (key-gated: XAI_API_KEY required; returns [] without it).
    # The LLM ONLY standardizes/scores tweet text — it is NEVER on the gate/scoring/money path.
    # Both features are market-wide (the query covers crypto broadly, not a single asset).
    # tier1 + low-confidence until validated OOS; the gate down-weights until it earns its place.
    FeatureDefinition(
        name="twitter_sentiment",
        source="xai",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="xAI LiveSearch fetch time (availability == observation, no look-ahead)",
        prior=(
            "Real-time Twitter/X crypto sentiment scored by Grok on [-1, +1]; "
            "crowd social signal that may lead price at swing horizon — low-confidence until validated OOS."
        ),
        transform_version=TWITTER_TRANSFORM_VERSION,
    ),
    FeatureDefinition(
        name="twitter_influencer_sentiment",
        source="xai",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="xAI LiveSearch fetch time (availability == observation, no look-ahead)",
        prior=(
            "Influencer-weighted Twitter/X sentiment: each tweet's Grok score is weighted by the author's "
            "historical hit-rate (fraction of past calls followed by correct price direction). "
            "Accounts with higher empirical accuracy carry more weight. tier1 + low-confidence until validated OOS."
        ),
        transform_version=TWITTER_TRANSFORM_VERSION,
    ),
    # Event/news scorer: a typed, dated, point-in-time signal with sign [-1,+1] and magnitude [0,1].
    # The LLM (when keyed) standardizes/scores the headline text — ONLY at ingest, NEVER on the gate path.
    # Without an LLM key the offline lexicon is used (StandardizedNews path). tier1 + low-confidence
    # until validated OOS; the gate down-weights until it earns its place.
    FeatureDefinition(
        name="news_event_score",
        source="news",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="headline availability time (ts == available_at; point-in-time, no look-ahead)",
        prior=(
            "A typed, dated event/news signal: sign + magnitude derived from the headline text at ingest. "
            "Positive = bullish catalyst (approval, surge, adoption); negative = bearish event (hack, ban, crash). "
            "The LLM standardizes text only at ingest; NEVER on the gate/scoring/money path. "
            "tier1 + low-confidence until validated OOS."
        ),
        transform_version="news-event-score-v1",
    ),
    # --- LLM qualitative→quantitative INDEX scores (VISION §6): an LLM-as-judge standardizes narrative into a
    # rubric-anchored numeric score, stored POINT-IN-TIME WITH HISTORY so the gate can train on it. The LLM ONLY
    # proposes the number against an explicit rubric; the deterministic Gate alone disposes — NEVER the money path.
    # Both are market-wide + tier1 (low-confidence until validated OOS; the gate down-weights until it earns its
    # place). transform_version pins the rubric+prompt so a gate-passed survivor is re-runnable byte-for-byte. ---
    FeatureDefinition(
        name="reg_risk_crypto",
        source="llm_index",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="LLM index minted at evidence-availability time (availability == observation, no look-ahead)",
        prior=(
            "An LLM-as-judge standardizes qualitative regulatory news into a [0, 1] crackdown-pressure score "
            "against an explicit rubric (0 = supportive/clear, 1 = severe crackdown). A spike marks rising "
            "regulatory risk that may precede de-risking. The LLM proposes; the deterministic Gate disposes — "
            "low-confidence until validated OOS."
        ),
        transform_version="llm-index-v1",
    ),
    FeatureDefinition(
        name="risk_on_off",
        source="llm_index",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="LLM index minted at evidence-availability time (availability == observation, no look-ahead)",
        prior=(
            "An LLM-as-judge standardizes macro/geopolitical narrative into a [-1, +1] risk-appetite score "
            "against an explicit rubric (+1 risk-on, -1 risk-off) — a shared cross-asset regime tag. The LLM "
            "proposes; the deterministic Gate disposes — low-confidence until validated OOS."
        ),
        transform_version="llm-index-v1",
    ),
    # --- cross-asset daily price levels (free, no key) via Stooq/Yahoo: one asset class's price IS another's
    # macro feature. Each is market-wide, point-in-time (a daily close is known the next day — see
    # multiasset-daily-v1), and tier0 like the other liquid macro reads (dxy/vix). They condition the shared
    # risk regime across crypto + equity, so each spans both classes. ---
    FeatureDefinition(name="gold_xau", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Gold is the canonical risk-off / real-rate hedge; its level and trend tag the macro risk regime that conditions crypto + equity premia.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="silver_xag", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Silver blends a precious-metal hedge with industrial demand; the gold/silver behaviour is a cyclical risk-appetite read.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="wti_crude", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="Crude oil is a growth + inflation impulse; sharp moves precede shifts in risk premia across every class.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="spx_index", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="The S&P 500 is the global risk-on benchmark; crypto's beta to broad equities means SPX trend is a shared regime tag.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="ndx_index", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="The Nasdaq-100 carries the high-beta tech/liquidity factor crypto co-moves with most strongly — a faster risk-appetite read than SPX.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="eurusd", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="EUR/USD is the dominant dollar-strength gauge; a weaker dollar loosens global financial conditions, a tailwind for risk assets.", transform_version="multiasset-daily-v1"),
    FeatureDefinition(name="usdjpy", source="stooq", tier="tier0", asset_classes=["crypto", "equity"], asof_semantics="daily close (next-day availability floor)", prior="USD/JPY tracks the yen carry trade and global liquidity; a sharp JPY rally often coincides with cross-asset risk-off deleveraging.", transform_version="multiasset-daily-v1"),
    # --- SOCIAL AUTHORITY ("PageRank for credibility", Phase 3): score voices by whether their PREDICTIVE claims
    # came true (deterministic Brier-skill vs base rate), whether they were FIRST (primacy), and whether they LED
    # an event vs ECHOED it — weighted by a citation-graph PageRank ANCHORED to that track record. Both features
    # are POINT-IN-TIME with history (availability == observation; a real-time credibility judgement is knowable
    # only when made — no look-ahead). Derived from the Phase-0 voice timeline, not a managed network pull, so they
    # live outside the managed-ingest catalog. tier1 + low-confidence: influence ≠ authority and a loud-but-wrong
    # account scores ~0, but the feature still must EARN its place out-of-sample through the gate. ---
    FeatureDefinition(
        name="authority_weighted_claim_signal",
        source="social_authority",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass",
        prior=(
            "A credibility-weighted directional consensus [-1, +1] of recent claims on an asset: each voice's vote "
            "(up/down/flat × conviction) is weighted by its citation-graph PageRank ANCHORED to a deterministic "
            "track record (Brier-skill vs base rate), discounted for echoing vs leading. A positive shift flags "
            "credible voices turning bullish before it is priced. Influence ≠ authority — a loud, wrong account "
            "barely registers. tier1 — must earn its place via OOS."
        ),
        transform_version=AUTHORITY_TRANSFORM_VERSION,
    ),
    FeatureDefinition(
        name="author_authority",
        source="social_authority",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="snapshot minted at observation time (availability == observation, no look-ahead); PIT history accrues per pass",
        prior=(
            "Per-voice credibility weight (personalized PageRank over the who-cites-whom graph, teleport ∝ the "
            "deterministic Brier-skill track record). The diagnostic per-handle series feeding the weighted claim "
            "signal: a quiet calibrated voice scores high, a loud wrong one scores ~0. tier1 — must earn OOS."
        ),
        transform_version=AUTHORITY_TRANSFORM_VERSION,
    ),
    FeatureDefinition(name="pm_implied_prob", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Odds are a cross-market probability signal."),
    FeatureDefinition(name="pm_prob_velocity", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Probability repricing speed identifies changing beliefs."),
    FeatureDefinition(name="pm_book_depth", source="polymarket_clob", tier="tier0", asset_classes=["prediction"], asof_semantics="CLOB snapshot time", prior="Depth defines fillable capacity."),
    # --- EU-accessible, keyless alt-data (tier1 until validated OOS): GDELT geopolitical tone + Deribit DVOL ---
    FeatureDefinition(
        name="gdelt_tone",
        source="gdelt",
        tier="tier1",
        asset_classes=["crypto", "equity"],
        asof_semantics="daily geopolitical news tone (next-day availability floor — a day's indexed articles are closed by end-of-day; no look-ahead)",
        prior="Aggregate geopolitical/macro news tone from GDELT (keyless, global); negative tone spikes mark risk-off events that can precede drawdowns; sustained positive tone may tag risk-on regimes. tier1 — must earn its place OOS.",
        transform_version="gdelt-tone-v1",
    ),
    FeatureDefinition(
        name="dvol",
        source="deribit",
        tier="tier0",
        asset_classes=["crypto"],
        asof_semantics="daily close (next-day availability floor — DVOL bar opens at midnight UTC and is finalized at day-end; no look-ahead)",
        prior="Deribit DVOL is the crypto-native options implied volatility index (30-day annualized), the VIX equivalent for BTC/ETH options; elevated DVOL marks stress or opportunity and conditions position sizing and regime filters.",
        transform_version="dvol-v1",
    ),
)


def feature_names() -> set[str]:
    return {feature.name for feature in FEATURE_REGISTRY if feature.enabled}


def features_for(asset_classes: list[str]) -> list[FeatureDefinition]:
    wanted = set(asset_classes)
    return [
        feature
        for feature in FEATURE_REGISTRY
        if feature.enabled and (wanted & set(feature.asset_classes))
    ]

