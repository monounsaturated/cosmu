# intent: the ZERO-CAPITAL PAPER TRACK opener — shared by the two observe-only lanes (the VIBE/EXPLORE lane and
# the REJECTS WATCH-LIST lane). It opens a track that the EXISTING SIM executor (orchestrator/paper_step.step_tracks)
# steps forward exactly like a real survivor's track — same spec logic, same order path, same marks — but with
# `starting_capital = 0`, so it can NEVER move money and is excluded from every money/leaderboard population. This
# is the one place that wires a not-yet-gated (or gate-rejected) version into the forward-observation machinery
# WITHOUT funding it. inputs: the store + a strategy_version_id (whose spec/params already persist) + the asset-aware
# VenueCatalog; outputs: a flat zero-capital `tracks` row + a registered (zero-qty) position the executor sees +
# an audited `zero_capital_track_opened` event. invariants: ZERO capital (the row's starting_capital is '0' — the
# money path reads starting_capital and a 0-capital track contributes 0 to every equity/leaderboard sum), SIM-only
# (the position is registered venue='sim'; the executor never routes a non-'live' status to a real venue), idempotent
# (an existing track for the version is left untouched), best-effort (a failure logs + is swallowed — observe-only
# plumbing must never break the gate/research path), and it NEVER touches the gate's pass/fail or any threshold.

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from cosmu.knowledge.store import Store, utcnow
from cosmu.spine.venue import VenueCatalog, default_catalog

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZeroTrackResult:
    """One zero-capital track-open attempt. `opened` is False when the version already had a track (idempotent),
    its spec/venue could not be resolved (honest skip — never fabricate a symbol), or the write failed."""

    strategy_version_id: str
    opened: bool
    symbol: str | None = None
    venue_id: str | None = None
    reason: str | None = None


def _resolve_symbol_venue(store: Store, version_id: str, cat: VenueCatalog) -> tuple[str, str] | None:
    """The (symbol, venue_id) a version's zero-capital track should observe — resolved from its persisted spec's
    asset class exactly like the funder's survivor routing (crypto → Binance, equity → its funding venue), so the
    observe-only track prices on the SAME bars a funded survivor would. None when the spec is missing/unparsable
    or its asset class has no tradable instrument wired (the caller skips honestly rather than mislabel a symbol)."""
    # Deferred import: orchestrator.loop imports master at module load; importing it here keeps the dependency
    # one-way and avoids an import cycle (this module is imported by the rejects/vibe lanes, not at boot).
    from cosmu.orchestrator.loop import (
        _FUNDING_VENUE_BY_ASSET_CLASS,
        _screened_symbols,
        _survivor_asset_class,
        _venue_symbols,
    )

    row = store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))
    if row is None:
        return None
    raw_spec = row.get("spec")
    asset_class = _survivor_asset_class(raw_spec)
    venue_id = _FUNDING_VENUE_BY_ASSET_CLASS.get(asset_class)
    if venue_id is None:
        return None
    symbols = _venue_symbols(cat, venue_id, asset_class)
    if not symbols:
        return None
    pool = _screened_symbols(raw_spec, asset_class, symbols) or symbols
    if not pool:
        return None
    # Deterministic, stateless pick within the screened pool: a stable hash of the version id spreads two
    # observe-only tracks for the same asset class off the first symbol (mirrors the funder's round-robin spread).
    # There is no cross-track competition here — only observation — so a fixed-per-version choice is enough.
    idx = sum(version_id.encode("utf-8")) % len(pool)
    return pool[idx], venue_id


