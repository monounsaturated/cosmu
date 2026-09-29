# intent: the FORWARD-ONLY Hyperliquid positioning hoard-logger — the keyless `/info` poller for the
# "long-tail perp positioning" data axis (the #1 next-data-axis recommendation, 2026-06-28). It snapshots,
# at each capture instant, the AGGREGATE market state (open-interest + funding + mark) of a CONFIGURABLE
# basket of 15-25 LONG-TAIL / HIP-3 perps (BTC/ETH/SOL/HYPE EXCLUDED — saturated, desk-visible), plus the
# OPTIONAL per-account `assetPositions` for a watchlist of addresses. Everything is APPEND-ONLY and stamped
# with the CAPTURE timestamp (ts == available_at == now): the snapshot is only knowable AT the poll instant,
# and on-chain immutability makes it PIT-clean by construction. We NEVER re-pull or overwrite a past instant —
# native history is shallow, so the only way to get depth is to hoard FORWARD (the sooner the cron runs, the
# sooner the Gate can rule, ~2-3 weeks).
#
# WHY this is structurally invisible & free: Hyperliquid is an on-chain DEX whose full clearinghouse state is
# served keyless from `api.hyperliquid.xyz/info`; a Wall-St desk does not (and largely cannot) reconstruct
# crowd positioning on a $1-50M/day perp from a public chain. $0 cost, zero keys, PIT-immutable.
#
# invariants: PURE w.r.t. the money path (this only READS a public API and WRITES alt_data points — no order,
# no gate); point-in-time (ts == available_at == capture-now; no look-ahead, no revision — a chain snapshot is
# final); one dead coin / one unreachable account is caught and skipped, never aborts the pass; offline-testable
# via an injected `_post` callable so the unit tests never touch the network. The DERIVED crowding/liq-density
# FEATURES are computed downstream from these hoarded snapshots (see positioning_features.py) — this module only
# HOARDS the raw observations, it does not compute any signal.

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cosmu.data.providers._types import AltDataPoint, _ssl_context

logger = logging.getLogger("cosmu.data.sources.hyperliquid_positioning")

_BASE_URL = "https://api.hyperliquid.xyz"
PROVIDER = "hyperliquid_positioning"  # the alt_data provider bucket key for every metric this poller writes

# Saturated majors — EXPLICITLY excluded from the long-tail basket (desk-visible, arb'd; the thesis is the tail).
SATURATED = frozenset({"BTC", "ETH", "SOL", "HYPE"})

# Default LONG-TAIL basket (15-25 names; volume-ordered from the 2026-06-28 smoke-poll, majors excluded). This is
# the CONFIGURABLE seed — the cron / a caller may override with `coins=`. Chosen for having enough OI/flow to carry
# a positioning signal while being thin enough to stay desk-invisible. Names that delist simply yield no snapshot
# (honest skip), never an abort; new HIP-3 names can be added here without touching the poller logic.
DEFAULT_LONGTAIL_COINS: tuple[str, ...] = (
    "ZEC", "PUMP", "NEAR", "AAVE", "XRP", "LIT", "SUI", "WLD", "JTO", "XPL",
    "FARTCOIN", "ADA", "AVAX", "TRUMP", "TAO", "DOGE", "JUP", "WIF", "ENA", "SYRUP",
)

# The aggregate metrics written per coin from `metaAndAssetCtxs` (market-wide, one ctx per coin per capture).
M_OPEN_INTEREST = "hl_open_interest"          # OI in base units (coin count)
M_OI_NOTIONAL = "hl_oi_notional_usd"          # OI × markPx — the $ notional the crowd holds
M_FUNDING = "hl_funding_rate"                 # the current 1h funding rate (signed; +ve = longs pay)
M_MARK_PX = "hl_mark_px"                      # mark price at capture (the reference for liq-density)
M_DAY_NTL_VLM = "hl_day_ntl_vlm"             # trailing 24h notional volume (a liquidity/thinness read)

