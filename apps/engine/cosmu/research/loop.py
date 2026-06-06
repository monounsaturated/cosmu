# intent: the bounded, cron-able auto-research loop — remove the human from the loop, run the deterministic cross-asset gate against real ingested free data (or a labelled synthetic fallback), persist the verdict + emit an event, all with ZERO LLM in the gate/scoring path; inputs: the Store + the append-only alt-data store; outputs: a CrossAssetVerdict per pass, a persisted gate_verdicts row, and a cross_asset_gate_run event; invariants: BOUNDED (one pass per call, --passes N — NOT a daemon), deterministic scorer out of any LLM's reach, the news LLM is ingest-only (cached), and the live/synthetic data_source flag stays honest exactly like the API.

from __future__ import annotations

import json

from cosmu.config.settings import get_settings
from cosmu.data.altdata import StoreBackedAltProvider
from cosmu.data.sources.multiasset import MULTIASSET_METRICS
from cosmu.knowledge.store import Store, utcnow
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.research.gate import CrossAssetVerdict, evaluate_cross_asset_ablation


def _default_alt_store():  # noqa: ANN202 - AltDataStore | PgAltDataStore
    """Pick the alt-data backend the SAME way the API + ingest CLI do: postgres → PgAltDataStore over the
    Store, else the JSONL AltDataStore. This is the store a scheduled `cosmu.ingest.run` pass fills."""
    settings = get_settings()
    if settings.database_url.startswith("postgres://") or settings.database_url.startswith("postgresql://"):
        from cosmu.data.altdata import PgAltDataStore

        return PgAltDataStore(Store(settings))
    from cosmu.data.altdata import AltDataStore

    return AltDataStore()


def _has_cross_asset_data(alt_store) -> bool:  # noqa: ANN001
    """True once the two cross-asset transfer series (prediction-market risk_on + FRED macro_regime) are
    ingested — exactly what arm (3) needs to differ from price-only. Same predicate the API uses."""
    return bool(alt_store.read_all("polymarket", "MARKET", "pm_risk_on")) and bool(
        alt_store.read_all("fred", "MARKET", "macro_regime")
    )


def _persist_verdict(store: Store, verdict: CrossAssetVerdict, data_source: str) -> None:
    """Persist the gate verdict to gate_verdicts + emit a cross_asset_gate_run event — mirrors the API's
    POST /research/cross-asset-gate handler so the cron loop and the UI write the SAME rows/events."""
    payload = {
        "decision": verdict.decision,
        "passed": verdict.passed,
        "price_only_return": verdict.price_only_return,
        "single_alt_return": verdict.single_alt_return,
        "xasset_return": verdict.xasset_return,
        "buy_and_hold_return": verdict.buy_and_hold_return,
        "xasset_dsr": verdict.xasset_dsr,
        "single_alt_dsr": verdict.single_alt_dsr,
        "cscv_pbo": verdict.cscv_pbo,
        "regimes_positive": verdict.regimes_positive,
        "num_trades": verdict.num_trades,
        "max_drawdown": verdict.max_drawdown,
        "attempts": verdict.attempts,
        "drop_one_source": [{"source": d.source, "sharpe_without": d.sharpe_without, "delta": d.delta} for d in verdict.drop_one_source],
        "drop_one_class": [{"asset_class": c.asset_class, "sharpe_without": c.sharpe_without, "delta": c.delta} for c in verdict.drop_one_class],
        "reasons": verdict.reasons,
        "bar": verdict.bar,
        "data_source": data_source,
    }
    store.rows(
        "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
        (utcnow(), verdict.decision, data_source, json.dumps(payload, sort_keys=True)),
    )
    store.append_event(
        actor="master",
        kind="cross_asset_gate_run",
        ref_type="gate",
        payload={"decision": verdict.decision, "data_source": data_source},
    )


def auto_research_pass(store: Store, *, ingest: bool = False, alt_store=None, providers=None) -> CrossAssetVerdict:  # noqa: ANN001
    """ONE bounded auto-research pass — no human in the loop. Optionally ingest a fresh free-data pass first,
    then run evaluate_cross_asset_ablation against a StoreBackedAltProvider when the store holds the two
    cross-asset transfer series (data_source "live", news read as a pre-standardized numeric series → ZERO
    LLM), else fall back to the labelled synthetic fixture (data_source "synthetic"). Persists the verdict +
    emits the event, then returns it. The scorer is deterministic and out of any LLM's reach."""
    alt_store = alt_store if alt_store is not None else _default_alt_store()
    if ingest:
        from cosmu.ingest.run import run_once

        run_once(alt_store, providers=providers)

    market_by_class, synth_alt, synth_news = synthetic_cross_asset_inputs()
    if _has_cross_asset_data(alt_store):
        provider = StoreBackedAltProvider(
            alt_store,
            market_wide=frozenset({"pm_risk_on", "macro_regime", "putcall_ratio", *MULTIASSET_METRICS}),
        )
        verdict = evaluate_cross_asset_ablation(market_by_class, provider, None, store)
        data_source = "live"
    else:
        verdict = evaluate_cross_asset_ablation(market_by_class, synth_alt, synth_news, store)
        data_source = "synthetic"

    verdict.data_source = data_source
    _persist_verdict(store, verdict, data_source)
    return verdict


def _print_verdict(idx: int, verdict: CrossAssetVerdict) -> None:
    print(f"PASS {idx} — CROSS-ASSET GATE [{verdict.data_source}] — {verdict.decision}")
    print(f"  cross-asset+alt arm:    return {verdict.xasset_return:+.3f} · deflated Sharpe {verdict.xasset_dsr}")
    print(f"  single-asset+alt arm:   return {verdict.single_alt_return:+.3f} · deflated Sharpe {verdict.single_alt_dsr}")
    print(f"  single-asset price arm: return {verdict.price_only_return:+.3f}")
    print(f"  buy & hold (all):       return {verdict.buy_and_hold_return:+.3f}")
    print(f"  CSCV PBO {verdict.cscv_pbo} · regimes {verdict.regimes_positive} · trades {verdict.num_trades} · maxDD {verdict.max_drawdown} · attempts {verdict.attempts}")
    if verdict.reasons:
        print(f"  failed checks: {', '.join(verdict.reasons)}")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bounded auto-research loop: run the cross-asset gate N times (no keys).")
    parser.add_argument("--passes", type=int, default=1, help="number of bounded passes (default 1)")
    parser.add_argument("--ingest", action="store_true", help="run a fresh free-data ingest pass before each gate run")
    args = parser.parse_args(argv)

    store = Store(get_settings())
    last: CrossAssetVerdict | None = None
    for i in range(max(1, args.passes)):
        last = auto_research_pass(store, ingest=args.ingest)
        _print_verdict(i + 1, last)
    return 0 if (last is not None and last.passed) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
