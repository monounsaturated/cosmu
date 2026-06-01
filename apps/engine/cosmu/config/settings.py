# intent: load typed engine settings from server env/.env.local; inputs: env vars; outputs: Settings; invariants: secrets stay server-side and never enter prompts, DB rows, or frontend payloads.

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class RiskSettings(BaseModel):
    global_max_notional: Decimal = Decimal("100000")
    per_strategy_cap: Decimal = Decimal("10000")
    drawdown_killswitch_pct: Decimal = Decimal("0.15")
    min_cash_reserve: Decimal = Decimal("1000")
    sandbox_seconds_cap: int = 30


# Repo root holds the shared .env.local (engine runs from apps/engine, so also check there + CWD).
_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(_ROOT / ".env.local"), str(_ROOT / ".env"), ".env.local", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    app_name: str = "Cosmu v2"
    environment: Literal["local", "test", "production"] = "local"
    database_url: str = Field(default="sqlite:///./.cosmu/cosmu.sqlite3")
    base_currency: str = "USD"
    paper_bankroll: Decimal = Decimal("100000")
    openrouter_api_key: str | None = Field(default=None, repr=False)
    lunarcrush_api_key: str | None = Field(default=None, repr=False)
    binance_api_key: str | None = Field(default=None, repr=False)
    binance_api_secret: str | None = Field(default=None, repr=False)
    api_secret_key: str | None = Field(default=None, repr=False)
    spend: SpendSettings = Field(default_factory=SpendSettings)
    gates: GateSettings = Field(default_factory=GateSettings)
    live: LiveSettings = Field(default_factory=LiveSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            return Path(".cosmu/cosmu.sqlite3")
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