# The per-account-aggregate metrics written per coin from the watchlist's `assetPositions`. These are the AGGREGATE
# crowd-stress observations the crowding/liq-density features are built from — NOT a per-account copy-trade feed.
M_NET_POSITION_USD = "hl_net_position_usd"    # Σ signed positionValue across the watchlist (long − short, $)
M_GROSS_POSITION_USD = "hl_gross_position_usd"  # Σ |positionValue| (gross crowd $ at risk)
M_LONG_LIQ_DENSITY = "hl_long_liq_density"    # Σ long positionValue whose liqPx is within X% BELOW mark, $
M_SHORT_LIQ_DENSITY = "hl_short_liq_density"  # Σ short positionValue whose liqPx is within X% ABOVE mark, $
M_N_ACCOUNTS = "hl_n_accounts_in_coin"       # how many watchlist accounts hold this coin (crowd breadth)

# All metrics, for downstream registration / iteration.
AGGREGATE_METRICS: tuple[str, ...] = (M_OPEN_INTEREST, M_OI_NOTIONAL, M_FUNDING, M_MARK_PX, M_DAY_NTL_VLM)
ACCOUNT_METRICS: tuple[str, ...] = (
    M_NET_POSITION_USD, M_GROSS_POSITION_USD, M_LONG_LIQ_DENSITY, M_SHORT_LIQ_DENSITY, M_N_ACCOUNTS,
)
ALL_METRICS: tuple[str, ...] = AGGREGATE_METRICS + ACCOUNT_METRICS

# Liquidation-density band: a position counts toward liq-density if its liqPx is within this fraction of the mark.
# 0.10 = within 10% of mark — the zone a 1-3d adverse move could sweep. Configurable per poll.
DEFAULT_LIQ_BAND = 0.10


PostJson = Callable[[dict], object]


def _default_post(body: dict) -> object:
    """POST a JSON body to the Hyperliquid public `/info` endpoint (keyless, certifi-backed SSL like the rest of
    the data layer). Returns the parsed JSON. Network/parse errors propagate to the per-call `_safe` guard."""
    req = urllib.request.Request(
        f"{_BASE_URL}/info",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "cosmu-engine/0.1"},
    )
    with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _f(v: object) -> float | None:
    """Parse a Hyperliquid string-number to float; None on anything unparseable (honest 'no value')."""
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class CoinSnapshot:
    """One coin's aggregate state at a single capture instant — the row each `metaAndAssetCtxs` poll yields."""

    coin: str
    open_interest: float | None
    oi_notional_usd: float | None
    funding: float | None
    mark_px: float | None
    day_ntl_vlm: float | None
    # per-account-aggregate fields (populated only when a watchlist is polled; None/0 otherwise)
    net_position_usd: float | None = None
    gross_position_usd: float | None = None
    long_liq_density_usd: float | None = None
    short_liq_density_usd: float | None = None
    n_accounts: int = 0


