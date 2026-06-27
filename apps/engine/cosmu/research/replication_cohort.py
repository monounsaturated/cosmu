# intent: the INDEPENDENT REPLICATION-COHORT step (R3) — the GWAS discipline that "replication is the final
# arbiter, not FDR" (cross-disciplinary playbook 2026-06-26, bridge #5 + the meta-lesson "validation lives on data
# the discovery never touched"). The R1 discovery Gate (master.cohort.promote_cohort: DSR>=0.95 + real holdout +
# BH-FDR q=0.10) controls overfitting WITHIN the discovery data, but it cannot catch a survivor that is a
# single-CELL fluke — an edge that exists only on the exact symbols/venue it was mined on. R3 takes a Gate
# survivor's FROZEN spec (params_hash, NO refit) and re-runs it on 3-5 HELD-OUT symbols/venues it was NOT
# discovered on. It demands a REPLICATION QUORUM (>= 2 of N held-out cells replicate net-of-fees) before the
# survivor is deemed credible. No replication => the BRUT per-combo Gate passed a single-cell overfit.
#
# WHERE IT SITS — the staged R-lane (a credibility ladder, each stage a DIFFERENT axis of robustness):
#   R1  Discovery Gate (existing, master.cohort.promote_cohort) — DSR>=0.95 + real purged/embargoed holdout +
#       BH-FDR across the cohort. Controls overfitting in the TIME axis on the discovery universe. Output: a
#       "Gate survivor" with a FROZEN promotion (master.promotion.freeze_promotion -> params_hash).
#   R2  Parameter robustness (existing, equity_taa_robustness) — the edge survives a param-NEIGHBOURHOOD sweep
#       (fee / start-date / breadth). Robustness in PARAMETER space.
#   R3  Independent replication (THIS MODULE) — the FROZEN edge replicates on HELD-OUT symbols/venues the
#       discovery never touched. Robustness in DATA space — the GWAS final arbiter.
#
# WHY THIS IS HONEST, NOT GATE-LOOSENING: R3 is an ADDITIONAL credibility gate stacked ON TOP of R1. It changes
# NO threshold in GateSettings / research.gate.PREREGISTERED_BAR (those stay LOCKED). A survivor must FIRST clear
# the unchanged R1 Gate; R3 can only DEMOTE a credibility claim, never promote past R1. R3 registers NO trials —
# it is CONFIRMATION on independent data, not a fresh search, so it adds no multiple-testing inflation (that is
# exactly the GWAS reason replication, not a wider FDR, is the final arbiter).
#
# inputs: a FrozenSurvivor (id/label + frozen NUMERIC params + the discovery universe + a no-refit `replay`
#   callable) + a list of held-out symbols + an optional Store (durable persist) + an optional expected
#   params_hash (drift pin). outputs: a ReplicationReport (verdict REPLICATED | NOT-REPLICATED | INSUFFICIENT-DATA
#   | DRIFT, the per-cell net-of-fee stats, the quorum count). invariants: deterministic + keyless (no LLM, no
#   network); held-out symbols MUST be disjoint from the discovery universe (else they are not held out); a
#   params_hash mismatch FAILS CLOSED (verdict DRIFT — a re-fit, not the frozen spec); a persist failure NEVER
#   raises into the research path. Propose/measure-only — moves no money; zero LLM on this path.

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from cosmu.knowledge.store import Store, utcnow
from cosmu.master.promotion import params_hash
from cosmu.research import equity_faber_gtaa as gtaa

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------------------------
# R3 replication credibility — ADDITIONAL to the LOCKED R1 Gate; never loosens a single threshold.
# --------------------------------------------------------------------------------------------------------------

