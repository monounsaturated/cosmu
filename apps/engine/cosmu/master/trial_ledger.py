# intent: the HONEST trial-count ledger — record EVERY look the BRUT sweeps take (every strategy×symbol×venue
# cell, the seeder sweep, the exit-envelope sweep) so the Gate's Deflated Sharpe deflates against the TRUE number
# of trials, not the per-combo param-grid count alone; inputs: per-look per-observation Sharpes + the look's
# family + the family's measured return correlation; outputs: a decorrelated EFFECTIVE-N and a survivor DSR
# recompute at that N; invariants: append-only, out of any LLM's reach, reuses the locked scorer correlation
# haircut (effective_trials) — it makes N honest, it NEVER changes a locked Gate constant (DSR 0.95 / min-trades /
# PBO / FDR-q) and never moves money on its own.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.config.settings import GateSettings
from cosmu.knowledge.store import Store, trial_ledger_available, utcnow
from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob, effective_trials

_LEDGER_COLUMNS = ["ts", "lane", "family", "symbol", "venue", "sharpe_per_obs", "rho_bar"]


@dataclass(frozen=True)
class Look:
    """ONE look the machine took: a (strategy × symbol × venue) cell that was backtested + scored. `sharpe_per_obs`
    is the cell's per-observation Sharpe (the same statistic the Deflated Sharpe is built on). symbol/venue are the
    cell's S×A×V coordinates (None for a non-cell look)."""

    sharpe_per_obs: float
    symbol: str | None = None
    venue: str | None = None


def measure_family_rho(streams: list[list[float]]) -> float | None:
    """The family's average pairwise return correlation ρ̄ — the haircut input for effective_trials. Reuses the
    SAME pairwise-correlation primitive the cohort gate uses (master/strategy_correlation), so a dense correlated
    grid of one family collapses toward 1/ρ̄ effective trials instead of inflating the count. None when it cannot
    be measured (< 2 streams with enough overlap), which means "no haircut" downstream (the conservative,
    stricter direction — full independent trials)."""
    usable = [s for s in streams if s and len(s) >= 2]
    if len(usable) < 2:
        return None
    # Local import keeps the lean record path from pulling the correlation module unless a ρ̄ is actually wanted.
    from cosmu.master.strategy_correlation import pairwise_correlation

    rho = pairwise_correlation({f"s{i}": s for i, s in enumerate(usable)}).average_pairwise_correlation
    # average_pairwise_correlation is NaN when no pair cleared MIN_OVERLAP — surface that as "unmeasured".
    return None if rho != rho else float(rho)  # rho != rho is the NaN test


def record_looks(
    store: Store,
    *,
    lane: str,
    family: str,
    looks: list[Look],
    rho_bar: float | None = None,
) -> int:
    """Append every look of ONE family to the honest ledger in a single batched insert. THE choke point the BRUT
    finder/loop sweeps route through so the Deflated Sharpe can later deflate against the true look count.

    BEST-EFFORT + schema-probe gated: on a pre-migration prod table (no `trial_ledger`) this no-ops and returns 0
    (byte-identical to before this change); any DB hiccup is swallowed (recording a look must NEVER break the
    screen that produced it — the deterministic verdict is already set). Returns the number of rows written."""
    if not looks:
        return 0
    try:
        if not trial_ledger_available(store):
            return 0
        ts = utcnow()
        rho = None if rho_bar is None else float(rho_bar)
        rows = [
            (ts, lane, family, lk.symbol, lk.venue, float(lk.sharpe_per_obs), rho)
            for lk in looks
        ]
        with store.batch() as writer:
            writer.insert_many("trial_ledger", _LEDGER_COLUMNS, rows)
        return len(rows)
    except Exception:  # noqa: BLE001 — the ledger is an audit instrument; never break the screen on a write error
        return 0


def record_look(
    store: Store,
    *,
    lane: str,
    family: str,
    sharpe_per_obs: float,
    symbol: str | None = None,
    venue: str | None = None,
    rho_bar: float | None = None,
) -> int:
    """Append a SINGLE look (convenience over record_looks)."""
    return record_looks(
        store, lane=lane, family=family,
        looks=[Look(sharpe_per_obs=sharpe_per_obs, symbol=symbol, venue=venue)], rho_bar=rho_bar,
    )


def ledger_count(store: Store) -> int:
    """Raw row count of the honest ledger (every look). 0 when the table is absent (pre-migration)."""
    if not trial_ledger_available(store):
        return 0
    row = store.row("SELECT COUNT(*) AS n FROM trial_ledger")
    return int(row["n"]) if row else 0


