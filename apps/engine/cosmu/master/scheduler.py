# intent: the AUTONOMOUS MASTER TICK — one bounded, idempotent, audited self-driving cycle the human oversees.
# It composes the seams already built: ingest free data (ingest.run.run_once) → author N candidates (LLM if a key
# is set, else the deterministic template, consulting long-term memory + skills) → run them through the
# DETERMINISTIC FarmLoop gate/screen + flywheel (memory + curator, inside the loop) → size gate-passed survivors
# and open a standalone forward-test track per survivor (orchestrator.fund_tracks_from_survivors)
# → emit human-facing recommendations. inputs: a Store (+ optional injectable ingest/market/llm seams); outputs:
# a TickReport + persisted audit (events ledger) + recommendations rows. invariants: the scorer/Gate stay OUT of
# every LLM path and alone decide survival + money; the LLM only PROPOSES; LIVE STAYS OFF (sim fills only) —
# nothing here can move real money; CRON-ABLE (one tick per call, never a daemon); BOUNDED + reproducible offline
# (no keys/network needed); idempotent (a paused tick is a no-op; a fresh tick re-runs cleanly and is audited).

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import MarketDataProvider
from cosmu.knowledge.store import Store, utcnow

# State machine, persisted to the events ledger so GET /autonomy/status can read it without an in-memory daemon.
_TICK_STARTED = "autonomy_tick_started"
_TICK_COMPLETED = "autonomy_tick_completed"
_PAUSED = "autonomy_paused"
_RESUMED = "autonomy_resumed"


@dataclass
class TickSummary:
    """The headline counts of one tick — what the human overview shows. Money-honest: `funded` is PAPER only."""

    authored: int = 0
    gated_passed: int = 0
    funded: int = 0
    recommendations: int = 0


@dataclass
class TickReport:
    summary: TickSummary
    ingested: dict[str, int] = field(default_factory=dict)
    survivors: list[str] = field(default_factory=list)
    recommendation_ids: list[str] = field(default_factory=list)
    live_enabled: bool = False  # ALWAYS reported; the tick itself never arms live
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class AutonomyStatus:
    running: bool
    paused: bool
    live_enabled: bool
    cycles_run: int
    last_tick_at: str | None
    last_action: str
    next_action: str
    last_summary: TickSummary


def is_paused(store: Store) -> bool:
    """Read the latest pause/resume marker from the ledger (no in-memory daemon — the tick is cron-able)."""
    row = store.row(
        f"SELECT kind FROM events WHERE kind IN ('{_PAUSED}', '{_RESUMED}') ORDER BY id DESC LIMIT 1"
    )
    return bool(row and row["kind"] == _PAUSED)


def pause(store: Store) -> None:
    store.append_event(actor="human", kind=_PAUSED, ref_type="autonomy", ref_id="global")


def resume(store: Store) -> None:
    store.append_event(actor="human", kind=_RESUMED, ref_type="autonomy", ref_id="global")


def _live_enabled(store: Store) -> bool:
    row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return bool(row and row["enabled"])


def _cycles_run(store: Store) -> int:
    row = store.row(f"SELECT COUNT(*) AS n FROM events WHERE kind = '{_TICK_COMPLETED}'")
    return int(row["n"]) if row else 0


def autonomy_status(store: Store) -> AutonomyStatus:
    """The human-overview snapshot, read entirely off the persisted ledger. `running` means autonomy is armed
    (not paused); the loop is cron-driven, so there is no separate process to be 'up'."""
    paused = is_paused(store)
    last = store.row(
        f"SELECT ts, payload FROM events WHERE kind = '{_TICK_COMPLETED}' ORDER BY id DESC LIMIT 1"
    )
    last_at: str | None = None
    summary = TickSummary()
    last_action = "no tick yet"
    if last:
        import json

        last_at = last["ts"]
        payload = json.loads(last["payload"]) if isinstance(last["payload"], str) else (last["payload"] or {})
        s = payload.get("summary", {})
        summary = TickSummary(
            authored=int(s.get("authored", 0)),
            gated_passed=int(s.get("gated_passed", 0)),
            funded=int(s.get("funded", 0)),
            recommendations=int(s.get("recommendations", 0)),
        )
        last_action = (
            f"authored {summary.authored}, {summary.gated_passed} cleared the gate, "
            f"funded {summary.funded} forward-test track(s), {summary.recommendations} recommendation(s)"
        )
    next_action = "paused — resume to run the next tick" if paused else "run one bounded research+fund tick"
    return AutonomyStatus(
        running=not paused,
        paused=paused,
        live_enabled=_live_enabled(store),
        cycles_run=_cycles_run(store),
        last_tick_at=last_at,
        last_action=last_action,
        next_action=next_action,
        last_summary=summary,
    )