# Minimum forward observations on ONE held-out symbol before its per-cell Sharpe/maxDD is trustworthy enough to
# vote. 36 monthly obs (3y) is the same order as the discovery holdout; below it a single cell's risk-adjusted
# stat is too noisy to count as a replication. A too-short cell does NOT vote (it cannot replicate) — fail-closed.
MIN_CELL_OBS = 36
# The GWAS replication quorum: at least this many of the N held-out cells must replicate net-of-fees before the
# survivor is credible. 2 is the minimum that distinguishes "the edge travels" from "one lucky second cell".
DEFAULT_QUORUM = 2
# "Materially lower drawdown" — the SAME 0.75 bar equity_faber_gtaa.validate() uses for its deployment check. A
# trend-timing rule's documented edge in a strong bull is drawdown reduction, not out-Sharpe-ing buy-and-hold, so
# a cell replicates on EITHER a risk-adjusted (Sharpe) beat OR a materially lower maxDD — the rule's real edge.
MATERIAL_DD_REDUCTION = 0.75


@dataclass(frozen=True)
class CellRun:
    """The realized net-of-fee outcome of one FROZEN replay on a held-out symbol — the raw numbers, BEFORE the
    replication predicate is applied. `net_*` are the frozen rule timed on the held-out symbol; `buy_and_hold_*`
    are buying-and-holding that same symbol over the same months (the risk-adjusted reference the edge must beat)."""

    n_obs: int
    net_return: float
    net_sharpe: float
    net_max_dd: float
    buy_and_hold_return: float
    buy_and_hold_sharpe: float
    buy_and_hold_max_dd: float


@dataclass(frozen=True)
class FrozenSurvivor:
    """A Gate (R1) survivor carried into R3 by its FROZEN spec — the params are hashed (the drift pin) and the
    `replay` callable runs the frozen rule WITHOUT refitting any parameter (it closes over `params`). The replay
    takes ONE held-out symbol and returns its realized net-of-fee stats, or None when that symbol has no data."""

    id: str
    label: str
    params: dict[str, float]                 # the frozen NUMERIC params — exactly what params_hash pins
    discovery_universe: tuple[str, ...]      # the symbols the survivor was discovered on (held-out must be disjoint)
    replay: Callable[[str], CellRun | None]  # symbol -> frozen-rule net-of-fee stats, or None if no held-out data
    venue: str = "equity"


@dataclass(frozen=True)
class ReplicationCell:
    """One held-out cell's verdict — the frozen rule's net-of-fee outcome plus whether it REPLICATED."""

    symbol: str
    venue: str
    n_obs: int
    net_return: float
    net_sharpe: float
    net_max_dd: float
    buy_and_hold_return: float
    buy_and_hold_sharpe: float
    buy_and_hold_max_dd: float
    sharpe_beat: bool
    dd_beat: bool
    replicated: bool
    note: str = ""


@dataclass
class ReplicationReport:
    survivor_id: str
    label: str
    params_hash: str
    venue: str
    discovery_universe: list[str]
    held_out: list[str]
    quorum: int
    n_cells: int
    n_replicated: int
    verdict: str          # REPLICATED | NOT-REPLICATED | INSUFFICIENT-DATA | DRIFT
    credible: bool
    headline: str
    cells: list[ReplicationCell] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def cell_replicates(run: CellRun) -> tuple[bool, bool, bool]:
    """Does ONE held-out cell replicate the frozen edge net-of-fees? Returns (replicated, sharpe_beat, dd_beat).
    A cell replicates iff it has enough obs AND is net-positive after fees AND beats buy-and-hold on EITHER a
    risk-adjusted (Sharpe) basis OR a materially-lower drawdown — the SAME deployment bar equity_faber_gtaa uses.
    A too-short or net-negative cell never replicates (fail-closed)."""
    sharpe_beat = run.net_sharpe >= run.buy_and_hold_sharpe
    dd_beat = run.net_max_dd <= run.buy_and_hold_max_dd * MATERIAL_DD_REDUCTION
    enough = run.n_obs >= MIN_CELL_OBS
    replicated = bool(enough and run.net_return > 0 and (sharpe_beat or dd_beat))
    return replicated, sharpe_beat, dd_beat


