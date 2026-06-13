# intent: the DAILY fee-routing process. Snapshot each crypto venue's current per-instrument fee into the
# point-in-time venue_fees store, then compute + persist the cheapest-legal-venue-per-asset routing map so the
# (future) live lane "knows where to send" and the operator can see the comparison. Runnable as a Railway cron
# (daily). inputs: the Store (+ catalog + trailing-30d volume); outputs: PIT venue_fees rows + a venue_fee_routing
# event carrying the full fee matrix. invariants: idempotent (PIT append; the */15 dedup primitive applies),
# offline-safe (catalog volume-tier fees as the baseline — a live ccxt fetchTradingFees pull is a keyed
# follow-up), read-only on the money path (PLANNING only; never sends an order). live OFF.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.data.alt_join import resolve_alt_store
from cosmu.data.providers._types import AltDataPoint
from cosmu.spine.fee_router import crypto_base_assets, fee_matrix
from cosmu.spine.venue import default_catalog


def refresh_venue_fees(store, *, catalog=None, volume_30d: float = 0.0, jurisdiction: str = "FR") -> dict:  # noqa: ANN001
    """Snapshot every crypto venue's per-instrument maker+taker fee (catalog volume-tier baseline) into the
    venue_fees PIT store under the (venue_id:symbol) key read_pit_fee expects, recompute the cheapest-legal-
    venue routing map, and emit it as a durable event. Returns {matrix, routed, snapshots}."""
    catalog = catalog or default_catalog()
    alt_store = resolve_alt_store(store.settings, store)
    now = datetime.now(tz=UTC)
    snapshots = 0
    for inst in catalog.instruments:
        try:
            v = catalog.venue(inst.venue_id)
        except KeyError:
            continue
        if v.kind != "crypto":
            continue
        maker, taker = v.effective_fee(volume_30d)
        key = f"{v.id}:{inst.symbol}"  # the store_symbol read_pit_fee builds — keep in lock-step
        for metric, bps in (("venue_fees_maker", maker), ("venue_fees_taker", taker)):
            try:
                alt_store.append("venue_fees", key, metric, [AltDataPoint(ts=now, available_at=now, value=float(bps))])
                snapshots += 1
            except Exception:  # noqa: BLE001 — a single snapshot write never aborts the refresh
                continue

    # Recompute the routing map FROM the fresh snapshots (store-backed reads now win over the catalog default).
    matrix = fee_matrix(catalog, side="taker", volume_30d=volume_30d, jurisdiction=jurisdiction, store=alt_store)
    routed = {b: m["best"] for b, m in matrix.items() if m["best"]}
    store.append_event(
        actor="master", kind="venue_fee_routing", ref_type="fees", ref_id="aggregate",
        payload={"jurisdiction": jurisdiction, "volume_30d": volume_30d,
                 "assets": len(matrix), "snapshots": snapshots, "routed": routed,
                 "matrix": {b: m["by_venue"] for b, m in matrix.items()}},
    )
    return {"matrix": matrix, "routed": routed, "snapshots": snapshots}


def _main() -> int:
    import os
    import sys

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    volume = 0.0
    juris = os.environ.get("LIVE_JURISDICTION", "FR")
    for i, a in enumerate(sys.argv[1:], 1):
        if a == "--volume" and i < len(sys.argv):
            volume = float(sys.argv[i + 1])
        if a == "--jurisdiction" and i < len(sys.argv):
            juris = sys.argv[i + 1]
    store = Store(Settings())
    result = refresh_venue_fees(store, volume_30d=volume, jurisdiction=juris)
    print(f"venue-fee routing refreshed — {len(result['matrix'])} assets, {result['snapshots']} fee snapshots, "
          f"jurisdiction={juris}, 30d-vol=${volume:,.0f}")
    print(f"{'asset':8s} {'best venue':16s} {'fee(bps)':>9s}   all venues")
    for base, m in sorted(result["matrix"].items()):
        allv = " ".join(f"{vid}:{bps}" for vid, bps in sorted(m["by_venue"].items(), key=lambda kv: kv[1]))
        print(f"  {base:6s} {str(m['best']):16s} {str(m['best_fee_bps']):>9s}   {allv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
