# intent: the bounded, cron-able auto-research loop — remove the human from the loop. TWO INDEPENDENT steps per pass: (1) ingest a fresh free-data pass into the append-only store (self-contained + persisting), and (2) an OPT-IN, best-effort run of the deterministic cross-asset gate (the no-FDR/trials=5 path the audit flagged as LEAKY) against that store, default OFF on the --ingest cron so a flaky gate read can never abort the ingest step; inputs: the Store + the append-only alt-data store; outputs: per-source ingest counts (durable on their own) and, when the gate runs, a CrossAssetVerdict + a persisted gate_verdicts row + a cross_asset_gate_run event; invariants: BOUNDED (one pass per call, --passes N — NOT a daemon), deterministic scorer out of any LLM's reach, the news LLM is ingest-only (cached), the gate step is best-effort (its failure is caught + logged, never aborts ingest), and the live/synthetic data_source flag stays honest exactly like the API.

from __future__ import annotations

import json
import logging

from cosmu.config.settings import get_settings
from cosmu.data.altdata import StoreBackedAltProvider
from cosmu.data.sources.multiasset import MULTIASSET_METRICS
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.verdict_log import METHOD_CROSS_ASSET_NOFDR
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.research.gate import CrossAssetVerdict, evaluate_cross_asset_ablation

logger = logging.getLogger("cosmu.research.loop")


def _default_alt_store():  # noqa: ANN202 - AltDataStore | PgAltDataStore
    """The HOT alt-data write store via the single hot_alt_store factory (postgres → PgAltDataStore over the
    Store, else the JSONL AltDataStore) — the store a scheduled `cosmu.ingest.run` pass fills."""
    from cosmu.data.altdata import hot_alt_store

    return hot_alt_store(get_settings())


def _has_cross_asset_data(alt_store) -> bool:  # noqa: ANN001
    """True once the two cross-asset transfer series (prediction-market risk_on + FRED macro_regime) are
    ingested — exactly what arm (3) needs to differ from price-only. Same predicate the API uses."""
    return bool(alt_store.read_all("polymarket", "MARKET", "pm_risk_on")) and bool(
        alt_store.read_all("fred", "MARKET", "macro_regime")
    )


