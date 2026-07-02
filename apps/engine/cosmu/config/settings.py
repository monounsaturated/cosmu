# intent: load typed engine settings from server env/.env.local; inputs: env vars; outputs: Settings; invariants: secrets stay server-side and never enter prompts, DB rows, or frontend payloads.

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ADVISORY paper maturity threshold (calendar days). A funded SIM track that has run at least this many
# days of real-close forward time AND is net-of-fee positive is *recommended* as live-ready (see
# master/paper_maturity.py). This is SURFACED, NOT ENFORCED — the operator launches via the modal at their
# discretion and the 5 interlocks remain the only hard gate. Kept a named constant (never an inline magic number)
# and intentionally OUTSIDE GateSettings so it can never leak into the deterministic scorer/FDR/money path.
PAPER_MIN_DAYS: int = 30

# NOTE: the screened→paper badge promotion is now TRADE-based, not time-based — a paper entrant earns the
# "Paper" badge on its FIRST real paper fill (orchestrator.loop._has_paper_fills), so there is no promotion-days
# threshold constant anymore. PAPER_MIN_DAYS above stays — it is the separate LIVE-readiness maturity gate.

# FORWARD-EVIDENCE SIGNIFICANCE floor for the live-arming gate (master/live_eligibility). PAPER_MIN_DAYS above
# gates CALENDAR time + the SIGN of the net return — but a zero-edge random walk is net-positive after the clock
# ~48% of the time (Monte-Carlo, 40k draws, the repo's OWN scorer PSR machinery), so "matured + green" is a
# coin-flip on real money. These add a SIGNIFICANCE floor on the forward trajectory: the daily-resampled marked-
# return Sharpe must clear a Probabilistic-Sharpe floor before a track AUTO-arms. `forward_dsr = PSR(daily marked
# Sharpe vs 0) − 0.5 ∈ [−0.5, +0.5]` — recentred so 0 = a coin-flip Sharpe, the SAME number the deploy lane's
# holdout floor uses. Calibrated on that MC: floor 0.15 drops the no-edge false-arm rate ~48% → ~35% (roughly
# n-invariant, a clean pivot) while a genuine modest edge (true daily Sharpe ~0.10, ann ~1.6) still auto-arms
# ~57% at 30 marks and MORE as forward evidence deepens. Deliberately MODERATE, not draconian: the human OVERRIDE
# still waives it (the data-backed-risk escape hatch) and the regime gate is never waived, so over-strictness here
# would only delay going live (the bigger sin for a profit machine; the §1 'missing < losing' asymmetry is already
# carried by days+regime+net-positive). Raise to 0.20 for a stricter ~30% false-arm cut at the cost of ~6pts of
# auto-arm power on a real edge. Kept named + OUTSIDE GateSettings so they can never leak into the deterministic
# scorer/FDR/money path (same isolation as PAPER_MIN_DAYS).
PAPER_MIN_FORWARD_DSR: float = 0.15
# Minimum daily-resampled forward return observations before the significance floor is computed — below this the
# PSR estimate is too noisy to trust, so the track fails safe to NOT-significant (blocked from AUTO-arming; the
# human override still applies). ~12 daily marks sits well under PAPER_MIN_DAYS for a normally-marked track, so a
# matured track always has enough; only a sparsely-marked (e.g. cron-gapped) track trips it.
PAPER_MIN_FORWARD_OBS: int = 12


class SpendSettings(BaseModel):
    daily_cap_usd: Decimal = Decimal("50")
    alpha_share: Decimal = Decimal("0.25")
    floor_usd: Decimal = Decimal("5")


class GateSettings(BaseModel):
    min_trades: int = 30
    max_drawdown_pct: Decimal = Decimal("0.25")
    min_folds_positive_pct: Decimal = Decimal("0.60")
    max_pbo: Decimal = Decimal("0.50")
    holdout_min_deflated_sharpe: Decimal = Decimal("0")
    min_deflated_sharpe_prob: Decimal = Decimal("0.95")  # PSR against the trial-inflated benchmark
    # A promoted strategy must BEAT buy-and-hold on the validation slice, net of fees — else a bull-regime long can
    # clear DSR/PBO/holdout/FDR yet underperform BTC and still be funded. Default on; the deterministic gate's, not
    # the agent's, to relax (e.g. for a market-neutral spec whose benchmark is cash, set this False per run).
    require_beat_buy_and_hold: bool = True
    # Benjamini-Hochberg false-discovery-rate level applied ACROSS a cohort of distinct candidates before any
    # become fundable. Lower q = stricter (fewer false discoveries funded). Generating more ideas per tick no
    # longer manufactures a "winner": every candidate is one more test the cohort's BH cutoff must absorb.
    fdr_q: Decimal = Decimal("0.10")


