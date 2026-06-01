"""The deterministic regime classifier + live-eligibility gate: labels (bull/bear/chop + vol bucket + trend)
from a reference series, and the live gate that allows a strategy ONLY in a regime it proved in (in-regime
allowed, out-of-regime blocked). The gate only blocks — it never promotes — and an empty proven set fails safe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.live_eligibility import live_regime_verdict, proven_regimes_for
from cosmu.ml.regime import Regime, current_regime, proven_regimes, regime_eligible


def _bars(returns: list[float]) -> list[Bar]:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    price = 100.0
    out: list[Bar] = []
    for i, r in enumerate(returns):
        open_ = price
        price = max(0.01, price * (1 + r))
        out.append(
            Bar(
                ts=start + timedelta(days=i),
                open=Decimal(str(round(open_, 6))),
                high=Decimal(str(round(max(open_, price) * 1.01, 6))),
                low=Decimal(str(round(min(open_, price) * 0.99, 6))),
                close=Decimal(str(round(price, 6))),
                volume=Decimal("1000000"),
            )
        )
    return out


def test_labels_bull_when_trending_up():
    regime = current_regime(_bars([0.01] * 80))
    assert regime.label == "bull"
    assert regime.trend == "bull"
    assert regime.vol_bucket in ("low", "mid", "high")


def test_labels_bear_when_trending_down():
    regime = current_regime(_bars([-0.01] * 80))
    assert regime.label == "bear"


def test_labels_chop_when_flat():
    # tiny alternating moves => no sustained trend over the lookback band
    regime = current_regime(_bars([0.001, -0.001] * 40))
    assert regime.label == "chop"


def test_proven_regimes_only_positive():
    proven = proven_regimes({"bull": 0.2, "bear": -0.1, "chop": 0.0})
    assert proven == {"bull"}


def test_regime_eligible_in_regime_allowed_out_blocked():
    bull = Regime(label="bull", vol_bucket="mid", trend="bull")
    bear = Regime(label="bear", vol_bucket="mid", trend="bear")
    proven = {"bull"}
    assert regime_eligible(bull, proven) is True   # in-regime allowed
    assert regime_eligible(bear, proven) is False  # out-of-regime blocked


def test_regime_eligible_empty_proven_fails_safe():
    bull = Regime(label="bull", vol_bucket="mid", trend="bull")
    assert regime_eligible(bull, set()) is False  # never proven anywhere => blocked


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/regime.sqlite3", openrouter_api_key=None))


def _open_sleeve(store: Store, version_id: str, proven: list[str]) -> None:
    store.append_event(
        actor="master", kind="sleeve_opened", ref_type="strategy_version", ref_id=version_id,
        payload={"deflated_sharpe": "0.97", "lane": "seed", "survival_score": 0.9, "survival_trained": False, "proven_regimes": proven},
    )


def test_live_eligibility_reads_passport_and_gates(tmp_path):
    store = _store(tmp_path)
    _open_sleeve(store, "v-bull", ["bull"])
    assert proven_regimes_for(store, "v-bull") == {"bull"}

    up = _bars([0.01] * 80)    # current regime = bull
    down = _bars([-0.01] * 80)  # current regime = bear

    allowed = live_regime_verdict(store, "v-bull", up)
    assert allowed.eligible is True
    assert allowed.current_regime.label == "bull"

    blocked = live_regime_verdict(store, "v-bull", down)
    assert blocked.eligible is False
    assert "not in proven set" in blocked.reason


def test_live_eligibility_unknown_version_blocked(tmp_path):
    store = _store(tmp_path)
    verdict = live_regime_verdict(store, "never-opened", _bars([0.01] * 80))
    assert verdict.eligible is False
    assert verdict.proven_regimes == []