@dataclass
class PositioningPoller:
    """Forward-only keyless Hyperliquid positioning poller. `_post` is injectable (tests pass a canned callable;
    production POSTs to `/info`). Aggregate snapshots need no key/address; per-account aggregation needs a
    configured `accounts` watchlist (operator-supplied known large-account addresses).

    Cadence is the CALLER's concern (the cron schedules it ~every 10 min) — one `.poll()` is ONE capture instant.
    """

    coins: tuple[str, ...] = DEFAULT_LONGTAIL_COINS
    accounts: tuple[str, ...] = ()           # watchlist of 0x… addresses; empty → aggregate-only
    liq_band: float = DEFAULT_LIQ_BAND
    _post: PostJson = field(default=_default_post)

    def __post_init__(self) -> None:
        # Defensive: never let a saturated major sneak into the long-tail basket (the thesis is the tail).
        self.coins = tuple(c for c in self.coins if c not in SATURATED)

    # --- aggregate market state ----------------------------------------------------------------------------
    def fetch_aggregate(self) -> dict[str, CoinSnapshot]:
        """One `metaAndAssetCtxs` poll → {coin: CoinSnapshot} for every basket coin Hyperliquid currently lists.
        OI-notional is OI × markPx (the $ the crowd holds). A coin absent from the live universe is skipped."""
        data = self._post({"type": "metaAndAssetCtxs"})
        if not (isinstance(data, list) and len(data) >= 2):
            return {}
        meta, ctxs = data[0], data[1]
        universe = meta.get("universe", []) if isinstance(meta, dict) else []
        wanted = set(self.coins)
        out: dict[str, CoinSnapshot] = {}
        for i, u in enumerate(universe):
            name = u.get("name", "") if isinstance(u, dict) else ""
            if name not in wanted or u.get("isDelisted"):
                continue
            ctx = ctxs[i] if i < len(ctxs) and isinstance(ctxs[i], dict) else {}
            oi = _f(ctx.get("openInterest"))
            mark = _f(ctx.get("markPx"))
            oi_ntl = oi * mark if (oi is not None and mark is not None) else None
            out[name] = CoinSnapshot(
                coin=name,
                open_interest=oi,
                oi_notional_usd=oi_ntl,
                funding=_f(ctx.get("funding")),
                mark_px=mark,
                day_ntl_vlm=_f(ctx.get("dayNtlVlm")),
            )
        return out

    # --- per-account aggregation ---------------------------------------------------------------------------
    def _account_state(self, address: str) -> list[dict]:
        """One account's `clearinghouseState.assetPositions` (the raw position dicts). [] on any error/empty."""
        cs = self._post({"type": "clearinghouseState", "user": address})
        if not isinstance(cs, dict):
            return []
        return [ap for ap in cs.get("assetPositions", []) if isinstance(ap, dict)]

    def fold_accounts(self, snapshots: dict[str, CoinSnapshot]) -> dict[str, CoinSnapshot]:
        """Fold the watchlist's per-account positions INTO the aggregate snapshots, per coin: net/gross $ exposure,
        long/short liquidation-density within `liq_band` of mark, and the count of accounts holding the coin.

        Liq-density semantics: a LONG with liqPx within `liq_band` BELOW the mark is fuel for a down-cascade;
        a SHORT with liqPx within `liq_band` ABOVE the mark is fuel for an up-squeeze. We sum the $ positionValue
        in each band. One unreachable account is skipped (logged), never aborting the whole fold."""
        if not self.accounts:
            return snapshots
        agg: dict[str, dict[str, float]] = {
            c: {"net": 0.0, "gross": 0.0, "long_liq": 0.0, "short_liq": 0.0, "n": 0} for c in snapshots
        }
        for address in self.accounts:
            try:
                positions = self._account_state(address)
            except Exception as exc:  # noqa: BLE001 — one dead account never aborts the pass
                logger.warning("hl positioning: account %s failed (skipped): %s", address, exc)
                continue
            for ap in positions:
                pos = ap.get("position", {}) if isinstance(ap, dict) else {}
                coin = pos.get("coin", "")
                if coin not in agg:
                    continue
                snap = snapshots[coin]
                szi = _f(pos.get("szi"))
                pos_value = _f(pos.get("positionValue"))
                liq_px = _f(pos.get("liquidationPx"))
                if szi is None or pos_value is None or pos_value <= 0:
                    continue
                is_long = szi > 0
                signed = pos_value if is_long else -pos_value
                a = agg[coin]
                a["net"] += signed
                a["gross"] += pos_value
                a["n"] += 1
                mark = snap.mark_px
                if liq_px is not None and liq_px > 0 and mark is not None and mark > 0:
                    if is_long and 0 < (mark - liq_px) <= self.liq_band * mark:
                        a["long_liq"] += pos_value     # liqPx just below mark → down-cascade fuel
                    elif (not is_long) and 0 < (liq_px - mark) <= self.liq_band * mark:
                        a["short_liq"] += pos_value     # liqPx just above mark → up-squeeze fuel
        merged: dict[str, CoinSnapshot] = {}
        for coin, snap in snapshots.items():
            a = agg[coin]
            merged[coin] = CoinSnapshot(
                coin=coin,
                open_interest=snap.open_interest,
                oi_notional_usd=snap.oi_notional_usd,
                funding=snap.funding,
                mark_px=snap.mark_px,
                day_ntl_vlm=snap.day_ntl_vlm,
                net_position_usd=a["net"] if a["n"] else None,
                gross_position_usd=a["gross"] if a["n"] else None,
                long_liq_density_usd=a["long_liq"] if a["n"] else None,
                short_liq_density_usd=a["short_liq"] if a["n"] else None,
                n_accounts=int(a["n"]),
            )
        return merged

    # --- one capture ---------------------------------------------------------------------------------------
    def poll(self, *, now: datetime | None = None) -> dict[str, CoinSnapshot]:
        """ONE capture instant: aggregate state for every basket coin, folded with the watchlist accounts (if any).
        Pure read; the CALLER (the sink writer below) stamps + appends. `now` is accepted only for determinism in
        tests — the actual capture timestamp is set at WRITE time so ts == available_at == the real poll instant."""
        snapshots = self.fetch_aggregate()
        return self.fold_accounts(snapshots)


