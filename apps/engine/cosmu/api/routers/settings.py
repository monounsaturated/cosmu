# intent: read-only key inventory for the Keys page (one row PER env var); inputs: none; outputs: SettingsKeysResponse; invariants: only presence booleans are derived — no secret value is ever returned.

from __future__ import annotations

import os

from fastapi import APIRouter

from cosmu.api._shared import settings
from cosmu.api.models import KeyPresence, SettingsKeyRow, SettingsKeysResponse

router = APIRouter()

# Host the env var belongs on for the v18 "Location" column. Almost everything is the engine deploy host
# (Railway); Modal tokens are laptop/CI-only and never baked into the Railway image.
Host = str  # Literal["railway","vercel","local","none"] on the model; plain str here for the table below.

# The canonical key table: (env_var, service, description, requirement, cost, host, configured).
# ONE entry PER env var — composite secrets (Binance/Alpaca/R2/Modal/Reddit) are split into their parts so
# the v18 index keys on a single var. `configured` is the ONLY thing read from a secret — a boolean, never
# the value. Mirrors docs/KEYS.md.


def _key_table() -> list[tuple[str, str, str, str, str, str, bool]]:
    env = os.environ
    return [
        ("API_SECRET_KEY", "API secret", "Locks the control-plane API — the web app sends it; nobody else can call the engine.", "required", "free", "railway", bool(settings.api_secret_key)),
        ("XAI_API_KEY", "xAI (Grok)", "LLM strategy authoring (preferred). Research still runs offline without it.", "optional", "paid", "railway", bool(settings.xai_api_key)),
        ("OPENROUTER_API_KEY", "OpenRouter", "LLM authoring fallback when xAI is not set.", "optional", "paid", "railway", bool(settings.openrouter_api_key)),
        ("LUNARCRUSH_API_KEY", "LunarCrush", "Social-sentiment scores + a real (non-synthetic) edge-gate verdict.", "optional", "paid", "railway", bool(settings.lunarcrush_api_key)),
        ("FRED_API_KEY", "FRED", "Macro-regime cross-asset source (free key).", "optional", "free", "railway", bool(settings.fred_api_key)),
        ("POLYMARKET_TOKEN", "Polymarket", "Prediction-market risk-on cross-asset source (a market token id, not a secret).", "optional", "free", "railway", bool(settings.polymarket_token)),
        ("BINANCE_API_KEY", "Binance (live)", "Real-money execution on Binance spot. Only needed once you arm live trading.", "live-only", "free", "railway", bool(settings.binance_api_key)),
        ("BINANCE_API_SECRET", "Binance (live)", "Real-money execution on Binance spot. Only needed once you arm live trading.", "live-only", "free", "railway", bool(settings.binance_api_secret)),
        ("BINANCE_TESTNET_API_KEY", "Binance (testnet)", "Paper execution against Binance testnet (testnet.binance.vision).", "optional", "free", "railway", bool(settings.binance_testnet_api_key)),
        ("BINANCE_TESTNET_API_SECRET", "Binance (testnet)", "Paper execution against Binance testnet (testnet.binance.vision).", "optional", "free", "railway", bool(settings.binance_testnet_api_secret)),
        ("ALPACA_PAPER_API_KEY", "Alpaca (paper)", "US equities market data (IEX) + free paper execution — the equity forward-test lane.", "optional", "free", "railway", bool(settings.alpaca_paper_api_key)),
        ("ALPACA_PAPER_API_SECRET", "Alpaca (paper)", "US equities market data (IEX) + free paper execution — the equity forward-test lane.", "optional", "free", "railway", bool(settings.alpaca_paper_api_secret)),
        ("ALPACA_API_KEY", "Alpaca (live)", "Real-money US equities execution on Alpaca. Only needed once you arm live trading.", "live-only", "free", "railway", bool(settings.alpaca_api_key)),
        ("ALPACA_API_SECRET", "Alpaca (live)", "Real-money US equities execution on Alpaca. Only needed once you arm live trading.", "live-only", "free", "railway", bool(settings.alpaca_api_secret)),
        ("SLACK_WEBHOOK_URL", "Slack alerts", "Ops alerts to a Slack channel.", "optional", "free", "railway", bool(env.get("SLACK_WEBHOOK_URL"))),
        ("RAILWAY_API_TOKEN", "Railway", "Live Railway billing on the Costs page (real run-rate, not an estimate).", "optional", "free", "railway", bool(settings.railway_api_token)),
        ("R2_ACCOUNT_ID", "Cloudflare R2", "The cold-data lake — alt-data history as Parquet on R2 (cheap, zero-egress), queried by DuckDB.", "optional", "paid", "railway", bool(settings.r2_account_id)),
        ("R2_ACCESS_KEY_ID", "Cloudflare R2", "The cold-data lake — alt-data history as Parquet on R2 (cheap, zero-egress), queried by DuckDB.", "optional", "paid", "railway", bool(settings.r2_access_key_id)),
        ("R2_SECRET_ACCESS_KEY", "Cloudflare R2", "The cold-data lake — alt-data history as Parquet on R2 (cheap, zero-egress), queried by DuckDB.", "optional", "paid", "railway", bool(settings.r2_secret_access_key)),
        ("R2_BUCKET", "Cloudflare R2", "The cold-data lake — alt-data history as Parquet on R2 (cheap, zero-egress), queried by DuckDB.", "optional", "paid", "railway", bool(settings.r2_bucket)),
        ("MODAL_TOKEN_ID", "Modal", "Heavy compute offload (backtests / ML / matrix sweeps) on Modal's scale-to-zero workers.", "optional", "paid", "local", bool(env.get("MODAL_TOKEN_ID"))),
        ("MODAL_TOKEN_SECRET", "Modal", "Heavy compute offload (backtests / ML / matrix sweeps) on Modal's scale-to-zero workers.", "optional", "paid", "local", bool(env.get("MODAL_TOKEN_SECRET"))),
        ("CRYPTOPANIC_API_KEY", "CryptoPanic", "News-vote sentiment per symbol (free tier). Degrades to [] without it.", "optional", "free", "railway", bool(settings.cryptopanic_api_key)),
        ("REDDIT_CLIENT_ID", "Reddit", "Reddit post / comment volume features. Keyless-degrades to [] without it.", "optional", "free", "railway", bool(env.get("REDDIT_CLIENT_ID"))),
        ("REDDIT_CLIENT_SECRET", "Reddit", "Reddit post / comment volume features. Keyless-degrades to [] without it.", "optional", "free", "railway", bool(env.get("REDDIT_CLIENT_SECRET"))),
    ]