def effective_n(store: Store, *, family: str | None = None, include_legacy_trials: bool = True) -> float:
    """The DECORRELATED effective trial count — the honest N the Deflated Sharpe should deflate against.

    Computed per FAMILY and summed: N_eff = Σ_family effective_trials(K_family, ρ̄_family), reusing the scorer's
    correlation haircut N/(1+(N-1)·ρ̄). Within a family a dense correlated grid collapses toward 1/ρ̄ (densifying
    a near-duplicate family stops inflating the count); ACROSS families looks are treated as independent and
    summed — no cross-family haircut, so N can only err HIGHER (stricter), the honest direction for a hurdle.

    `family` restricts the count to one family (the survivor's own family); None counts the whole ledger.
    `include_legacy_trials` folds in the legacy `trials` rows (the research/FDR cohort lanes) as independent
    looks, so the audit sees EVERY look across the whole machine — brut sweeps AND research lanes."""
    total = 0.0
    if trial_ledger_available(store):
        if family is None:
            rows = store.rows(
                "SELECT family, COUNT(*) AS k, AVG(rho_bar) AS rho FROM trial_ledger GROUP BY family"
            )
        else:
            rows = store.rows(
                "SELECT family, COUNT(*) AS k, AVG(rho_bar) AS rho FROM trial_ledger WHERE family = ? GROUP BY family",
                (family,),
            )
        for r in rows:
            k = float(int(r["k"]))
            rho = r["rho"]
            total += effective_trials(k, None if rho is None else float(rho))
    # Legacy `trials` ledger (research/FDR cohort lanes): counted as independent looks (no per-family streams to
    # decorrelate here — they were already deflated in their own gate). Only when counting the whole machine.
    if include_legacy_trials and family is None:
        row = store.row("SELECT COUNT(*) AS n FROM trials")
        if row and row["n"] is not None:
            total += float(int(row["n"]))
    return total


def honest_trial_stats(store: Store, *, family: str | None = None) -> TrialStats:
    """A TrialStats whose `count` is the honest decorrelated effective-N — ready to feed `deflated_sharpe_prob`.

    sr_correlation is left None: the per-family haircut is ALREADY baked into the count (effective_n), so the
    scorer must NOT haircut it a second time. sr_variance is left None too, so the DSR uses the Lo (2002) analytic
    null variance — the SAME variance model the BRUT gate scored the survivor under, isolating the one thing this
    audit changes: the trial count N."""
    n = effective_n(store, family=family)
    return TrialStats(count=max(1, round(n)))


@dataclass(frozen=True)
class SurvivorRecompute:
    """The survivor-realness verdict: the SAME Deflated Sharpe, recomputed at the honest decorrelated effective-N.

    `raw_n` is the (undercounted) N the survivor was originally deflated by (its per-combo param-grid count).
    `effective_n` is the honest ledger count; `honest_n` is the N actually used (never below raw_n — the honest
    count can only raise the bar). `dsr_naive` reproduces the survivor's original Deflated Sharpe; `dsr_honest`
    is it recomputed at honest_n. `clears_*` compare against the LOCKED DSR gate (`threshold`, unchanged)."""

    family: str | None
    raw_n: int
    effective_n: float
    honest_n: int
    dsr_naive: float
    dsr_honest: float
    threshold: float
    clears_naive: bool
    clears_honest: bool

    @property
    def still_clears(self) -> bool:
        """Whether the survivor still clears the locked DSR gate once N is made honest."""
        return self.clears_honest


def recompute_dsr_at_honest_n(
    metrics: BacktestMetrics,
    store: Store,
    gates: GateSettings | None = None,
    *,
    family: str | None = None,
) -> SurvivorRecompute:
    """Recompute a survivor's Deflated Sharpe at the TRUE decorrelated effective-N from the honest ledger, and
    report whether it STILL clears the locked DSR gate. This is the playbook's bridge #2 instrument: it makes the
    N honest WITHOUT touching a single locked Gate constant — only the trial count fed into expected_max_sharpe
    changes. The variance model + every threshold are identical to the survivor's original verdict."""
    gates = gates or GateSettings()
    raw_n = max(int(metrics.trials_counted), 1)
    eff = effective_n(store, family=family)
    honest_n = max(round(eff), raw_n)  # the honest count can only RAISE the bar, never lower it
    naive = deflated_sharpe_prob(metrics, TrialStats(count=raw_n))
    honest = deflated_sharpe_prob(metrics, TrialStats(count=honest_n))
    thr = float(gates.min_deflated_sharpe_prob)
    return SurvivorRecompute(
        family=family,
        raw_n=raw_n,
        effective_n=eff,
        honest_n=honest_n,
        dsr_naive=naive,
        dsr_honest=honest,
        threshold=thr,
        clears_naive=naive >= thr,
        clears_honest=honest >= thr,
    )