def run_tick(
    store: Store,
    *,
    n: int = 4,
    seed: int = 7,
    settings: Settings | None = None,
    market_data: MarketDataProvider | None = None,
    chat=None,  # noqa: ANN001 — injectable LLM seam; None → real OpenRouter seam from settings (offline → fallback)
    ingest=None,  # noqa: ANN001 — injectable ingest callable (store -> counts); None → free-data run_once
    edge_market: bool = False,
    bankroll: Decimal | None = None,
) -> TickReport:
    """ONE bounded, idempotent, audited autonomous cycle. Paused → a no-op (idempotent). Otherwise: ingest free
    data → author N candidates (LLM PROPOSES if a key is set; deterministic template otherwise) → DETERMINISTIC
    FarmLoop gate/screen + flywheel → open a standalone track per gate-passed survivor → emit human-facing
    recommendations. LIVE STAYS OFF: funding routes sim fills only; the tick never arms live. Reproducible
    offline for a fixed (n, seed). Every stage is audited to the events ledger."""
    settings = settings or store.settings
    live = _live_enabled(store)

    if is_paused(store):
        return TickReport(summary=TickSummary(), live_enabled=live, skipped=True, skip_reason="paused")

    store.append_event(actor="master", kind=_TICK_STARTED, ref_type="autonomy", ref_id="global", payload={"n": n, "seed": seed})

    # 1) INGEST free data (append-only, point-in-time, zero keys; per-source failure → 0 count, never aborts).
    try:
        from cosmu.ingest.run import run_once

        ingested = ingest(store) if ingest is not None else run_once(store)
    except Exception as exc:  # noqa: BLE001 — ingest is best-effort; a dead source must never abort the tick
        ingested = {"error": 0}
        store.append_event(actor="master", kind="autonomy_ingest_failed", ref_type="autonomy", payload={"error": type(exc).__name__})

    # 2-3) AUTHOR → DETERMINISTIC GATE + FLYWHEEL. run_research_pass authors via lab/author (LLM-optional,
    # consulting memory + skills), then runs the FarmLoop screen/gate (scorer out of any LLM's reach) which
    # records the flywheel (memory + curator) inside the loop and persists survivors/graveyard.
    from cosmu.lab.research import run_research_pass

    report = run_research_pass(
        store,
        n=n,
        seed=seed,
        llm_enabled=bool(settings.llm_api_key) or chat is not None,
        market_data=market_data,
        edge_market=edge_market,
        chat=chat,
        persist=True,
    )
    authored = len(report.authored)
    survivors = report.survivors
    survivor_names = [s.name for s in survivors]

    # 4) OPEN a standalone forward-test track per gate-passed survivor (sim fills only — live
    # stays OFF inside fund_tracks_from_survivors). Best-effort + offline-safe; a market hiccup leaves it 0.
    funded = 0
    try:
        from cosmu.orchestrator import fund_tracks_from_survivors

        # Fund through the SAME provider the screen used: an explicit one if given, else the deterministic
        # edge-bearing fixture when edge_market is on (so funding resolves prices offline with no network/cache),
        # else the real Binance provider (cache-backed, offline-safe — a missing mark just skips that symbol).
        funding_provider = market_data
        if funding_provider is None and edge_market:
            from cosmu.lab.research import _EdgeBearingBars

            funding_provider = _EdgeBearingBars()
        funding = fund_tracks_from_survivors(
            store,
            market_data=funding_provider,
            bankroll=bankroll if bankroll is not None else settings.sim_bankroll,
        )
        funded = funding.funded
    except Exception as exc:  # noqa: BLE001 — funding is best-effort; never aborts an already-gated tick
        store.append_event(actor="master", kind="autonomy_funding_failed", ref_type="autonomy", payload={"error": type(exc).__name__})

    # 5) EMIT human-facing recommendations (watch the survivor 4 weeks; flag a source that stopped paying).
    rec_ids = _emit_recommendations(store, survivors=survivor_names, ingested=ingested)

    summary = TickSummary(
        authored=authored,
        gated_passed=len(survivors),
        funded=funded,
        recommendations=len(rec_ids),
    )
    store.append_event(
        actor="master",
        kind=_TICK_COMPLETED,
        ref_type="autonomy",
        ref_id="global",
        payload={
            "summary": {
                "authored": summary.authored,
                "gated_passed": summary.gated_passed,
                "funded": summary.funded,
                "recommendations": summary.recommendations,
            },
            "ingested": ingested,
            "survivors": survivor_names,
            "live_enabled": live,  # audited every tick: the tick never moves real money
            "llm": "on" if (settings.llm_api_key or chat is not None) else "off",
        },
    )
    return TickReport(
        summary=summary,
        ingested=ingested,
        survivors=survivor_names,
        recommendation_ids=rec_ids,
        live_enabled=live,
    )


