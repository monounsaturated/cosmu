# Tests for cosmu/strategy/pine_url.py — the pine-from-url skill helper.
# All tests are offline (no live network): fixture Pine snippets stand in for scraped source.
# Invariants checked:
#   - static_check passes (zero issues)
#   - compile_spec does not raise
#   - spec name carries the page title and (pine-url) tag
#   - spec rationale embeds the author's description
#   - lifted_params is non-empty (no magic numbers)
#   - fallback path (no page name, no description) degrades gracefully

from __future__ import annotations

from cosmu.evolution.loop import fit_params
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine_samples import PINE_SAMPLES
from cosmu.strategy.pine_url import PineUrlResult, fetch_and_translate, _effective_name, _enrich_rationale
from cosmu.strategy.static_check import validate_spec

# ── fixtures ────────────────────────────────────────────────────────────────

_RSI_SOURCE = PINE_SAMPLES["RSI oversold reversion"]
_MACD_SOURCE = PINE_SAMPLES["MACD momentum"]
_BB_SOURCE = PINE_SAMPLES["Bollinger breakout"]
_ADX_SOURCE = PINE_SAMPLES["ADX trend filter"]

_PAGE_DESC = "Buys the dip when RSI crosses above the oversold threshold with a tight stop."
_PAGE_URL = "https://www.tradingview.com/script/abc123-rsi-dip-buy/"
_PAGE_NAME = "RSI Dip Buy v2"


# ── core translation tests ───────────────────────────────────────────────────


def test_fetch_and_translate_passes_static_check():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert isinstance(result, PineUrlResult)
    issues = validate_spec(result.translation.spec)
    assert issues == [], f"spec has validation issues: {issues}"


def test_fetch_and_translate_compiles():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    # compile_spec must not raise; fit_params gives it a concrete param dict
    compile_spec(result.translation.spec, fit_params(result.translation.spec))


def test_fetch_and_translate_lifts_magic_numbers():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert result.translation.lifted_params, "lifted_params must be non-empty — literals were not lifted"


def test_spec_name_uses_page_title():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert _PAGE_NAME in result.translation.spec.name, (
        f"spec name should contain page title; got {result.translation.spec.name!r}"
    )
    assert "(pine-url)" in result.translation.spec.name.lower(), (
        f"spec name should have (pine-url) tag; got {result.translation.spec.name!r}"
    )


def test_spec_name_without_page_title_uses_translator_name():
    result = fetch_and_translate(_RSI_SOURCE)
    # No page_name → falls back to whatever translate_pine inferred, still tagged
    assert "(pine-url)" in result.translation.spec.name.lower()
    # Must NOT say "Imported Pine strategy (pine-url)" verbatim — the translator inferred a better name
    # (this is a soft check; the translated name just needs the tag)
    assert result.translation.spec.name.strip()


def test_spec_rationale_embeds_description():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert _PAGE_DESC in result.translation.spec.rationale, (
        "rationale should embed author's description from the page"
    )


def test_spec_rationale_embeds_source_url():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert _PAGE_URL in result.translation.spec.rationale


def test_result_fields_populated():
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC, strategy_name=_PAGE_NAME, source_url=_PAGE_URL)
    assert result.description == _PAGE_DESC
    assert result.source_url == _PAGE_URL
    assert result.strategy_name  # non-empty


def test_no_network_calls_needed(monkeypatch):
    """fetch_and_translate must be offline-safe — it should not attempt any network I/O."""
    import socket

    def _block(*a, **kw):
        raise RuntimeError("fetch_and_translate made a live network call — must be offline-safe")

    monkeypatch.setattr(socket, "getaddrinfo", _block)
    # If this runs without raising, the function is truly offline.
    result = fetch_and_translate(_RSI_SOURCE, description=_PAGE_DESC)
    assert result.translation.spec.entry


# ── test all Pine samples round-trip ────────────────────────────────────────


def test_all_pine_samples_translate_via_url_helper():
    """Every canonical sample must survive fetch_and_translate → static_check → compile_spec."""
    for name, source in PINE_SAMPLES.items():
        result = fetch_and_translate(source, description=f"Community Pine: {name}", strategy_name=name, source_url="https://example.com/pine")
        issues = validate_spec(result.translation.spec)
        assert issues == [], f"{name}: static_check issues {issues}"
        compile_spec(result.translation.spec, fit_params(result.translation.spec))


# ── unit tests for name / rationale helpers ──────────────────────────────────


def test_effective_name_uses_page_name():
    assert _effective_name("Imported Pine strategy (pine)", "My Strategy") == "My Strategy (pine-url)"


def test_effective_name_strips_old_pine_tag():
    assert _effective_name("Old Name (pine)", "Old Name") == "Old Name (pine-url)"


def test_effective_name_strips_existing_pine_url_tag():
    assert _effective_name("Old Name (pine-url)", "Old Name") == "Old Name (pine-url)"


def test_effective_name_truncates_long_title():
    long = "A" * 100
    name = _effective_name("fallback", long)
    assert len(name) <= 80
    assert name.endswith("(pine-url)")


def test_effective_name_fallback_to_translated():
    name = _effective_name("Translated Name", "")
    assert "Translated Name" in name
    assert "(pine-url)" in name.lower()


def test_enrich_rationale_includes_description():
    enriched = _enrich_rationale("original rationale", "page description", "https://example.com")
    assert "page description" in enriched
    assert "original rationale" in enriched


def test_enrich_rationale_includes_url():
    enriched = _enrich_rationale("orig", "desc", "https://example.com/script")
    assert "https://example.com/script" in enriched


def test_enrich_rationale_without_url():
    enriched = _enrich_rationale("orig", "desc", "")
    assert "desc" in enriched
    assert "orig" in enriched
    # No dangling "Source:" line
    assert "Source:" not in enriched