def open_zero_capital_track(
    store: Store,
    version_id: str,
    *,
    catalog: VenueCatalog | None = None,
    origin: str = "explore",
) -> ZeroTrackResult:
    """Open a ZERO-CAPITAL paper track for an existing strategy version so the SIM executor observes its own logic
    forward without funding it. Writes (idempotently): one `tracks` row with starting_capital='0', one flat
    (zero-qty) `positions` row the executor's flat-row query sees (via Portfolio.register_track), and a
    `track_opened` event (so the lifecycle trace + maturity clock recognise the track) carrying origin so a vibe
    vs rejects track is distinguishable. Returns a ZeroTrackResult. Best-effort: any failure is swallowed + logged
    — observe-only plumbing must NEVER break a gate/research run. `origin` labels the lane ("explore" | "rejects").

    A track already exists for the version ⇒ idempotent no-op (opened=False). The position is registered
    venue='sim' and the track is starting_capital=0, so the executor steps it on the sim book and it contributes
    ZERO to every equity/leaderboard sum — it can never move money."""
    cat = catalog or default_catalog()
    try:
        existing = store.row("SELECT id FROM tracks WHERE strategy_version_id = ?", (version_id,))
        if existing is not None:
            return ZeroTrackResult(version_id, opened=False, reason="track_exists")
        resolved = _resolve_symbol_venue(store, version_id, cat)
        if resolved is None:
            return ZeroTrackResult(version_id, opened=False, reason="unresolved_symbol")
        symbol, venue_id = resolved
        instrument = cat.instrument(symbol, venue_id)
        now = utcnow()
        # The zero-capital track row: starting_capital='0' is what makes it weightless on the money path. equity
        # mirrors starting_capital (0) and return_pct starts flat — mark_tracks accrues the honest forward return.
        store.rows(
            "INSERT INTO tracks(id, strategy_version_id, starting_capital, equity, return_pct, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (f"zct-{version_id}", version_id, "0", "0", "0", now),
        )
        # Register a FLAT (zero-qty) position so the executor's flat-row query picks the track up and opens the
        # first leg on the SPEC'S OWN entry signal — never a static buy-and-hold. venue='sim' = the fill-ledger
        # label the order path uses; the executor routes a non-'live' status to the sim book (no real venue).
        from cosmu.master.portfolio import Portfolio

        Portfolio(store, bankroll=store.settings.sim_bankroll).register_track(
            instrument_id=instrument.id, symbol=symbol, venue="sim", strategy_version_id=version_id
        )
        store.append_event(
            actor="master",
            kind="track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={"origin": origin, "symbol": symbol, "venue_id": venue_id, "zero_capital": True},
        )
        store.append_event(
            actor="master",
            kind="zero_capital_track_opened",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={"origin": origin, "symbol": symbol, "venue_id": venue_id},
        )
        return ZeroTrackResult(version_id, opened=True, symbol=symbol, venue_id=venue_id)
    except Exception:  # noqa: BLE001 — observe-only plumbing must never break the gate/research path.
        log.warning("open_zero_capital_track failed for version_id=%s", version_id, exc_info=True)
        return ZeroTrackResult(version_id, opened=False, reason="error")


def persist_explore_version(store: Store, spec) -> str | None:  # noqa: ANN001 — StrategySpec (deferred import)
    """Persist a VIBE/EXPLORE spec as a strategy + strategy_version row stamped `lane='explore'` (carried on the
    spec) with status='screened' (badge: Backtest) and origin='explore', so the SIM executor can observe it forward
    WITHOUT the strict gate ever funding it. Returns the new strategy_version_id, or None on failure / duplicate.
    Idempotent on the compiled code_hash: an already-persisted vibe is not re-inserted (the existing version id is
    returned). Best-effort + observe-only — a persist hiccup never raises into the NL pipeline (the gate disposes
    at graduation). The spec's `lane` is forced to 'explore' here so a vibe can NEVER be mistaken for a gate-lane
    survivor until it has actually GRADUATED (cleared the unchanged gate)."""
    try:
        from cosmu.strategy.compiler import compile_spec
        from cosmu.strategy.spec import StrategySpec

        explore_spec = spec if getattr(spec, "lane", "gate") == "explore" else spec.model_copy(update={"lane": "explore"})
        if not isinstance(explore_spec, StrategySpec):  # defensive: only ever persist a real validated spec
            return None
        from cosmu.evolution.loop import fit_params

        params = fit_params(explore_spec)
        compiled = compile_spec(explore_spec, params)
        existing = store.row("SELECT id FROM strategy_versions WHERE code_hash = ?", (compiled.code_hash,))
        if existing is not None:
            return str(existing["id"])  # idempotent: the same vibe re-entered observes once
        with store.batch() as b:
            strat = store.row("SELECT id FROM strategies WHERE name = ? AND origin = 'explore'", (explore_spec.name,))
            strategy_id = str(strat["id"]) if strat else b.insert(
                "strategies",
                {"name": explore_spec.name, "thesis": explore_spec.rationale, "origin": "explore", "created_at": utcnow()},
            )
            version_id = b.insert(
                "strategy_versions",
                {
                    "strategy_id": strategy_id,
                    "parent_id": None,
                    "spec": explore_spec.model_dump(mode="json"),
                    "generated_code": compiled.code,
                    "code_hash": compiled.code_hash,
                    "params": params,
                    "mutation_operator": "explore",
                    "mutation_rationale": "vibe/explore disposition — observed on paper, not gate-judged yet",
                    "origin": "explore",
                    "status": "screened",
                    "authored_by": "agent",
                    "created_at": utcnow(),
                },
            )
            b.append_event(
                actor="agent",
                kind="explore_entered",
                ref_type="strategy_version",
                ref_id=version_id,
                payload={"name": explore_spec.name, "lane": "explore"},
            )
        return version_id
    except Exception:  # noqa: BLE001 — observe-only plumbing must never break the NL pipeline.
        log.warning("persist_explore_version failed for spec=%s", getattr(spec, "name", "?"), exc_info=True)
        return None