class EvolutionSettings(BaseModel):
    # Throughput knobs (NOT gate constants — these are env-overridable via EVOLUTION__COHORT_SIZE etc.).
    # WIDENED 2026-06-25 (widest-honest universe pivot, Binance→Kraken): cohort_size 64→128, survive_top 6→12.
    # A bigger population + wider survivor band is pure throughput: every extra candidate is one more test the
    # cohort's Benjamini-Hochberg FDR cutoff (gates.fdr_q, UNTOUCHED) must absorb, so a wider funnel finds more
    # REAL edges without ever manufacturing a false one. max_cohort_size (400) stays the hard ceiling above this.
    cohort_size: int = 128
    explore_pct: Decimal = Decimal("0.30")
    seed_lane_count: int = 6
    survive_top: int = 12
    max_cohort_size: int = 400
    default_seed: int = 7


class LiveSettings(BaseModel):
    enabled: bool = False
    per_strategy_live_cap: Decimal = Decimal("2500")
    global_live_cap: Decimal = Decimal("10000")
    daily_loss_cap: Decimal = Decimal("250")
    # mode is the explicit real-money interlock: "testnet" never touches real funds (Binance Testnet,
    # fake money, real mechanics); "real" is the ONLY value that lets BINANCE_API_KEY/SECRET reach the
    # production exchange — and even then only with the live toggle ON + gates passed + caps available.
    mode: Literal["testnet", "real"] = "testnet"


class RiskSettings(BaseModel):
    global_max_notional: Decimal = Decimal("100000")
    per_strategy_cap: Decimal = Decimal("10000")
    drawdown_killswitch_pct: Decimal = Decimal("0.15")
    min_cash_reserve: Decimal = Decimal("1000")
    sandbox_seconds_cap: int = 30
    # --- LATCHING CIRCUIT-BREAKER (ops/breaker.py) — aviation graduated bands ------------------------------
    # The old drawdown/daily-loss guards only BLOCK the next entry; the breaker is the LATCHING actuator that
    # LIQUIDATES the armed book + DISARMS live on a hard breach and stays tripped until a human re-arms. These are
    # SENSE/DECIDE thresholds read by breaker.assess — they NEVER move money themselves (actuation delegates to the
    # existing gauntlet-exempt capital_guard.kill). Ordered warn < HALT < liquidate on the aggregate drawdown axis:
    #   • warn  (breaker_warn_drawdown_pct): the earliest CAUTION band — emits a breaker_warn event only, no action.
    #   • HALT  reuses the existing drawdown_killswitch_pct (the breaker READS it, never mutates/duplicates it): the
    #     entry-blocking band the gauntlet already enforces — the breaker escalates it to a warn-with-dwell, still no
    #     liquidation, so today's "block new entries" behaviour is preserved and only made observable.
    #   • liquidate (breaker_liquidate_drawdown_pct): the HARD band — trips the latch (disarm + liquidate) at 1 tick.
    # DAILY-LOSS axis: liquidate when daily_loss >= daily_loss_cap * breaker_liquidate_daily_loss_mult (the cap alone
    # is the existing entry-disarm; a MULTIPLE of it is the "we blew clean through the soft cap" hard trip).
    # DWELL: the SOFT (warn/halt) band must persist breaker_dwell_ticks consecutive marks before it escalates — a
    # single mark-to-market spike (one bad print, a transient wick) must not raise a warn. The HARD/liquidate band
    # trips at ONE tick (no dwell — a real hard breach is not debounced). breaker_enabled is the config-kill (no
    # deploy): False → assess still reads but trip() is a NO-OP, so the operator can disable the actuator instantly.
    breaker_enabled: bool = True
    breaker_warn_drawdown_pct: Decimal = Decimal("0.08")
    breaker_liquidate_drawdown_pct: Decimal = Decimal("0.25")
    breaker_liquidate_daily_loss_mult: Decimal = Decimal("1.5")
    breaker_dwell_ticks: int = 2


