# The discovery-corpus fix (SAFE, high-leverage part of the alpha-search redesign). Two placebo/routing leaks
# diluted the autonomous 4h search: (a) ~9 NON-CAUSAL CONTROL features (astro/weather/exotic quakes+Kp,
# enabled=True) leaked into the brief corpus via _registry_briefs() and inflated the BH-FDR / deflation
# effective-N with theses that can NEVER win; (b) equity-only alt features were briefed "Condition CRYPTO
# entries on…" and stripped by the crypto validator → never tested. This locks the fix:
#   * control_feature_names() == the expected 9-feature control set,
#   * discovery ∪ control == the enabled feature_names() (nothing lost, nothing double-counted),
#   * registry_version() is BYTE-UNCHANGED (the new is_control field is off the hashed surface),
#   * NO control feature appears in _registry_briefs(),
#   * an equity-only feature is briefed EQUITY and, through draft_from_brief, produces an equity/ibkr spec that
#     RETAINS the feature (regression against the strip-bug).
# Hermetic: no network, no live DB; the store-backed paths use a temp sqlite Store like the other lab tests.

from __future__ import annotations

from cosmu.config.feature_registry import (
    FEATURE_REGISTRY,
    asset_classes_of,
    control_feature_names,
    discovery_feature_names,
    feature_names,
    registry_version,
)
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.lab.author import draft_from_brief
from cosmu.lab.research import _registry_briefs

# The ENABLED non-causal CONTROL features — the known-false noise floor the Gate is EXPECTED to kill. Any
# feature whose prior literally says "NON-CAUSAL CONTROL" / "ORTHOGONALITY CONTROL … Must be killed by the
# Gate". Frozen here so a stray future is_control=True (or a removed one) trips the test.
_EXPECTED_CONTROLS = {
    "astro_lunar_phase",
    "astro_sun_longitude",
    "astro_jupiter_longitude",
    "astro_saturn_longitude",
    "astro_sun_jupiter_aspect",
    "weather_hub_stress",
    "usgs_earthquake_count",
    "usgs_max_magnitude",
    "noaa_kp_index",
}

# registry_version() BEFORE this fix — pinned so the new is_control field provably does NOT alter the version
# hash (a promoted survivor's frozen registry stays reproducible byte-for-byte).
_REGISTRY_VERSION_FROZEN = "a06cd8eab024146d"


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/discovery.sqlite3", openrouter_api_key=None))


# ---------------------------------------------------------------------------
# 1) The control set + the hard invariants
# ---------------------------------------------------------------------------
def test_control_feature_names_is_the_expected_set():
    assert control_feature_names() == _EXPECTED_CONTROLS


def test_every_control_is_flagged_and_still_enabled():
    # is_control must sit ONLY on the expected set, and each must remain enabled (the Gate still needs the
    # placebo baseline in feature_names() to kill — the fix removes them from the corpus, not the universe).
    flagged = {f.name for f in FEATURE_REGISTRY if f.is_control}
    assert flagged == _EXPECTED_CONTROLS
    for name in _EXPECTED_CONTROLS:
        assert name in feature_names(), f"{name} must stay in feature_names() (the Gate's placebo baseline)"


def test_discovery_union_control_equals_enabled_and_disjoint():
    disc, ctrl, enabled = discovery_feature_names(), control_feature_names(), feature_names()
    assert disc | ctrl == enabled  # nothing lost
    assert disc & ctrl == set()  # nothing double-counted
    assert ctrl <= enabled  # controls are a subset of the enabled universe


def test_registry_version_is_byte_unchanged():
    # The is_control field is deliberately OFF registry_version()'s hashed surface (name|source|transform).
    assert registry_version() == _REGISTRY_VERSION_FROZEN
    assert registry_version() == registry_version()  # and deterministic across calls


# ---------------------------------------------------------------------------
# 2) No control leaks into the discovery corpus
# ---------------------------------------------------------------------------
def test_no_control_appears_in_registry_briefs():
    briefs = _registry_briefs()
    ctrl = control_feature_names()
    for text, feats in briefs:
        assert not (set(feats) & ctrl), f"control feature leaked into a brief's feature list: {feats}"
        for c in ctrl:
            assert c not in text, f"control feature name leaked into a brief's text: {text!r}"


