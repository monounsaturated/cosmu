# intent: 6h vendor spend refresh job — fetch all vendor costs, check budget, emit alerts;
# run as `python -m cosmu.costs.refresh` (Railway cron or modal run).

from __future__ import annotations


def main() -> int:
    from datetime import UTC, datetime

    from cosmu.config.settings import get_settings
    from cosmu.costs.accounts import seed_accounts_from_env, sync_spend_from_ledger
    from cosmu.costs.alerts import check_account_strides, check_budget, emit_alerts
    from cosmu.costs.fetchers import refresh_vendor_costs
    from cosmu.knowledge.store import Store

    settings = get_settings()
    store = Store(settings=settings)
    spends = refresh_vendor_costs(store, settings)
    alerts = check_budget(spends, settings)
    emit_alerts(alerts, store, settings)

    # Modular compute-spend: register the account pool from env, reconcile each account's spend from the ledger
    # (this month), then fire the $15-fixed-stride notifier for any account that crossed a new stride.
    period = datetime.now(tz=UTC).strftime("%Y-%m")
    seeded = seed_accounts_from_env(store)
    synced = sync_spend_from_ledger(store, period=period)
    strides = check_account_strides(store, settings)

    vendors = ", ".join(s.vendor for s in spends)
    print(f"[cost_refresh] fetched {len(spends)} vendors: {vendors}")
    print(f"[cost_refresh] accounts: {seeded} seeded, {synced} reconciled, {len(strides)} stride alert(s)")
    if alerts:
        print(f"[cost_refresh] {len(alerts)} budget alert(s) emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