def run_replication_cohort(
    survivor: FrozenSurvivor,
    held_out_symbols: list[str],
    *,
    quorum: int = DEFAULT_QUORUM,
    expected_params_hash: str | None = None,
) -> ReplicationReport:
    """Re-run a FROZEN survivor on HELD-OUT symbols (no refit) and judge replication by quorum. `expected_params_hash`
    (e.g. read off the strategy_promotions freeze record) pins the spec: a mismatch means the params were re-fit, so
    R3 FAILS CLOSED with verdict DRIFT and judges nothing. Held-out symbols overlapping the discovery universe are
    dropped (they are not held out). Deterministic; registers NO trials (replication is confirmation, not a search)."""
    phash = params_hash(dict(survivor.params))
    disc = sorted(survivor.discovery_universe)
    notes: list[str] = []

    # NO-REFIT enforcement: the frozen params must match what the Gate promoted. A mismatch is a re-fit, not the
    # frozen spec — refuse to judge (fail-closed), never silently replicate a drifted recipe.
    if expected_params_hash is not None and phash != expected_params_hash:
        return ReplicationReport(
            survivor_id=survivor.id, label=survivor.label, params_hash=phash, venue=survivor.venue,
            discovery_universe=disc, held_out=[], quorum=quorum, n_cells=0, n_replicated=0,
            verdict="DRIFT", credible=False,
            headline=(f"params_hash drift — frozen spec was re-fit ({phash[:12]} != expected "
                      f"{expected_params_hash[:12]}); replication REFUSED (fail-closed)"),
            notes=[f"expected params_hash {expected_params_hash}", f"computed params_hash {phash}"],
        )

    disc_set = {s.upper() for s in survivor.discovery_universe}
    held = [s for s in held_out_symbols if s.upper() not in disc_set]
    overlap = [s for s in held_out_symbols if s.upper() in disc_set]
    if overlap:
        notes.append(f"excluded {overlap} — they overlap the discovery universe (not held out)")

    cells: list[ReplicationCell] = []
    for sym in held:
        try:
            run = survivor.replay(sym)
        except Exception as exc:  # noqa: BLE001 — one held-out symbol that can't load is an honest skip, not a crash
            notes.append(f"{sym}: replay error {type(exc).__name__}: {exc}")
            continue
        if run is None or run.n_obs == 0:
            notes.append(f"{sym}: no held-out data (skipped)")
            continue
        replicated, sharpe_beat, dd_beat = cell_replicates(run)
        note = "" if run.n_obs >= MIN_CELL_OBS else f"only {run.n_obs} obs (< {MIN_CELL_OBS}) — cannot vote"
        cells.append(ReplicationCell(
            symbol=sym, venue=survivor.venue, n_obs=run.n_obs,
            net_return=round(run.net_return, 6), net_sharpe=round(run.net_sharpe, 4),
            net_max_dd=round(run.net_max_dd, 6), buy_and_hold_return=round(run.buy_and_hold_return, 6),
            buy_and_hold_sharpe=round(run.buy_and_hold_sharpe, 4), buy_and_hold_max_dd=round(run.buy_and_hold_max_dd, 6),
            sharpe_beat=sharpe_beat, dd_beat=dd_beat, replicated=replicated, note=note,
        ))

    n_rep = sum(1 for c in cells if c.replicated)
    n_cells = len(cells)
    if n_cells < quorum:
        verdict, credible = "INSUFFICIENT-DATA", False
        headline = (f"only {n_cells} held-out cell(s) ran (< quorum {quorum}) — cannot judge replication "
                    f"(need {quorum} held-out symbols with data the survivor never saw)")
    elif n_rep >= quorum:
        verdict, credible = "REPLICATED", True
        headline = (f"{n_rep}/{n_cells} held-out cells replicated net-of-fees (>= quorum {quorum}) — "
                    f"{survivor.label} is CREDIBLE (the frozen edge travels off its discovery universe)")
    else:
        verdict, credible = "NOT-REPLICATED", False
        headline = (f"only {n_rep}/{n_cells} held-out cells replicated (< quorum {quorum}) — single-cell overfit "
                    f"risk: the BRUT per-combo Gate passed an edge that does NOT travel off its discovery universe")

    return ReplicationReport(
        survivor_id=survivor.id, label=survivor.label, params_hash=phash, venue=survivor.venue,
        discovery_universe=disc, held_out=held, quorum=quorum, n_cells=n_cells, n_replicated=n_rep,
        verdict=verdict, credible=credible, headline=headline, cells=cells, notes=notes,
    )