def enter_explore(store: Store, spec, *, catalog: VenueCatalog | None = None) -> ZeroTrackResult | None:  # noqa: ANN001
    """The VIBE lane's one-call entry: persist `spec` as an explore-lane version (paper, zero capital) AND open a
    zero-capital paper track for it so the SIM executor observes its own logic forward. Returns the ZeroTrackResult
    (or None when the version could not be persisted). This is the disposition a loose NL idea enters INSTEAD of the
    strict gate — it graduates to the gate-lane only if it later clears the unchanged gate (see graduate_explore)."""
    version_id = persist_explore_version(store, spec)
    if version_id is None:
        return None
    return open_zero_capital_track(store, version_id, catalog=catalog, origin="explore")


def graduate_explore(store: Store, version_id: str, *, gate_clears) -> bool:  # noqa: ANN001 — callable(version_id)->bool
    """GRADUATE an explore version to the gate-lane — the ONLY lane transition the vibe lane makes, and it happens
    only AFTER the strategy actually clears the unchanged honest gate. `gate_clears(version_id) -> bool` is the
    injected gate verdict (the caller runs the SAME deterministic gate every survivor runs — this function never
    re-implements or softens it). On a clear, the version's persisted spec is rewritten with lane='gate' so the
    rest of the system treats it as a normal gate-lane survivor; on a non-clear nothing changes (it keeps observing
    on paper). Returns True iff it graduated. Best-effort + observe-only: a hiccup leaves the vibe in explore.

    The gate is NEVER loosened here: graduation is gated on `gate_clears`, which is the honest 0.95 + BH-FDR bar.
    An explore version that never clears simply stays a zero-capital paper observation forever — exactly the point
    of the vibe lane (route a low-confidence idea to paper, let the unchanged gate decide if it ever earns money)."""
    try:
        if not gate_clears(version_id):
            return False
        row = store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))
        if row is None:
            return False
        raw = row.get("spec")
        spec_dict = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        spec_dict["lane"] = "gate"  # the graduation: explore → gate (the rest treats it as a normal survivor)
        store.rows(
            "UPDATE strategy_versions SET spec = ? WHERE id = ?",
            (json.dumps(spec_dict, sort_keys=True), version_id),
        )
        store.append_event(
            actor="master",
            kind="explore_graduated",
            ref_type="strategy_version",
            ref_id=version_id,
            payload={"from_lane": "explore", "to_lane": "gate"},
        )
        return True
    except Exception:  # noqa: BLE001 — graduation is observe-only bookkeeping; never break the loop.
        log.warning("graduate_explore failed for version_id=%s", version_id, exc_info=True)
        return False