class VendorBudget(BaseModel):
    monthly_cap: Decimal = Decimal("0")  # 0 = uncapped; operator sets via BUDGET__<VENDOR>__MONTHLY_CAP


class BudgetConfig(BaseModel):
    """Monthly spend caps per vendor + global. 0 = uncapped. Set via env:
      BUDGET__GLOBAL_MONTHLY_CAP=300
      BUDGET__OPENROUTER__MONTHLY_CAP=50
      BUDGET__RAILWAY__MONTHLY_CAP=30
    Alert tiers: 50% info / 80% warn / 100% throttle-suggest → Slack + recommendation row.
    The default global cap is a NON-HALTING tripwire (alerts only, never blocks spend or trading) so the
    cost pipeline is live out of the box — paid LLM use is meant to be near-zero, so a $30/mo total is an
    'something unexpected ran up' heads-up, not a budget. Override with BUDGET__GLOBAL_MONTHLY_CAP; set 0 to
    silence all alerts. Per-vendor caps stay 0 (uncapped) unless the operator sets them."""
    global_monthly_cap: Decimal = Decimal("30")
    openrouter: VendorBudget = Field(default_factory=VendorBudget)
    xai: VendorBudget = Field(default_factory=VendorBudget)
    railway: VendorBudget = Field(default_factory=VendorBudget)
    modal: VendorBudget = Field(default_factory=VendorBudget)
    claude: VendorBudget = Field(default_factory=VendorBudget)


# Repo root holds the shared .env files (engine runs from apps/engine, so also check CWD). In a deployed
# container the package sits shallow (e.g. /app/cosmu/config/settings.py), so guard the index — production
# reads process env only and never loads a file, so a best-effort root is fine.
_parents = Path(__file__).resolve().parents
_ROOT = _parents[4] if len(_parents) > 4 else _parents[-1]

# APP_ENV (dev|test|qa|production, default dev) picks WHICH env file the profile loads. Production loads
# NO file — it reads process env only (secrets injected by the platform, never committed). dev maps to the
# existing .env.local so nothing breaks; the typed `environment` Literal below maps dev→local for back-compat.
_ENV_FILE_BY_PROFILE = {
    "dev": ".env.local",
    "test": ".env.local",   # local QA/test runs share the same real credentials as dev
    "qa": ".env.local",
    "production": None,  # process env only — no file is read
}
_PROFILE_TO_ENVIRONMENT = {"dev": "local", "test": "test", "qa": "production", "production": "production"}


def _profile() -> str:
    profile = os.environ.get("APP_ENV", "dev").strip().lower()
    return profile if profile in _ENV_FILE_BY_PROFILE else "dev"