# --------------------------------------------------------------------------------------------------------------
# Durable record — operationalize the R3 lane: one queryable gate_verdicts row + an event, best-effort/offline-safe.
# --------------------------------------------------------------------------------------------------------------

# Payload marker so the read path can tell an R3 REPLICATION verdict apart from an R1 funding pass. An R3 row's
# `decision` is its own verdict string (REPLICATED / NOT-REPLICATED / ...), which can NEVER collide with the
# funding 'PASS' — so a replication record can never masquerade as a money-moving gate pass.
METHOD_REPLICATION_COHORT = "independent_replication_cohort"


def persist_replication_verdict(store: Store, report: ReplicationReport) -> bool:
    """Write ONE `gate_verdicts` row (payload kind='replication') + a `replication_cohort_run` event capturing the
    R3 verdict, so the staged lane's outcome is durable + queryable (the Mind / 'is this survivor credible?' read).
    Best-effort + offline-safe: any failure is swallowed + logged — an R3 persist must never break a research run.
    Reuses the EXISTING gate_verdicts table (no schema change); the row moves no money and adds no trials."""
    try:
        payload = {
            "kind": "replication",
            "method": METHOD_REPLICATION_COHORT,
            "survivor_id": report.survivor_id,
            "label": report.label,
            "params_hash": report.params_hash,
            "venue": report.venue,
            "verdict": report.verdict,
            "credible": report.credible,
            "quorum": report.quorum,
            "n_cells": report.n_cells,
            "n_replicated": report.n_replicated,
            "discovery_universe": report.discovery_universe,
            "held_out": report.held_out,
            "cells": [
                {
                    "symbol": c.symbol, "venue": c.venue, "n_obs": c.n_obs, "net_return": c.net_return,
                    "net_sharpe": c.net_sharpe, "net_max_dd": c.net_max_dd,
                    "buy_and_hold_sharpe": c.buy_and_hold_sharpe, "buy_and_hold_max_dd": c.buy_and_hold_max_dd,
                    "replicated": c.replicated, "note": c.note,
                }
                for c in report.cells
            ],
            "notes": report.notes,
        }
        store.rows(
            "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
            (utcnow(), report.verdict, "replication", json.dumps(payload, sort_keys=True)),
        )
        store.append_event(
            actor="master", kind="replication_cohort_run", ref_type="strategy", ref_id=report.survivor_id,
            payload={"verdict": report.verdict, "credible": report.credible,
                     "n_replicated": report.n_replicated, "n_cells": report.n_cells},
        )
        return True
    except Exception:  # noqa: BLE001 — a verdict-persist failure must never break the research/R3 path.
        log.warning("persist_replication_verdict failed for survivor=%s", report.survivor_id, exc_info=True)
        return False


# --------------------------------------------------------------------------------------------------------------
# Equity-TAA adapter — the FROZEN Faber GTAA timing rule applied to a SINGLE held-out ETF.
#
# Faber GTAA's per-sleeve rule IS a single-asset absolute-momentum timing rule: hold the asset when its month-end
# close is above its trailing 10-month SMA, else sit in cash (SHY). The whole portfolio is just 5 equal-weight
# copies of this rule on the canonical sleeves. So the frozen rule on ONE held-out ETF the strategy was never
# screened on is a genuine held-out replication cohort — exactly the GWAS test. We reuse equity_faber_gtaa's OWN
# primitives (_sma_signal / _realized_return / _add_months / SMA_MONTHS / IBKR_ETF_BPS_PER_SIDE / CASH), so there
# is NO re-implementation and NO refit — the rule is byte-identical to the discovery rule, only the symbol changes.
# --------------------------------------------------------------------------------------------------------------