def _persist_verdict(store: Store, verdict: CrossAssetVerdict, data_source: str) -> None:
    """Persist the gate verdict to gate_verdicts + emit a cross_asset_gate_run event — mirrors the API's
    POST /research/cross-asset-gate handler so the cron loop and the UI write the SAME rows/events. The
    `method` marker tags this as the no-FDR/trials=5 cross-asset ablation path so the experiments read path
    can never let it masquerade as a BH-FDR-gated survivor."""
    payload = {
        "method": METHOD_CROSS_ASSET_NOFDR,
        "decision": verdict.decision,
        "passed": verdict.passed,
        "price_only_return": verdict.price_only_return,
        "single_alt_return": verdict.single_alt_return,
        "xasset_return": verdict.xasset_return,
        "buy_and_hold_return": verdict.buy_and_hold_return,
        "xasset_dsr": verdict.xasset_dsr,
        "single_alt_dsr": verdict.single_alt_dsr,
        "cscv_pbo": verdict.cscv_pbo,
        "rank_consistency": verdict.rank_consistency,  # advisory IS↔OOS rank transfer (RESEARCH_LESSONS §3)
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


def _run_cross_asset_gate(store: Store, alt_store) -> CrossAssetVerdict:  # noqa: ANN001
    """Run the four-arm cross-asset ablation against the ingested store (data_source "live", news read as a
    pre-standardized numeric series → ZERO LLM) when the two cross-asset transfer series are present, else
    against the labelled synthetic fixture (data_source "synthetic"). Persists the verdict + emits the event,
    then returns it. The scorer is deterministic and out of any LLM's reach.

    NOTE: this is the no-FDR/trials=5 cross-asset ablation path the audit flagged as LEAKY — its verdicts are
    method-tagged METHOD_CROSS_ASSET_NOFDR so they can never masquerade as FDR-gated survivors. It is OPT-IN
    (default off for the ingest cron) and best-effort: the caller wraps it so a failure here never aborts the
    independent ingest step."""
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


def auto_research_pass(
    store: Store, *, ingest: bool = False, cross_asset_gate: bool = True, alt_store=None, providers=None  # noqa: ANN001
) -> CrossAssetVerdict | None:
    """ONE bounded auto-research pass — no human in the loop. Two INDEPENDENT steps:

      1) (optional) INGEST a fresh free-data pass into the append-only store. This is self-contained: run_once
         persists per-source as it goes and per-source failure is already caught, so the ingest result stands
         on its own.
      2) (opt-in) run the deterministic cross-asset gate against that store. This is the no-FDR/trials=5
         ablation path the audit flagged as LEAKY, so it is best-effort and DEFAULT OFF on the ingest cron:
         any failure here (e.g. a Supabase fee-read hiccup) is caught + logged and NEVER aborts the ingest
         step. The honest BH-FDR cohort path is elsewhere and untouched.

    Returns the cross-asset verdict when the gate ran (and succeeded), else None — so an ingest-only cron pass
    that skips (or fails) the leaky gate still completes and persists its ingest work."""
    alt_store = alt_store if alt_store is not None else _default_alt_store()
    if ingest:
        from cosmu.ingest.health import check_ingest_health
        from cosmu.ingest.run import run_once
        from cosmu.notify.slack import SlackNotifier

        # Self-contained + persisting: run_once banks per-source counts as it goes, so the ingest step's work
        # is durable regardless of what the optional gate step does next.
        counts = run_once(alt_store, providers=providers)
        # The stale-source alarm (deep review): a pass where EVERY source returned 0, or providers gone quiet
        # for days, pages Slack ONCE per cooldown window — silent data death no longer needs someone to look.
        # Best-effort by invariant: a health-check failure never touches the ingest result.
        check_ingest_health(store, counts, notifier=SlackNotifier.from_env())

    if not cross_asset_gate:
        return None

    try:
        return _run_cross_asset_gate(store, alt_store)
    except Exception:  # noqa: BLE001 - the leaky gate is best-effort; it must never abort the ingest step
        # The ingest step (if any) has already persisted independently above. Log + swallow so a flaky gate
        # read (Supabase connect/fee-read hiccup) can't fail the whole cron pass.
        logger.exception("cross-asset gate step failed; ingest step (if any) already persisted independently")
        return None


def _print_verdict(idx: int, verdict: CrossAssetVerdict) -> None:
    print(f"PASS {idx} — CROSS-ASSET GATE [{verdict.data_source}] — {verdict.decision}")
    print(f"  cross-asset+alt arm:    return {verdict.xasset_return:+.3f} · deflated Sharpe {verdict.xasset_dsr}")
    print(f"  single-asset+alt arm:   return {verdict.single_alt_return:+.3f} · deflated Sharpe {verdict.single_alt_dsr}")
    print(f"  single-asset price arm: return {verdict.price_only_return:+.3f}")
    print(f"  buy & hold (all):       return {verdict.buy_and_hold_return:+.3f}")
    _rc = verdict.rank_consistency
    _rc_note = "n/a" if _rc is None else (f"{_rc:+.2f}" + (" ⚠ curve-fit smell" if _rc < -0.5 else ""))
    print(f"  CSCV PBO {verdict.cscv_pbo} · IS→OOS rank-consistency {_rc_note} · regimes {verdict.regimes_positive} · trades {verdict.num_trades} · maxDD {verdict.max_drawdown} · attempts {verdict.attempts}")
    if verdict.reasons:
        print(f"  failed checks: {', '.join(verdict.reasons)}")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bounded auto-research loop: ingest free data and/or run the cross-asset gate (no keys).")
    parser.add_argument("--passes", type=int, default=1, help="number of bounded passes (default 1)")
    parser.add_argument("--ingest", action="store_true", help="run a fresh free-data ingest pass each pass")
    # The cross-asset ablation is the no-FDR/trials=5 path the audit flagged as LEAKY. It is OPT-IN and, on the
    # ingest cron (--ingest), DEFAULT OFF so a flaky gate read can never fail an otherwise-good ingest pass.
    # Pass --cross-asset-gate to run it anyway; without --ingest it runs by default (the standalone gate CLI).
    parser.add_argument(
        "--cross-asset-gate", dest="cross_asset_gate", action="store_true", default=None,
        help="run the (leaky, no-FDR) cross-asset ablation after ingest — default OFF on the --ingest cron",
    )
    args = parser.parse_args(argv)

    # When the gate flag is left unset: skip the leaky gate on the ingest cron, run it on a bare gate invocation.
    cross_asset_gate = (not args.ingest) if args.cross_asset_gate is None else args.cross_asset_gate

    store = Store(get_settings())
    last: CrossAssetVerdict | None = None
    for i in range(max(1, args.passes)):
        verdict = auto_research_pass(store, ingest=args.ingest, cross_asset_gate=cross_asset_gate)
        if verdict is not None:
            last = verdict
            _print_verdict(i + 1, verdict)
        else:
            print(f"PASS {i + 1} — INGEST-ONLY (cross-asset gate skipped)")
    # Ingest-only passes have no verdict to pass/fail on → success once they complete without raising.
    if last is None:
        return 0
    return 0 if last.passed else 1


if __name__ == "__main__":
    raise SystemExit(_main())