def _settings_key_rows() -> list[SettingsKeyRow]:
    """Build the read-only per-env-var key inventory. SECURITY: only a boolean presence is derived per env var
    — no value is ever read into the response. The engine can only observe the env of the PROCESS it runs in,
    so presence is recorded for that one side and left None (honest "unverified") for the other — never
    fabricated. The canonical table lives in docs/KEYS.md."""
    # The engine process can only see its own env. In production it's the deployed host (Railway) → the values
    # it reads ARE the host's; locally it's the laptop/.env.local. We NEVER guess the side we cannot observe.
    is_prod = getattr(settings, "environment", "local") == "production"
    rows: list[SettingsKeyRow] = []
    for env_var, service, description, requirement, cost, host, configured in _key_table():
        present = KeyPresence(
            local=None if is_prod else configured,
            host=configured if is_prod else None,
        )
        observed = present.host if is_prod else present.local  # the side we can actually see
        if observed:
            status = "connected"
        elif requirement in ("required", "live-only"):
            status = "missing"  # expected but absent on the side we observe
        else:
            status = "unset"  # optional and absent
        rows.append(
            SettingsKeyRow(
                key=service,
                env_var=env_var,
                configured=configured,
                unlocks=description,
                where=f"{service} key on {host}",
                name=env_var,
                service=service,
                description=description,
                host=host,  # type: ignore[arg-type]
                present=present,
                status=status,  # type: ignore[arg-type]
                requirement=requirement,  # type: ignore[arg-type]
                cost=cost,  # type: ignore[arg-type]
            )
        )
    return rows


@router.get("/settings/keys", response_model=SettingsKeysResponse)
def settings_keys() -> SettingsKeysResponse:
    """Read-only per-env-var key inventory for the Keys page: which env vars are configured (per location) and
    what each unlocks. SECURITY: values are NEVER returned — only a presence boolean per var. The canonical key
    table lives in docs/KEYS.md."""
    return SettingsKeysResponse(rows=_settings_key_rows())
