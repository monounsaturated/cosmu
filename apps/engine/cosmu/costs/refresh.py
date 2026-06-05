# intent: 6h vendor spend refresh job — fetch all vendor costs, check budget, emit alerts;
# run as `python -m cosmu.costs.refresh` (Railway cron or modal run).

from __future__ import annotations


def main() -> int:
    from cosmu.config.settings import get_settings
    from cosmu.costs.alerts import check_budget, emit_alerts
    from cosmu.costs.fetchers import refresh_vendor_costs
    from cosmu.knowledge.store import Store

    settings = get_settings()
    store = Store(settings=settings)
    spends = refresh_vendor_costs(store, settings)
    alerts = check_budget(spends, settings)
    emit_alerts(alerts, store, settings)
    vendors = ", ".join(s.vendor for s in spends)
    print(f"[cost_refresh] fetched {len(spends)} vendors: {vendors}")
    if alerts:
        print(f"[cost_refresh] {len(alerts)} budget alert(s) emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
