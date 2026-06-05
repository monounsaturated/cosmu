# intent: read-only key inventory for Settings → Keys; inputs: none; outputs: SettingsKeysResponse; invariants: only a boolean `configured` per key is derived — no secret value is ever returned.

from __future__ import annotations

import os

from fastapi import APIRouter

from cosmu.api._shared import settings
from cosmu.api.models import SettingsKeyRow, SettingsKeysResponse

router = APIRouter()


def _settings_key_rows() -> list[SettingsKeyRow]:
    """Build the read-only key inventory from typed settings. SECURITY: only the boolean `configured` is
    derived — no value is ever read into the response. The canonical table lives in docs/KEYS.md."""
    binance_live = bool(settings.binance_api_key and settings.binance_api_secret)
    binance_testnet = bool(settings.binance_testnet_api_key and settings.binance_testnet_api_secret)
    return [
        SettingsKeyRow(
            key="API secret",
            env_var="API_SECRET_KEY",
            configured=bool(settings.api_secret_key),
            unlocks="Locks the control-plane API — the web app sends it; nobody else can call the engine.",
            requirement="required",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="xAI (Grok)",
            env_var="XAI_API_KEY",
            configured=bool(settings.xai_api_key),
            unlocks="LLM strategy authoring (preferred). Research still runs offline without it.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="OpenRouter",
            env_var="OPENROUTER_API_KEY",
            configured=bool(settings.openrouter_api_key),
            unlocks="LLM authoring fallback when xAI is not set. Optional.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="LunarCrush",
            env_var="LUNARCRUSH_API_KEY",
            configured=bool(settings.lunarcrush_api_key),
            unlocks="Social-sentiment scores + a REAL (non-synthetic) edge-gate verdict.",
            requirement="optional",
            cost="paid",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="FRED",
            env_var="FRED_API_KEY",
            configured=bool(settings.fred_api_key),
            unlocks="Macro-regime cross-asset source (free key).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Polymarket",
            env_var="POLYMARKET_TOKEN",
            configured=bool(settings.polymarket_token),
            unlocks="Prediction-market risk-on cross-asset source (a market token id, not a secret).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Binance (live)",
            env_var="BINANCE_API_KEY / BINANCE_API_SECRET",
            configured=binance_live,
            unlocks="Real-money execution on Binance spot. Only needed once you arm live trading.",
            requirement="live-only",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Binance (testnet)",
            env_var="BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET",
            configured=binance_testnet,
            unlocks="Paper execution against Binance testnet (testnet.binance.vision).",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
        SettingsKeyRow(
            key="Slack alerts",
            env_var="SLACK_WEBHOOK_URL",
            configured=bool(os.environ.get("SLACK_WEBHOOK_URL")),
            unlocks="Ops alerts to a Slack channel.",
            requirement="optional",
            cost="free",
            where="Engine env (Railway)",
        ),
    ]


@router.get("/settings/keys", response_model=SettingsKeysResponse)
def settings_keys() -> SettingsKeysResponse:
    """Read-only key inventory for the Settings → Keys page: which provider keys are configured on the
    engine and what each unlocks. SECURITY: values are NEVER returned — only a boolean `configured` per
    key. Safe to render in the browser. The canonical key table lives in docs/KEYS.md."""
    return SettingsKeysResponse(rows=_settings_key_rows())