def _profile_env_files() -> tuple[str, ...]:
    """Resolve the env files for the active APP_ENV profile. Root file first, then a CWD-relative copy so
    the engine works whether launched from the repo root or apps/engine. Production resolves to () (no file)."""
    name = _ENV_FILE_BY_PROFILE[_profile()]
    if name is None:
        return ()
    return (str(_ROOT / name), name)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_profile_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    app_name: str = "Cosmu v2"
    environment: Literal["local", "test", "production"] = Field(default_factory=lambda: _PROFILE_TO_ENVIRONMENT[_profile()])  # type: ignore[arg-type]
    database_url: str = Field(default="sqlite:///./.cosmu/cosmu.sqlite3")
    base_currency: str = "USD"
    # Operating jurisdiction (ISO-3166 alpha-2). Live-legality is a venue+country fact (e.g. Binance is not
    # legal for US live), so this PICKS which venues can move real money. Override with LIVE_JURISDICTION.
    live_jurisdiction: str = "FR"
    # Per-strategy STANDALONE track size — the capital one paper/SIM track is funded with (the funder
    # deploys exactly this per survivor; finder/arms stamp it as the track's starting_capital). Override with
    # SIM_TRACK_CAPITAL. Default $1k: small enough to be credible, above Binance-spot min-notional.
    sim_track_capital: Decimal = Decimal("1000")
    # SIM POOL bankroll — the shared paper account the tick funds many standalone tracks FROM (distinct from
    # the per-track slice above). Must stay >> sim_track_capital so multiple tracks fit. Override SIM_BANKROLL.
    sim_bankroll: Decimal = Decimal("100000")
    openrouter_api_key: str | None = Field(default=None, repr=False)
    # xAI (Grok) key. RESERVED FOR ON-DEMAND USE by default: the scheduled/unattended crons (ingest tweet
    # LiveSearch, llm_index rubric scoring, the tick author + research live_search) NEVER auto-spend it —
    # they route to OpenRouter ":free" instead (see llm_provider). This preserves the small xAI credit for
    # explicit on-demand tweet ingestion (scripts/backfill_voices.py reads XAI_API_KEY directly). Flip
    # XAI_SCHEDULED_ENABLED=1 to let the crons author/score with Grok again. Both APIs are OpenAI-compatible.
    xai_api_key: str | None = Field(default=None, repr=False)
    # Opt-in: allow the SCHEDULED crons to spend xAI (default off → xAI is on-demand only). See xai_api_key.
    xai_scheduled_enabled: bool = False
    # PAID-call throttle for LLM-BACKED ingest sources (xAI LiveSearch, llm_index rubric scoring): a source
    # whose newest stored point is younger than this many minutes is SKIPPED for the pass. Exists because the
    # Tier-1 15-min ingest cadence (realtime-data-lane epic) would otherwise multiply paid LLM calls ×24 vs
    # the old 6h cron — free/numeric sources never throttle (idempotent + $0). 0 disables the throttle.
    llm_source_min_interval_minutes: int = 60
    lunarcrush_api_key: str | None = Field(default=None, repr=False)
    # CryptoPanic news-vote source: key-gated (free tier). No key → the provider returns [] (honest
    # degradation, never fabricates). Reddit-volume uses REDDIT_CLIENT_ID/SECRET read directly from env.
    cryptopanic_api_key: str | None = Field(default=None, repr=False)
    # The in-process realtime recording worker (realtime-data-lane P3): OFF by default — the operator
    # activates with REALTIME_WORKER_ENABLED=1 after local testing (decision 2026-06-11). When off, the
    # Tier-1 crons remain the (slower) data lane; nothing else changes. The worker RECORDS only.
    realtime_worker_enabled: bool = False
    # The Railway-side cross-monitor of the Modal cron fleet (the watcher's watcher): OFF by default — the
    # operator flips MODAL_WATCH_ENABLED=1 on the always-on Railway engine. When on, an in-process loop
    # (cosmu/ops/modal_watch.py) re-runs the shared heartbeat.check() FROM Railway and pages if the Modal-driven
    # DB signals all go stale (= total Modal death the on-Modal heartbeat can't see itself). Detection only — no
    # failover/takeover. When off, nothing changes (the on-Modal heartbeat remains the sole watcher).
    modal_watch_enabled: bool = False
    # Ops toggles (match the existing Railway variable names): the in-process scheduler/autonomy loop
    # and the deterministic risk guardian. Default on; flip to false to freeze the machine.
    scheduler_enabled: bool = True
    guardian_enabled: bool = True
    # The Mind's LLM-as-judge committee is OPT-IN: off (default) → the analyst panel is fully deterministic and
    # offline ($0, fast). On + an LLM key → each pillar WITH data is rubric-scored by the model, while the
    # consensus stays deterministic math and the gate alone disposes. Flip with MIND_JUDGE_ENABLED.
    mind_judge_enabled: bool = False
    # Free cross-asset transfer sources: FRED needs a (free) key; Polymarket needs a real market token id
    # (not a secret). Wired into the ingest providers so setting them is all it takes to go live.
    fred_api_key: str | None = Field(default=None, repr=False)
    polymarket_token: str | None = Field(default=None)
    # Polymarket LIVE execution (CLOB on Polygon, USDC). The signing key is the ONLY thing that unlocks real
    # orders, and only with live.mode=="real" (the same never-auto-live interlock as Binance/Alpaca); the L2
    # API creds (key/secret/passphrase) are derived from the signing key by py-clob-client when omitted.
    # `funder_address` is the proxy/funder wallet positions+fills are keyed to (defaults to the signer);
    # `signature_type` is the py-clob-client signer kind (0=EOA, 1=email/magic proxy, 2=browser proxy).
    # TESTNET (Amoy) keys take precedence and never touch real funds. No signing key → the adapter is disabled
    # and prediction tracks stay on the SIM lane (honest degradation, identical to the unkeyed Binance path).
    polymarket_private_key: str | None = Field(default=None, repr=False)
    polymarket_api_key: str | None = Field(default=None, repr=False)
    polymarket_api_secret: str | None = Field(default=None, repr=False)
    polymarket_passphrase: str | None = Field(default=None, repr=False)
    polymarket_funder_address: str | None = Field(default=None)
    polymarket_signature_type: int = 0
    polymarket_testnet_private_key: str | None = Field(default=None, repr=False)
    polymarket_testnet_api_key: str | None = Field(default=None, repr=False)
    polymarket_testnet_api_secret: str | None = Field(default=None, repr=False)
    polymarket_testnet_passphrase: str | None = Field(default=None, repr=False)
    binance_api_key: str | None = Field(default=None, repr=False)
    binance_api_secret: str | None = Field(default=None, repr=False)
    binance_testnet_api_key: str | None = Field(default=None, repr=False)
    binance_testnet_api_secret: str | None = Field(default=None, repr=False)
    # Kraken spot (crypto): the US-legal live crypto venue. Real keys are honored ONLY with live.mode=="real"
    # (the same never-auto-live interlock as Binance/Alpaca). Kraken spot has NO public sandbox/testnet, so
    # there is no testnet key pair — the only modes are disabled (no keys) and live (keys + mode=="real"). No
    # keys → the adapter is disabled and crypto tracks routed here stay on the SIM lane (honest degradation).
    # NOTE: live Kraken from FR/EU retail is ESMA-restricted for derivatives, but SPOT is permitted via Payward
    # Europe Ltd (MiCA); the keys + live.mode interlock guarantees nothing arms without explicit operator action.
    kraken_api_key: str | None = Field(default=None, repr=False)
    kraken_api_secret: str | None = Field(default=None, repr=False)
    # Alpaca (US equities): PAPER keys unlock the free paper-trading lane AND the market-data API (IEX feed) —
    # the equity data+paper venue. Live keys are honored ONLY with live.mode=="real" (the same
    # never-auto-live interlock as Binance). No keys → the adapter is disabled and the equity lane stays on
    # the keyless Yahoo/Stooq path (honest degradation).
    alpaca_paper_api_key: str | None = Field(default=None, repr=False)
    alpaca_paper_api_secret: str | None = Field(default=None, repr=False)
    alpaca_api_key: str | None = Field(default=None, repr=False)
    alpaca_api_secret: str | None = Field(default=None, repr=False)
    api_secret_key: str | None = Field(default=None, repr=False)
    # SECOND-TIER money-path auth (DARK-LAUNCHED — off by default). `api_secret_key` above authenticates the
    # WEB PROXY to the engine (every route). `operator_secret_key` is a SEPARATE shared secret the proxy injects
    # (as x-operator) ONLY on money-mutating routes (toggle/live, live/launch|defund|liquidate|activate,
    # live/rules|jurisdiction, ops/breaker/rearm) AFTER it has verified a real operator session cookie — so a
    # leaked x-api-key alone can no longer drive the money control plane. `operator_auth_enforced` is the single
    # switch: while False (default) the engine's two-tier check and the extra prod boot-assert are BOTH no-ops,
    # so merging + deploy is byte-identical to today and can never lock the operator out. Flip
    # OPERATOR_AUTH_ENFORCED=true (and set OPERATOR_SECRET_KEY on the engine + the web session secrets on Vercel)
    # to activate. See docs/KEYS.md.
    operator_secret_key: str | None = Field(default=None, repr=False)
    operator_auth_enforced: bool = Field(default=False)
    railway_api_token: str | None = Field(default=None, repr=False)
    slack_webhook_url: str | None = Field(default=None, repr=False)
    # Aviation two-tier alerting: slack_webhook_url is the master-CAUTION / LOG bus (routine, high-signal
    # notices — gate verdicts, budget info/warn, stride pings). slack_webhook_url_page is the OPTIONAL
    # master-WARNING / PAGE bus (a second, louder channel for the few "wake me up" events — total-silence fleet
    # death, account EXHAUSTED, budget 100% crossed). UNSET → the page tier falls back to slack_webhook_url, so a
    # single-channel operator keeps one channel and loses nothing; set it (SLACK_WEBHOOK_URL_PAGE) to split the
    # buses. Never enters prompts/DB/frontend (repr=False, same isolation as every secret above).
    slack_webhook_url_page: str | None = Field(default=None, repr=False)
    # --- alt-data storage tier (hot/cold) ---------------------------------------------------------------
    # "pg" (default, unchanged): alt_data rows live in Postgres (hot, transactional, the live-gate read path).
    # "parquet": the COLD tier — alt-data is an append-only Parquet lake read via DuckDB (columnar, ~5-15x
    # smaller, no per-row btrees), local for research / Cloudflare R2 for prod. Flip with ALT_DATA_BACKEND once
    # the lake is backfilled (python -m cosmu.data.export_alt_parquet). See docs/epics/hot-cold-data-stack.md.
    # "pg" (hot Postgres, money/UI default) · "parquet" (raw Parquet glob, legacy) · "ducklake" (DuckLake on R2,
    # full archive) · "tiered" (PG-hot ∪ DuckLake-cold — the RESEARCH default once the lake is backfilled, so a
    # prune never opens a blind spot). Money/UI always read raw PG regardless of this setting.
    alt_data_backend: Literal["pg", "parquet", "ducklake", "tiered"] = "pg"
    alt_data_parquet_root: str = ".cosmu/altdata_parquet"
    # Cloudflare R2 (S3-compatible object store, ~$0.36/mo/24GB, ZERO egress) for the prod Parquet lake. All
    # four present → the cold tier writes/reads R2; absent → it uses the local dir (honest degradation, same
    # keyless-fallback pattern as the Alpaca lane). Set R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
    # / R2_BUCKET in .env.local (and on Railway for prod ingest).
    r2_account_id: str | None = Field(default=None, repr=False)
    r2_access_key_id: str | None = Field(default=None, repr=False)
    r2_secret_access_key: str | None = Field(default=None, repr=False)
    r2_bucket: str | None = Field(default=None)
    spend: SpendSettings = Field(default_factory=SpendSettings)
    gates: GateSettings = Field(default_factory=GateSettings)
    live: LiveSettings = Field(default_factory=LiveSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    # Matrix sweep universe — the assets and timeframes the overnight strategy × asset × timeframe
    # hunt visits. Override via MATRIX_SWEEP_ASSETS (comma-separated) and MATRIX_SWEEP_TIMEFRAMES.
    # Defaults are deep-cached majors (crypto spot + equity ETFs) and daily bars only.
    matrix_sweep_assets: list[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "SPY", "QQQ"],
    )
    matrix_sweep_timeframes: list[str] = Field(default=["1d"])

    @property
    def llm_provider(self) -> str | None:
        """Provider for AUTOMATIC/scheduled LLM work (author, judge, index scoring). xAI is reserved for
        ON-DEMAND use unless XAI_SCHEDULED_ENABLED=1, so the unattended crons default to OpenRouter ":free"
        ($0) — preserving the small xAI credit. Order: xAI (only when opted in) → OpenRouter → None
        (deterministic template). Centralizes the choice in one place."""
        if self.xai_api_key and self.xai_scheduled_enabled:
            return "xai"
        if self.openrouter_api_key:
            return "openrouter"
        return None

    @property
    def llm_api_key(self) -> str | None:
        """The key that MATCHES llm_provider (kept consistent so the router hits the right base URL — never an
        xAI key paired with the OpenRouter URL or vice-versa). None → deterministic template authoring."""
        provider = self.llm_provider
        if provider == "xai":
            return self.xai_api_key
        if provider == "openrouter":
            return self.openrouter_api_key
        return None

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            return Path(".cosmu/cosmu.sqlite3")
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