def _emit_recommendations(store: Store, *, survivors: list[str], ingested: dict[str, int]) -> list[str]:
    """Emit at most a few human-facing, plain-language recommendations from this tick: a Version that cleared the
    gate (watch it 4 weeks before live), and any free source that stopped paying (0 points this pass). Idempotent
    within a tick: a survivor already watched (open recommendation referencing it) is not re-emitted."""
    ids: list[str] = []
    open_bodies = {
        r["body"] for r in store.rows("SELECT body FROM recommendations WHERE state = 'open'")
    }
    for name in survivors[:3]:
        body = (
            f"A Version cleared the deterministic gate: '{name}'. Watch it in sim for 4+ weeks with positive "
            f"net edge before considering live. Live stays off until you arm it."
        )
        if body in open_bodies:
            continue
        rec_id = store.insert(
            "recommendations",
            {
                "ts": utcnow(),
                "kind": "forward_test_promotion_watch",
                "body": body,
                "state": "open",
                "payload": {"version_name": name, "requires": ["4w_sim_survival", "regime_match", "caps_available"]},
            },
        )
        ids.append(rec_id)
    for source, count in ingested.items():
        if count != 0 or source == "error":
            continue
        body = f"Free data source '{source}' returned 0 points this pass — it may have stopped paying. Consider checking or dropping it."
        if body in open_bodies:
            continue
        rec_id = store.insert(
            "recommendations",
            {
                "ts": utcnow(),
                "kind": "source_stopped_paying",
                "body": body,
                "state": "open",
                "payload": {"source": source},
            },
        )
        ids.append(rec_id)
    if ids:
        store.append_event(actor="master", kind="recommendations_emitted", ref_type="autonomy", payload={"count": len(ids)})
    return ids


def _main(argv: list[str] | None = None) -> int:
    """CLI / Railway cron entrypoint: one bounded tick on the REAL production store + REAL Binance data.

    This is what `python3 -m cosmu.master.scheduler` runs every 4h on Railway, so it MUST connect to the
    production DB (Settings() reads DATABASE_URL etc. from the env) and screen on real bars — never a
    throwaway temp DB or synthetic fixture. Use --offline for a self-contained demo (temp sqlite, edge-bearing
    fixture, no network/keys) when running locally without a DB."""
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Run ONE bounded autonomous master tick (cron-able, sim-only, never arms live).")
    parser.add_argument("--n", type=int, default=4, help="candidates to author this tick (default 4)")
    parser.add_argument("--seed", type=int, default=7, help="cohort seed (default 7)")
    parser.add_argument("--offline", action="store_true", help="self-contained demo: temp sqlite + edge-bearing fixture, no network/keys (NOT for prod)")
    args = parser.parse_args(argv)

    if args.offline:
        tmp = tempfile.mkdtemp(prefix="cosmu-tick-")
        store = Store(Settings(database_url=f"sqlite:///{tmp}/tick.sqlite3", openrouter_api_key=None))
        report = run_tick(store, n=max(1, args.n), seed=args.seed, edge_market=True, ingest=lambda _s: {})
    else:
        # PRODUCTION: real store (DATABASE_URL from env), real free-data ingest, real Binance bars (edge_market=False).
        store = Store(Settings())
        report = run_tick(store, n=max(1, args.n), seed=args.seed, edge_market=False)
    s = report.summary
    print("AUTONOMOUS MASTER TICK — one bounded cycle complete (sim-only, live off)")
    print(f"  authored={s.authored} gated_passed={s.gated_passed} funded={s.funded} recommendations={s.recommendations}")
    print(f"  survivors: {', '.join(report.survivors) or '-'}")
    print(f"  live_enabled={report.live_enabled} (the tick never arms live)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