# Held-out ETFs the Faber sleeves were NOT discovered on (disjoint from {SPY, EFA, AGG, GLD, IEF, SHY}). All are in
# equity_total_return_backfill.TAA_SYMBOLS, so the real run on the M2/Modal has their `*_tr.json` total-return data.
DEFAULT_HELD_OUT = ["QQQ", "IWM", "EEM", "TLT", "DBC"]


def _single_asset_timed(
    asset: gtaa.MonthlySeries, cash: gtaa.MonthlySeries, *, window: int, fee_bps_per_side: float
) -> tuple[list[float], list[float]]:
    """The FROZEN Faber rule on ONE asset: month M is invested iff close[M-1] > its trailing `window`-month SMA
    (decided at the prior month-end — PIT), else it earns the cash (SHY) total return. A fee is charged on the leg
    that flips invested<->cash. Returns (net_returns, buy_and_hold_returns) aligned month-for-month. Reuses
    equity_faber_gtaa's exact signal/return primitives — same rule, no refit."""
    fee = fee_bps_per_side / 1e4
    net: list[float] = []
    bh: list[float] = []
    prev_invested: bool | None = None
    for m in asset.months:
        signal_month = gtaa._add_months(m, -1)
        sig = gtaa._sma_signal(asset, signal_month, window)
        r_asset = gtaa._realized_return(asset, m)
        r_cash = gtaa._realized_return(cash, m)
        if sig is None or r_asset is None or r_cash is None:
            continue
        invested = bool(sig)
        gross = r_asset if invested else r_cash
        if prev_invested is None:
            cost = fee if invested else 0.0
        else:
            cost = fee if invested != prev_invested else 0.0
        net.append(gross - cost)
        bh.append(r_asset)  # buy-and-hold the held-out ETF over the SAME months
        prev_invested = invested
    return net, bh


def _gtaa_replay(symbol: str, *, load: Callable[[str], gtaa.MonthlySeries]) -> CellRun | None:
    """Run the frozen single-asset Faber rule on one held-out `symbol` and return its net-of-fee CellRun (or None
    when the symbol or the cash proxy has too little data). `load` is injectable so tests pass synthetic series."""
    asset = load(symbol)
    cash = load(gtaa.CASH)
    net, bh = _single_asset_timed(asset, cash, window=gtaa.SMA_MONTHS, fee_bps_per_side=gtaa.IBKR_ETF_BPS_PER_SIDE)
    if len(net) < 2:
        return None
    ns = gtaa._stats(net)
    bs = gtaa._stats(bh)
    return CellRun(
        n_obs=len(net), net_return=ns.total_return, net_sharpe=ns.ann_sharpe, net_max_dd=ns.max_dd,
        buy_and_hold_return=bs.total_return, buy_and_hold_sharpe=bs.ann_sharpe, buy_and_hold_max_dd=bs.max_dd,
    )


def faber_gtaa_survivor(*, loader: Callable[[str], gtaa.MonthlySeries] | None = None) -> FrozenSurvivor:
    """The equity-TAA survivor as a FROZEN single-asset absolute-momentum timing rule (Mebane Faber GTAA's
    per-sleeve 10-month-SMA rule). Discovery universe = Faber's canonical sleeves + the cash proxy. `loader`
    defaults to the real equities-cache reader; tests inject synthetic MonthlySeries so R3 runs with no cache."""
    load = loader or gtaa.load_monthly
    params = {"sma_months": float(gtaa.SMA_MONTHS), "fee_bps_per_side": float(gtaa.IBKR_ETF_BPS_PER_SIDE)}
    return FrozenSurvivor(
        id="equity-taa-faber-gtaa",
        label="Faber GTAA 10m-SMA timing (frozen)",
        params=params,
        discovery_universe=tuple(gtaa.ALL_SERIES),  # SPY EFA AGG GLD IEF SHY — the sleeves it was screened on
        replay=lambda sym: _gtaa_replay(sym, load=load),
        venue="equity",
    )


