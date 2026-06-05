# intent: load typed engine settings from server env/.env.local; inputs: env vars; outputs: Settings; invariants: secrets stay server-side and never enter prompts, DB rows, or frontend payloads.

from __future__ import annotations

import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ADVISORY forward-test maturity threshold (calendar days). A funded SIM track that has run at least this many
# days of real-close forward time AND is net-of-fee positive is *recommended* as live-ready (see
# master/forward_maturity.py). This is SURFACED, NOT ENFORCED — the operator launches via the modal at their
# discretion and the 5 interlocks remain the only hard gate. Kept a named constant (never an inline magic number)
# and intentionally OUTSIDE GateSettings so it can never leak into the deterministic scorer/FDR/money path.
FORWARD_TEST_MIN_DAYS: int = 30


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
    cohort_size: int = 64
    explore_pct: Decimal = Decimal("0.30")
    seed_lane_count: int = 6
    survive_top: int = 6
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


class VendorBudget(BaseModel):
    monthly_cap: Decimal = Decimal("0")  # 0 = uncapped; operator sets via BUDGET__<VENDOR>__MONTHLY_CAP


class BudgetConfig(BaseModel):
    """Monthly spend caps per vendor + global. 0 = uncapped. Set via env:
      BUDGET__GLOBAL_MONTHLY_CAP=300
      BUDGET__OPENROUTER__MONTHLY_CAP=50
      BUDGET__RAILWAY__MONTHLY_CAP=30
    Alert tiers: 50% info / 80% warn / 100% throttle-suggest → Slack + recommendation row."""
    global_monthly_cap: Decimal = Decimal("0")
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
    "test": ".env.test.local",
    "qa": ".env.qa.local",
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
    sim_bankroll: Decimal = Decimal("100000")
    openrouter_api_key: str | None = Field(default=None, repr=False)
    # LLM author: xAI (Grok) is preferred when XAI_API_KEY is set (already on Railway) — most efficient,
    # no new key; OpenRouter is the fallback. Both are OpenAI-compatible (same request shape).
    xai_api_key: str | None = Field(default=None, repr=False)
    lunarcrush_api_key: str | None = Field(default=None, repr=False)
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
    binance_api_key: str | None = Field(default=None, repr=False)
    binance_api_secret: str | None = Field(default=None, repr=False)
    binance_testnet_api_key: str | None = Field(default=None, repr=False)
    binance_testnet_api_secret: str | None = Field(default=None, repr=False)
    api_secret_key: str | None = Field(default=None, repr=False)
    railway_api_token: str | None = Field(default=None, repr=False)
    slack_webhook_url: str | None = Field(default=None, repr=False)
    spend: SpendSettings = Field(default_factory=SpendSettings)
    gates: GateSettings = Field(default_factory=GateSettings)
    live: LiveSettings = Field(default_factory=LiveSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    @property
    def llm_provider(self) -> str | None:
        """Which LLM provider is live: xAI if XAI_API_KEY is set (preferred — already on Railway), else
        OpenRouter, else None (deterministic template authoring). Centralizes the choice in one place."""
        if self.xai_api_key:
            return "xai"
        if self.openrouter_api_key:
            return "openrouter"
        return None

    @property
    def llm_api_key(self) -> str | None:
        return self.xai_api_key or self.openrouter_api_key

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            return Path(".cosmu/cosmu.sqlite3")
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