def test_registry_briefs_cover_only_discovery_features():
    briefs = _registry_briefs()
    from cosmu.data.backtest import PRICE_FEATURES

    briefed = {f for _, feats in briefs for f in feats if f != "ret_Nd"}
    # Every briefed non-anchor feature is an enabled DISCOVERY feature (never a control, never price/TA).
    assert briefed <= discovery_feature_names()
    assert not (briefed & control_feature_names())
    assert not (briefed & PRICE_FEATURES)


# ---------------------------------------------------------------------------
# 3) Honest equity routing (the strip-bug regression)
# ---------------------------------------------------------------------------
def test_equity_only_feature_is_briefed_as_equity():
    # credit_spread is equity-only → its registry briefs must be framed on EQUITY, never CRYPTO.
    briefs = _registry_briefs()
    assert asset_classes_of("credit_spread") == ("equity",)
    cs_briefs = [text for text, feats in briefs if "credit_spread" in feats]
    assert cs_briefs, "credit_spread should have registry briefs"
    for text in cs_briefs:
        assert "crypto" not in text.lower(), f"equity-only feature briefed on crypto: {text!r}"
        assert "equity" in text.lower(), f"equity-only feature not framed on equity: {text!r}"


def test_equity_brief_produces_equity_spec_retaining_the_feature():
    # The FULL loop: the honest equity brief → draft_from_brief → an EQUITY/ibkr spec that RETAINS credit_spread
    # (regression against the strip bug where a crypto-framed brief dropped the equity-only feature entirely).
    brief = "Condition equity entries on credit spread extremes (registry-derived; must earn its place)"
    draft = draft_from_brief(brief, features=["credit_spread"])
    assert draft.spec.universe.asset_classes == ["equity"]
    assert draft.spec.universe.venues == ["ibkr"]
    entry_feats = [c.feature.name for c in draft.spec.entry]
    assert "credit_spread" in entry_feats, "the equity feature was stripped — the strip bug is back"
    assert draft.valid, draft.issues


def test_no_asset_brief_with_equity_only_feature_retargets_to_equity():
    # The draft_from_brief fallback: a brief that names NO asset but pins an equity-ONLY feature must retarget
    # the universe to equity so valid_feats keeps the feature (instead of the crypto validator stripping it).
    draft = draft_from_brief("Fade extremes in the signal", features=["insider_buy_ratio"])
    assert draft.spec.universe.asset_classes == ["equity"]
    assert draft.spec.universe.venues == ["ibkr"]
    assert "insider_buy_ratio" in [c.feature.name for c in draft.spec.entry]


def test_crypto_brief_is_unchanged_regression():
    # The DEFAULT crypto behavior must be untouched: a crypto brief with crypto features stays crypto/binance.
    draft = draft_from_brief("Fade oversold RSI on crypto", features=["rsi", "bb_z"])
    assert draft.spec.universe.asset_classes == ["crypto"]
    assert draft.spec.universe.venues == ["binance"]
    entry_feats = [c.feature.name for c in draft.spec.entry]
    assert entry_feats == ["rsi", "bb_z"]


def test_multiclass_feature_brief_is_not_retargeted_to_equity_only():
    # A crypto-capable / multi-class feature (macro_regime spans crypto+equity) must NOT be forced to an
    # equity-ONLY universe by the no-asset fallback — only EXCLUSIVELY non-crypto features trigger the retarget.
    # The default crypto universe (template default) must still be able to read it (crypto in the classes).
    assert "crypto" in asset_classes_of("macro_regime")
    draft = draft_from_brief("Condition entries on macro regime extremes", features=["macro_regime"])
    assert "crypto" in draft.spec.universe.asset_classes
    assert draft.spec.universe.asset_classes != ["equity"]  # the retarget did NOT fire
    assert "macro_regime" in [c.feature.name for c in draft.spec.entry]


def test_store_backed_equity_brief_is_hermetic(tmp_path):
    # A store-wired author path (memory + novelty consulted) still routes the equity feature honestly and
    # retains it — proves the fix holds through the full memory/novelty plumbing, no network.
    store = _store(tmp_path)
    brief = "Condition equity entries on insider buy ratio extremes (registry-derived; must earn its place)"
    draft = draft_from_brief(brief, features=["insider_buy_ratio"], store=store)
    assert draft.spec.universe.asset_classes == ["equity"]
    assert "insider_buy_ratio" in [c.feature.name for c in draft.spec.entry]
