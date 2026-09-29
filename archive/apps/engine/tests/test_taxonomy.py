# Verifies the leaderboard's faceted taxonomy is DERIVED from a spec's named features (no manual tagging):
# the signal-family follows the referenced alt-data features, price-only specs fall back to Math/Price, and
# the orthogonal facets (asset class, venue, timeframe, edge-type) read straight off the spec.

from cosmu.strategy.taxonomy import derive_facets, family_of_feature, strategy_origin_family


def _spec(features, *, asset_classes=None, venues=None, bar_size="4h", funding_feature=None, setup=None):
    return {
        "universe": {"asset_classes": asset_classes or ["crypto"], "venues": venues or ["binance"]},
        "horizon": {"bar_size": bar_size, "min_hold_days": 1, "max_hold_days": 5},
        "entry": [{"feature": {"name": name}, "op": "gt", "threshold": {"param": "t"}} for name in features],
        "exit": {"signal_exits": []},
        "funding_feature": funding_feature,
        "setup": setup,
    }


def test_price_only_spec_is_math_price():
    facets = derive_facets(_spec(["rsi", "atr"]), "template")
    assert facets.signal_family == "math_price"
    assert facets.signal_family_label == "Math/Price"
    assert facets.edge_type == "mean-reversion"  # rsi -> overextension fade


def test_social_feature_drives_family():
    facets = derive_facets(_spec(["rsi", "reddit_sentiment"]), "chat")
    assert facets.signal_family == "social"
    assert facets.origin == "chat"
    assert "reddit_sentiment" in facets.features


def test_onchain_flow_and_carry():
    facets = derive_facets(_spec(["funding_rate"], funding_feature="funding_rate"), "template")
    assert facets.signal_family == "onchain_flow"
    assert facets.edge_type == "carry"


def test_macro_positioning_overrides():
    # risk_on_off is minted by llm_index but is a macro regime tag, not news.
    assert family_of_feature("risk_on_off") == "macro_positioning"
    facets = derive_facets(_spec(["vix_level", "dxy"]), "template")
    assert facets.signal_family == "macro_positioning"


def test_multi_asset_and_venue():
    facets = derive_facets(
        _spec(["ret_Nd"], asset_classes=["crypto", "equity"], venues=["binance", "ibkr"]),
        "mined",
    )
    assert facets.asset_class == "multi"
    assert facets.venue == "multi"
    assert facets.timeframe == "4h"
    assert facets.edge_type == "momentum"


def test_breakout_setup_edge_type():
    facets = derive_facets(_spec(["atr"], setup={"orb": {"range_bars": {"param": "r"}}}), "template")
    assert facets.edge_type == "breakout"


def test_malformed_spec_is_tolerated():
    facets = derive_facets({}, None)
    assert facets.signal_family == "math_price"
    assert facets.asset_class == "—"
    assert facets.origin == "template"


# --- Strategy origin family (operator rule: only Quant/LLM are origins; Index is the indicator layer) -----------

def test_llm_provenances_resolve_to_llm_family():
    # 'LLM'/'Prompt'/'agent'/'mind' all denote the LLM (= Prompt) strategy origin.
    assert strategy_origin_family("LLM") == "llm"
    assert strategy_origin_family("Prompt") == "llm"
    assert strategy_origin_family("agent") == "llm"
    assert strategy_origin_family("mind") == "llm"


def test_quant_provenances_resolve_to_quant_family():
    # Every sweep/mutation/documented/import/NL-intake provenance is the Quant (= ML) strategy origin.
    for o in ("ML", "Quant", "seed", "mutation", "wildcard", "finder",
              "documented", "pine", "nlp", "inbox", "chat", "vibe", "template"):
        assert strategy_origin_family(o) == "quant", o


def test_index_is_not_an_origin_it_is_the_indicator_layer():
    """Operator rule: 'Index' is NOT a strategy origin — it's the indicator/feature layer. A legacy
    origin='Index' reads as a typed quant spec that KEYS OFF an index feature, never a third origin."""
    assert strategy_origin_family("Index") == "quant"
    assert strategy_origin_family("index") == "quant"
    # The resolver only ever returns one of the TWO real families — never 'index'/'ml'/'prompt'.
    assert strategy_origin_family("Index") in ("quant", "llm")


def test_unknown_and_none_origin_default_to_quant():
    assert strategy_origin_family(None) == "quant"
    assert strategy_origin_family("") == "quant"
    assert strategy_origin_family("something-new") == "quant"
