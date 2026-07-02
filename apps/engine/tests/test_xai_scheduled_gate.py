# Offline regression tests for the xAI on-demand gate (docs/reports/xai-spend-fix-2026-06-29.md).
# xAI/Grok is RESERVED for ON-DEMAND use: the scheduled/unattended crons (tick author, llm_index rubric
# scoring, ingest tweet LiveSearch, research live_search) must NEVER auto-spend it unless XAI_SCHEDULED_ENABLED=1
# — they default to OpenRouter ":free" ($0). These tests pin that routing so the silent ~$0.20/day xAI leak
# (key present in the Modal secret → crons spend Grok) cannot regress. No key / no network needed.

from __future__ import annotations

from cosmu.config.settings import Settings


def test_llm_provider_defaults_to_openrouter_when_xai_not_opted_in():
    """xAI key present but NOT opted in for scheduled use → automatic work routes to OpenRouter, not xAI."""
    s = Settings(xai_api_key="xai-test", openrouter_api_key="or-test")
    assert s.llm_provider == "openrouter"
    assert s.llm_api_key == "or-test"  # key MATCHES provider (never xai-key + openrouter-url)


def test_llm_provider_xai_only_when_opted_in():
    """XAI_SCHEDULED_ENABLED=1 restores xAI as the automatic provider (the explicit opt-in)."""
    s = Settings(xai_api_key="xai-test", openrouter_api_key="or-test", xai_scheduled_enabled=True)
    assert s.llm_provider == "xai"
    assert s.llm_api_key == "xai-test"


def test_llm_provider_none_when_only_xai_and_not_opted_in():
    """xAI key alone + default (off) → NO automatic LLM (deterministic template authoring), never xAI spend."""
    s = Settings(xai_api_key="xai-test", openrouter_api_key=None)
    assert s.llm_provider is None
    assert s.llm_api_key is None


def test_scheduled_ingest_does_not_wire_xai_tweet_key_by_default():
    """Providers.from_settings (the hourly ingest path) leaves XaiTwitterProvider keyless by default → the
    LiveSearch tweet pull degrades to [] ($0). On-demand paths construct the provider with the key directly."""
    from cosmu.ingest.run import Providers

    off = Providers.from_settings(Settings(xai_api_key="xai-test", openrouter_api_key=None))
    assert off.xai_twitter.api_key == ""  # no scheduled xAI spend

    on = Providers.from_settings(
        Settings(xai_api_key="xai-test", openrouter_api_key=None, xai_scheduled_enabled=True)
    )
    assert on.xai_twitter.api_key == "xai-test"  # opt-in re-arms the scheduled LiveSearch