def snapshot_to_points(snap: CoinSnapshot, *, capture_at: datetime) -> dict[str, AltDataPoint]:
    """Turn ONE coin's snapshot into {metric: AltDataPoint} at the capture instant. ts == available_at ==
    capture_at — the snapshot is knowable only AT the poll instant (forward-hoard PIT discipline; no look-ahead,
    no revision). Metrics whose value is None (an unreported field) are simply omitted (honest gap, never a 0)."""
    pairs: list[tuple[str, float | None]] = [
        (M_OPEN_INTEREST, snap.open_interest),
        (M_OI_NOTIONAL, snap.oi_notional_usd),
        (M_FUNDING, snap.funding),
        (M_MARK_PX, snap.mark_px),
        (M_DAY_NTL_VLM, snap.day_ntl_vlm),
        (M_NET_POSITION_USD, snap.net_position_usd),
        (M_GROSS_POSITION_USD, snap.gross_position_usd),
        (M_LONG_LIQ_DENSITY, snap.long_liq_density_usd),
        (M_SHORT_LIQ_DENSITY, snap.short_liq_density_usd),
        (M_N_ACCOUNTS, float(snap.n_accounts) if snap.n_accounts else None),
    ]
    return {
        metric: AltDataPoint(ts=capture_at, available_at=capture_at, value=float(value))
        for metric, value in pairs
        if value is not None
    }


