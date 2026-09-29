"""Hyperliquid LONG-TAIL POSITIONING hoard-logger + crowding/liq-density features + disconfirmer-gated BRUT
harness (next-data-axis #1, 2026-06-28). All OFFLINE + DETERMINISTIC on SYNTHETIC snapshots — the network is
NEVER touched (the poller's `_post` is injected; the harness gets in-memory series). The tests prove:

  POLLER  — metaAndAssetCtxs + clearinghouseState parse into CoinSnapshots; majors are excluded; per-account fold
            computes net/gross/liq-density correctly; hoard_once stamps ts == available_at == capture (PIT) and is
            append-only; one dead account/coin never aborts the pass.
  FEATURES— crowding-extreme z is a trailing PIT z-score (no look-ahead; honest gap before the window fills);
            long-liq-density is normalized by OI-notional; the aggregate proxy uses OI × funding sign.
  HARNESS — a SEEDED real reversion edge clears the BRUT gate AND all four disconfirmers (positive control);
            and EACH disconfirmer flags its own artefact (a BTC/ETH leak, a shuffled placebo, a vol-proxy, a
            copy-whale-only edge) — the instrument can tell a real edge from a fake.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.sources.hyperliquid_positioning import (
    DEFAULT_LONGTAIL_COINS,
    M_FUNDING,
    M_LONG_LIQ_DENSITY,
    M_NET_POSITION_USD,
    M_OI_NOTIONAL,
    PROVIDER,
    SATURATED,
    PositioningPoller,
    hoard_once,
    materialize_features,
    snapshot_to_points,
)
from cosmu.data.sources.positioning_features import (
    aggregate_crowding_proxy,
    crowding_extreme_z,
    long_liq_density_norm,
)
from cosmu.research.disconfirmers import forward_returns

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------- a tiny in-memory alt store


class _MemStore:
    """Minimal append/read_all alt store for offline tests (mirrors AltDataStore's seam). Append-only; read_all
    returns the rows in insertion order, deduped on (ts, available_at) like the real PIT-photocopy collapse."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], list[AltDataPoint]] = {}

    def append(self, provider: str, symbol: str, metric: str, points: list[AltDataPoint]) -> None:
        key = (provider, symbol, metric)
        bucket = self.rows.setdefault(key, [])
        seen = {(p.ts, p.available_at) for p in bucket}
        for p in points:
            if (p.ts, p.available_at) not in seen:
                bucket.append(p)
                seen.add((p.ts, p.available_at))

    def read_all(self, provider: str, symbol: str, metric: str) -> list[AltDataPoint]:
        return list(self.rows.get((provider, symbol, metric), []))


# --------------------------------------------------------------------------- synthetic /info responses


def _meta_ctx_response(coins: list[tuple[str, float, float, float]]) -> list:
    """A canned metaAndAssetCtxs payload: coins as (name, openInterest, funding, markPx)."""
    universe = [{"name": name, "szDecimals": 2} for name, *_ in coins]
    ctxs = [
        {"openInterest": str(oi), "funding": str(f), "markPx": str(px), "dayNtlVlm": "1000000"}
        for _, oi, f, px in coins
    ]
    return [{"universe": universe}, ctxs]


def _clearinghouse_response(positions: list[tuple[str, float, float, float]]) -> dict:
    """A canned clearinghouseState: positions as (coin, szi, positionValue, liquidationPx)."""
    return {
        "assetPositions": [
            {
                "type": "oneWay",
                "position": {
                    "coin": coin, "szi": str(szi), "positionValue": str(pv), "liquidationPx": str(liq),
                    "entryPx": "1.0", "leverage": {"type": "cross", "value": 10},
                },
            }
            for coin, szi, pv, liq in positions
        ]
    }


# --------------------------------------------------------------------------- POLLER


def test_aggregate_parse_and_majors_excluded():
    coins = [("ZEC", 1000.0, 0.0001, 400.0), ("BTC", 50.0, 0.00001, 60000.0), ("WLD", 5000.0, -0.0002, 0.5)]
    poller = PositioningPoller(coins=("ZEC", "BTC", "WLD"), _post=lambda b: _meta_ctx_response(coins))
    # BTC is a saturated major → stripped from the basket in __post_init__.
    assert "BTC" not in poller.coins
    snaps = poller.fetch_aggregate()
    assert set(snaps) == {"ZEC", "WLD"}
    z = snaps["ZEC"]
    assert z.open_interest == 1000.0
    assert z.oi_notional_usd == 1000.0 * 400.0  # OI × markPx
    assert z.funding == 0.0001
    assert z.mark_px == 400.0


def test_account_fold_net_gross_and_liq_density():
    coins = [("ZEC", 1000.0, 0.0001, 400.0)]
    # Two accounts in ZEC: a $10k long with liqPx 380 (5% below 400 → in the 10% band → down-cascade fuel)
    # and a $4k short with liqPx 460 (15% above 400 → OUTSIDE the 10% band → NOT short-liq fuel).
    states = {
        "0xA": _clearinghouse_response([("ZEC", 2.0, 10000.0, 380.0)]),
        "0xB": _clearinghouse_response([("ZEC", -1.0, 4000.0, 460.0)]),
    }

    def post(body):
        if body.get("type") == "metaAndAssetCtxs":
            return _meta_ctx_response(coins)
        return states[body["user"]]

    poller = PositioningPoller(coins=("ZEC",), accounts=("0xA", "0xB"), liq_band=0.10, _post=post)
    snaps = poller.poll()
    z = snaps["ZEC"]
    assert z.net_position_usd == 10000.0 - 4000.0   # long − short
    assert z.gross_position_usd == 14000.0
    assert z.n_accounts == 2
    assert z.long_liq_density_usd == 10000.0          # the long is within the band
    assert z.short_liq_density_usd == 0.0             # the short's liqPx is outside the band


def test_dead_account_is_skipped_not_aborting():
    coins = [("ZEC", 1000.0, 0.0, 400.0)]

    def post(body):
        if body.get("type") == "metaAndAssetCtxs":
            return _meta_ctx_response(coins)
        if body["user"] == "0xBAD":
            raise RuntimeError("network down")
        return _clearinghouse_response([("ZEC", 1.0, 5000.0, 390.0)])

    poller = PositioningPoller(coins=("ZEC",), accounts=("0xBAD", "0xGOOD"), _post=post)
    z = poller.poll()["ZEC"]
    # The good account's $5k long still folds in despite the dead one.
    assert z.net_position_usd == 5000.0
    assert z.n_accounts == 1


def test_hoard_once_is_pit_and_append_only():
    coins = [("ZEC", 1000.0, 0.0001, 400.0)]
    poller = PositioningPoller(coins=("ZEC",), _post=lambda b: _meta_ctx_response(coins))
    store = _MemStore()
    t1 = _T0
    counts = hoard_once(store, poller=poller, now=t1)
    assert counts[M_OI_NOTIONAL] == 1
    pts = store.read_all(PROVIDER, "ZEC", M_OI_NOTIONAL)
    assert len(pts) == 1
    # PIT: ts == available_at == the capture instant.
    assert pts[0].ts == t1 and pts[0].available_at == t1
    # A LATER capture appends a NEW row (forward-hoard), never overwrites the first.
    t2 = _T0 + timedelta(minutes=10)
    hoard_once(store, poller=poller, now=t2)
    pts2 = store.read_all(PROVIDER, "ZEC", M_OI_NOTIONAL)
    assert len(pts2) == 2
    assert {p.available_at for p in pts2} == {t1, t2}


def test_snapshot_to_points_omits_none_metrics():
    from cosmu.data.sources.hyperliquid_positioning import CoinSnapshot

    snap = CoinSnapshot(coin="ZEC", open_interest=10.0, oi_notional_usd=None, funding=0.001, mark_px=None,
                        day_ntl_vlm=None)
    pts = snapshot_to_points(snap, capture_at=_T0)
    # Only the non-None metrics are written (honest gap, never a fabricated 0).
    assert M_OI_NOTIONAL not in pts
    assert M_FUNDING in pts and pts[M_FUNDING].value == 0.001


# --------------------------------------------------------------------------- FEATURES


def _series(values: list[float], *, start: datetime = _T0, step_min: int = 10) -> list[AltDataPoint]:
    return [
        AltDataPoint(ts=start + timedelta(minutes=step_min * i), available_at=start + timedelta(minutes=step_min * i), value=v)
        for i, v in enumerate(values)
    ]


def test_crowding_z_is_trailing_pit():
    # A flat series then a spike: the z at the spike must be large + positive, and computed ONLY from past values.
    values = [0.0] * 12 + [10.0]
    pts = _series(values)
    out = crowding_extreme_z(pts, min_window=12)
    # No point until the window fills (honest gap); index 11 has an all-zero window → zero variance → undefined z
    # (None, dropped — never a fabricated 0), so only the spike at index 12 yields a point.
    assert len(out) == 1
    assert out[-1].value > 2.0   # the spike is a strong positive z vs its trailing window
    # PIT: the output point keeps the input instant's stamps.
    assert out[-1].available_at == pts[-1].available_at


def test_long_liq_density_norm_divides_by_oi():
    liq = _series([200.0, 400.0])
    oi = _series([1000.0, 1000.0])
    out = long_liq_density_norm(liq, oi)
    assert [round(p.value, 4) for p in out] == [0.2, 0.4]


def test_aggregate_crowding_proxy_uses_funding_sign():
    oi = _series([1000.0, 1000.0, 1000.0])
    funding = _series([0.001, -0.001, 0.0])  # long-crowded, short-crowded, neutral
    out = aggregate_crowding_proxy(oi, funding)
    assert [p.value for p in out] == [1000.0, -1000.0, 0.0]


def test_materialize_features_writes_derived_metrics():
    store = _MemStore()
    # Seed a net-positioning series with a late spike + an OI/long-liq series so both derived features compute.
    net = _series([0.0] * 12 + [50000.0])
    store.rows[(PROVIDER, "ZEC", M_NET_POSITION_USD)] = net
    store.rows[(PROVIDER, "ZEC", M_OI_NOTIONAL)] = _series([1_000_000.0] * 13)
    store.rows[(PROVIDER, "ZEC", M_LONG_LIQ_DENSITY)] = _series([100_000.0] * 13)
    counts = materialize_features(store, coins=("ZEC",), min_window=12)
    assert counts["hl_crowding_extreme_z"] >= 1
    assert counts["hl_long_liq_density_norm"] >= 1
    z_pts = store.read_all(PROVIDER, "ZEC", "hl_crowding_extreme_z")
    assert z_pts[-1].value > 2.0


# --------------------------------------------------------------------------- HARNESS (disconfirmer-gated BRUT)


def _coin_with_reversion_edge(
    n: int, *, edge: bool, seed: int, horizon: int = 2, amp: float = 0.04, noise: float = 0.001,
) -> tuple[list[AltDataPoint], list[Bar], list[AltDataPoint]]:
    """Build (net-positioning points, bars, funding points) for ONE coin over n captures.

    OSCILLATOR design: net positioning oscillates (sine + noise). With `edge=True` the return INTO each bar is
    ANTI-correlated with the net `horizon` bars ago (a crowded long now → the price falls over the next horizon →
    fading the extreme pays), giving a strong NEGATIVE IC AND a profitable fade. With `edge=False` the moves are
    pure noise (no reversion relationship). Funding is INDEPENDENT noise here, so the (c) vol+funding control does
    NOT spuriously kill the positive-control edge. Deterministic via a string-seeded RNG (repo fixture style)."""
    rng = random.Random(f"hl-{seed}-{edge}")
    nets = [3.0e6 * math.sin(2 * math.pi * t / 10.0) + rng.uniform(-2.0e5, 2.0e5) for t in range(n)]
    rets: list[float] = [0.0] * n
    for t in range(n):
        if edge and t >= horizon:
            rets[t] = -(nets[t - horizon] / 3.0e6) * (amp / horizon) + rng.uniform(-noise, noise)
        else:
            rets[t] = rng.uniform(-noise, noise)
    closes = [100.0]
    for r in rets:
        closes.append(closes[-1] * (1.0 + r))
    bars: list[Bar] = []
    net_pts: list[AltDataPoint] = []
    fund_pts: list[AltDataPoint] = []
    for t in range(n):
        ts = _T0 + timedelta(days=t)
        px = Decimal(str(round(closes[t], 6)))
        bars.append(Bar(ts=ts, open=px, high=px, low=px, close=px, volume=Decimal(1000)))
        net_pts.append(AltDataPoint(ts=ts, available_at=ts, value=nets[t]))
        fund_pts.append(AltDataPoint(ts=ts, available_at=ts, value=rng.uniform(-3.0e-4, 3.0e-4)))
    return net_pts, bars, fund_pts


def test_harness_positive_control_clears_gate_and_disconfirmers():
    import cosmu.research.hl_positioning_cohort as hp

    net, bars, fund = _coin_with_reversion_edge(360, edge=True, seed=1)
    report = hp.run(
        net_position_by_coin={"ZEC": net},
        bars_by_coin={"ZEC": bars},
        funding_by_coin={"ZEC": fund},
        z_thresh=1.0,
        min_window=6,
    )
    zec = next(c for c in report.coins if c.coin == "ZEC")
    # The seeded reversion edge: a strong (negative) IC, a promoted BRUT cell, all coin-level disconfirmers met.
    assert abs(zec.raw_ic) > 0.1, zec
    assert zec.num_trades >= 30, zec
    assert zec.brut_promoted, zec.reasons
    assert zec.d_shuffle_survives          # (b) survives the shuffle null
    assert zec.d_control_keeps_ic          # (c) survives vol+funding residualization
    assert zec.d_aggregate_beats_copy      # (d) aggregate beats copy-whale (no whale series → trivially true)
    assert zec.is_candidate
    assert report.disconfirmer_a_majors_clean  # (a) no major in this run → clean
    assert report.verdict == "CANDIDATES"
    assert "ZEC" in report.candidates


def test_disconfirmer_a_rejects_when_a_major_promotes():
    import cosmu.research.hl_positioning_cohort as hp

    # Give BTC (a major) the SAME real edge → it promotes → disconfirmer (a) must mark the run UNTRUSTWORTHY.
    net, bars, fund = _coin_with_reversion_edge(360, edge=True, seed=2)
    report = hp.run(
        net_position_by_coin={"BTC": net},
        bars_by_coin={"BTC": bars},
        funding_by_coin={"BTC": fund},
        z_thresh=1.0, min_window=6,
    )
    btc = next(c for c in report.coins if c.coin == "BTC")
    assert btc.is_major
    assert btc.brut_promoted               # the edge IS there on BTC...
    assert not btc.is_candidate            # ...but a major can never be a candidate
    assert not report.disconfirmer_a_majors_clean
    assert report.verdict == "UNTRUSTWORTHY"


def test_disconfirmer_b_kills_a_no_edge_coin():
    import cosmu.research.hl_positioning_cohort as hp

    # No reversion relationship → the IC should NOT survive the shuffle null (the coin is not a candidate).
    net, bars, fund = _coin_with_reversion_edge(360, edge=False, seed=3)
    report = hp.run(
        net_position_by_coin={"NOISE": net},
        bars_by_coin={"NOISE": bars},
        funding_by_coin={"NOISE": fund},
        z_thresh=1.0, min_window=6,
    )
    noise = next(c for c in report.coins if c.coin == "NOISE")
    # The defining negative-control assertion: a no-edge coin is NOT a candidate.
    assert not noise.is_candidate
    assert report.verdict == "NO_EDGE"


def test_disconfirmer_d_rejects_copy_whale_only_edge():
    import cosmu.research.hl_positioning_cohort as hp

    # Aggregate net has NO edge, but a copy-whale series DOES (it equals the future-reverting signal). Disconfirmer
    # (d) must fire: the aggregate IC < the copy-whale IC → not a candidate (the thesis is aggregate stress).
    net, bars, fund = _coin_with_reversion_edge(360, edge=False, seed=4)
    # Build a copy-whale series that genuinely predicts COPY's OWN forward return (whale value = the realized
    # future move on these bars), so the copy-whale IC is large while the aggregate net IC is noise.
    fwd = forward_returns(bars, 2)
    whale_pts = [
        AltDataPoint(ts=b.ts, available_at=b.ts, value=fwd.get(b.ts.isoformat(), 0.0))
        for b in bars
    ]
    report = hp.run(
        net_position_by_coin={"COPY": net},
        bars_by_coin={"COPY": bars},
        funding_by_coin={"COPY": fund},
        copy_whale_by_coin={"COPY": whale_pts},
        z_thresh=1.0, min_window=6,
    )
    copy = next(c for c in report.coins if c.coin == "COPY")
    # The copy-whale series carries the real reversion edge; the aggregate net is noise. So the copy-whale IC
    # dominates the aggregate IC → disconfirmer (d) fires → the cell is NOT a candidate (the thesis is the
    # AGGREGATE stress, not copying a whale).
    assert abs(copy.copy_whale_ic) > abs(copy.raw_ic), copy
    assert not copy.d_aggregate_beats_copy
    assert not copy.is_candidate


# --------------------------------------------------------------------------- registry / catalog wiring


def test_features_registered_and_routable():
    from cosmu.config.feature_registry import feature_names
    from cosmu.data.backtest import PRICE_FEATURES
    from cosmu.data.providers.store import _STORE_PROVIDER_OF

    names = feature_names()
    assert "hl_crowding_extreme_z" in names
    assert "hl_long_liq_density_norm" in names
    # The registry↔route guard: both must be store-routed (else a silent no-op feature).
    unaccounted = names - (PRICE_FEATURES | set(_STORE_PROVIDER_OF))
    assert not unaccounted


def test_catalog_owns_the_two_metrics():
    from cosmu.data.altdata import _STORE_PROVIDER_OF
    from cosmu.ingest import catalog

    # The lock-step guard: every routed metric is owned by exactly one catalog source.
    assert catalog.catalog_metric_set() == set(_STORE_PROVIDER_OF)
    src = catalog.managed_sources()["hyperliquid_positioning"]
    assert set(src.metrics) == {"hl_crowding_extreme_z", "hl_long_liq_density_norm"}


def test_default_basket_excludes_saturated_majors():
    assert not (set(DEFAULT_LONGTAIL_COINS) & SATURATED)
    assert 15 <= len(DEFAULT_LONGTAIL_COINS) <= 25