# --------------------------------------------------------------------------------------------------------------
# CLI — operationalize: run R3 on the equity-TAA survivor, print the report, persist when a durable store exists.
#   python -m cosmu.research.replication_cohort                 # default held-out QQQ/IWM/EEM/TLT/DBC, quorum 2
#   python -m cosmu.research.replication_cohort --held QQQ IWM  # explicit held-out symbols
#   python -m cosmu.research.replication_cohort --quorum 3      # stricter quorum
# Needs the equities total-return cache (`*_tr.json`, env COSMU_EQUITY_CACHE) — a data-network task, so the REAL
# run lives on the M2/Modal where the cache is materialized (python -m cosmu.research.equity_total_return_backfill
# --taa). A missing cache degrades to verdict INSUFFICIENT-DATA with an honest note (never fabricates a number).
# --------------------------------------------------------------------------------------------------------------


def _print(report: ReplicationReport) -> None:
    print("\n" + "=" * 116)
    print("INDEPENDENT REPLICATION COHORT (R3) — a Gate survivor's FROZEN spec re-run on HELD-OUT symbols (no refit)")
    print(f"  survivor={report.label}  venue={report.venue}  params_hash={report.params_hash[:16]}")
    print(f"  discovery universe (NOT eligible): {report.discovery_universe}")
    print(f"  held-out: {report.held_out}  quorum: >= {report.quorum} of {report.n_cells} net-of-fees")
    print("  rule: an ADDITIONAL credibility gate on top of the LOCKED R1 Gate — registers no trials, moves no money")
    print("=" * 116)
    print(f"  {'symbol':<8} {'n':>4} {'net_tot':>9} {'netSR':>6} {'netDD':>6} {'B&H_SR':>7} {'B&H_DD':>7} "
          f"{'beat':>10}  replicated")
    for c in report.cells:
        beat = ("Sharpe" if c.sharpe_beat else "") + ("/" if c.sharpe_beat and c.dd_beat else "") + ("DD" if c.dd_beat else "")
        flag = "YES" if c.replicated else "no"
        print(f"  {c.symbol:<8} {c.n_obs:>4} {c.net_return:>+9.1%} {c.net_sharpe:>6.2f} {c.net_max_dd:>6.1%} "
              f"{c.buy_and_hold_sharpe:>7.2f} {c.buy_and_hold_max_dd:>7.1%} {beat or '-':>10}  {flag}")
        if c.note:
            print(f"           note: {c.note}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"\n  VERDICT: {report.verdict}  (credible={report.credible})")
    print(f"  {report.headline}")
    print("=" * 116)


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    p = argparse.ArgumentParser(description="R3 independent replication cohort on the equity-TAA (Faber GTAA) survivor.")
    p.add_argument("--held", nargs="*", default=None, help="held-out symbols (default QQQ IWM EEM TLT DBC)")
    p.add_argument("--quorum", type=int, default=DEFAULT_QUORUM, help=f"replication quorum (default {DEFAULT_QUORUM})")
    p.add_argument("--no-persist", action="store_true", help="do not write the durable gate_verdicts record")
    args = p.parse_args(argv)

    held = args.held or list(DEFAULT_HELD_OUT)
    survivor = faber_gtaa_survivor()
    report = run_replication_cohort(survivor, held, quorum=args.quorum)
    _print(report)

    if report.verdict == "INSUFFICIENT-DATA":
        print("\n  (No held-out data ran. Materialize the equities total-return cache first — a DATA-NETWORK task,")
        print("   so run it on the M2/Modal, NOT a network-restricted cloud agent:")
        print("     python -m cosmu.research.equity_total_return_backfill --taa")
        print("   then re-run:  python -m cosmu.research.replication_cohort )")

    if not args.no_persist:
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            from cosmu.config.settings import Settings
            store = Store(Settings(database_url=db_url, openrouter_api_key=None))
            if persist_replication_verdict(store, report):
                print("  persisted R3 verdict -> gate_verdicts (kind='replication')")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