def hoard_once(
    store,  # noqa: ANN001 — AltDataStore | PgAltDataStore | ParquetAltDataStore (any .append seam)
    *,
    poller: PositioningPoller | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """ONE forward-hoard pass: poll the current Hyperliquid positioning snapshot and APPEND every metric point
    (stamped at the capture instant) into the alt-data `store`. Append-only — a re-run at a LATER instant just
    adds a new row per (coin, metric); a snapshot is NEVER re-pulled for a past instant. Returns per-metric
    append counts. Per-coin failure is caught and counted 0 so one dead coin never aborts the pass.

    The store key is symbol == coin (e.g. "ZEC"), provider == PROVIDER, metric == one of ALL_METRICS — exactly
    the (provider, symbol, metric, ts, available_at, value) shape every other alt source writes, so the existing
    PIT read/correlation/feature machinery sees it with zero new plumbing."""
    poller = poller or PositioningPoller()
    capture_at = now or datetime.now(UTC)
    try:
        snapshots = poller.poll(now=capture_at)
    except Exception as exc:  # noqa: BLE001 — a whole-pass network failure is logged, never crashes the cron
        logger.warning("hl positioning hoard: aggregate poll failed (0 written): %s", exc)
        return {}
    counts: dict[str, int] = {}
    for coin, snap in snapshots.items():
        points = snapshot_to_points(snap, capture_at=capture_at)
        for metric, point in points.items():
            try:
                store.append(PROVIDER, coin, metric, [point])
                counts[metric] = counts.get(metric, 0) + 1
            except Exception as exc:  # noqa: BLE001 — one bad write never aborts the rest of the snapshot
                logger.warning("hl positioning hoard: append %s/%s/%s failed: %s", PROVIDER, coin, metric, exc)
    logger.info("hl positioning hoard: %d coins, %d points across %d metrics",
                len(snapshots), sum(counts.values()), len(counts))
    return counts


def materialize_features(
    store,  # noqa: ANN001 — any .read_all / .append seam
    *,
    coins: tuple[str, ...] = DEFAULT_LONGTAIL_COINS,
    min_window: int | None = None,
) -> dict[str, int]:
    """Compute the two DERIVED registry features from the RAW hoarded snapshots and append them PIT-honest under
    the SAME provider, so the correlation scan + gate read them via the normal as-of join. For each coin:

      hl_crowding_extreme_z      = z-score of net positioning (per-account) vs its trailing window; falls back to
                                   the OI-notional × funding-sign aggregate proxy when no per-account net exists.
      hl_long_liq_density_norm   = long-liq density $ / OI-notional $ at each capture instant.

    Append-only + idempotent on (ts, available_at): a re-run appends only genuinely-new instants (the store's
    PIT-photocopy collapse handles a re-materialized overlap). Returns per-metric append counts. Pure read of the
    raw series + a derived write — never touches the gate/money path. Skips a coin with no/insufficient raw data
    (honest gap). The two features are computed STRICTLY from values whose available_at <= each output instant."""
    from cosmu.data.sources.positioning_features import (
        DEFAULT_MIN_WINDOW,
        aggregate_crowding_proxy,
        crowding_extreme_z,
        long_liq_density_norm,
    )
    from cosmu.ingest.pipeline import _append_fresh  # idempotent (ts, available_at) append

    mw = min_window if min_window is not None else DEFAULT_MIN_WINDOW
    counts: dict[str, int] = {}
    for coin in coins:
        try:
            net = store.read_all(PROVIDER, coin, M_NET_POSITION_USD)
            oi_ntl = store.read_all(PROVIDER, coin, M_OI_NOTIONAL)
            funding = store.read_all(PROVIDER, coin, M_FUNDING)
            long_liq = store.read_all(PROVIDER, coin, M_LONG_LIQ_DENSITY)
        except Exception as exc:  # noqa: BLE001 — one bad coin read never aborts the rest
            logger.warning("hl positioning materialize: read %s failed: %s", coin, exc)
            continue
        # Crowding: prefer the real per-account net series; fall back to the keyless aggregate proxy.
        net_series = net if net else aggregate_crowding_proxy(oi_ntl, funding)
        crowd_pts = crowding_extreme_z(net_series, min_window=mw)
        if crowd_pts:
            _append_fresh(store, PROVIDER, coin, "hl_crowding_extreme_z", crowd_pts)
            counts["hl_crowding_extreme_z"] = counts.get("hl_crowding_extreme_z", 0) + len(crowd_pts)
        liq_pts = long_liq_density_norm(long_liq, oi_ntl)
        if liq_pts:
            _append_fresh(store, PROVIDER, coin, "hl_long_liq_density_norm", liq_pts)
            counts["hl_long_liq_density_norm"] = counts.get("hl_long_liq_density_norm", 0) + len(liq_pts)
    return counts


def _main(argv: list[str] | None = None) -> int:
    """CLI: one forward-hoard pass into the configured hot alt-data store (the cron entrypoint). Reads the
    account watchlist from HL_POSITIONING_ACCOUNTS (comma-separated 0x… addresses) if set; aggregate-only otherwise.
    `python3 -m cosmu.data.sources.hyperliquid_positioning`."""
    import argparse
    import os

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="One forward-hoard pass of Hyperliquid long-tail positioning.")
    parser.add_argument("--coins", default="", help="comma-separated coin override (default = long-tail basket)")
    parser.add_argument("--accounts", default="", help="comma-separated 0x… watchlist (default = env or none)")
    args = parser.parse_args(argv)

    from cosmu.config.settings import get_settings
    from cosmu.data.altdata import hot_alt_store

    coins = tuple(c.strip() for c in args.coins.split(",") if c.strip()) or DEFAULT_LONGTAIL_COINS
    env_accounts = os.environ.get("HL_POSITIONING_ACCOUNTS", "")
    accounts = tuple(a.strip() for a in (args.accounts or env_accounts).split(",") if a.strip())
    poller = PositioningPoller(coins=coins, accounts=accounts)
    store = hot_alt_store(get_settings())
    counts = hoard_once(store, poller=poller)
    # Materialize the two derived registry features from the raw hoard accrued so far (idempotent; early passes
    # write nothing until the trailing window fills — an honest "not enough history yet", never a fabricated 0).
    feat_counts = materialize_features(store, coins=coins)
    print("HYPERLIQUID POSITIONING HOARD — one forward capture")
    for metric, n in sorted(counts.items()):
        print(f"  {metric:<26} {n:>4} coins")
    for metric, n in sorted(feat_counts.items()):
        print(f"  {metric:<26} {n:>4} feature-points (derived)")
    print(f"  {'TOTAL raw':<26} {sum(counts.values()):>4} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
