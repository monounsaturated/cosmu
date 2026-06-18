# intent: CLOSE THE AUTONOMOUS LOOP — read REAL persisted survivors (Finder/research gate-passers with tracks),
# open a STANDALONE paper track for each (its own simulated capital, no pooled wallet, no cross-track
# competition). Funding REGISTERS the track FLAT (a zero-qty position row): the track's first entry is its own
# spec's signal, executed by the paper executor (orchestrator/forward_step.py) — the funder never opens a
# static long, so the ≥30-day forward record measures the strategy, not buy-and-hold-from-funding-day. Each
# survivor funds on a symbol its gate evidence actually covered (the screened universe ∩ the venue catalog),
# then mark-to-market so GET /overview reflects genuine positions/equity (no fabricated numbers). inputs: the
# store + a market provider for latest marks; outputs: registered flat tracks + a marked snapshot. invariants:
# only gate-passed survivors are funded, each track is standalone (fixed per-strategy capital, never a pooled
# share), live stays OFF, registration is idempotent (an existing row is never reset), deterministic for a fixed
# store + marks, offline-safe (degrades to cache).

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING

from cosmu.adapters.data.alpaca import AlpacaDailyBarsProvider
from cosmu.adapters.exec.registry import EXEC_ADAPTER_VENUES
from cosmu.data.market import (
    MarketDataProvider,
    YahooDailyBarsProvider,
    default_crypto_reference,
)
from cosmu.data.price_cells import alt_ingest_symbol

if TYPE_CHECKING:
    from cosmu.config.settings import Settings
from cosmu.knowledge.lifecycle_status import ALIVE_STATUSES, PAPER_ALIASES, sql_in_list
from cosmu.knowledge.store import Store, tracks_has_cell_columns, utcnow
from cosmu.master.drift import DriftVerdict, assess_drift, track_return_series
from cosmu.master.live_eligibility import cell_id
from cosmu.master.neutral import accrue_funding, neutral_tracks
from cosmu.master.portfolio import Portfolio
from cosmu.portfolio.rotation import Track, select_tracks
from cosmu.spine.venue import VenueCatalog, default_catalog

# ASSET-CLASS → its DEFAULT funding venue (the fallback when a cell's own screen venue can't execute). It MUST be a
# venue with a real ExecutionAdapter (adapters/exec/registry.EXEC_ADAPTER_VENUES = binance/kraken/alpaca/polymarket),
# else a funded survivor can never route live — it sim-fills forever while the UI shows 'armed'. crypto → Binance
# spot; equity/ETF → ALPACA (ibkr has data but NO exec adapter, so every equity survivor — the only class with Gate
# survivors today — was structurally unable to go live). Alpaca mirrors the same 31 equities in the catalog and the
# mark leg prices equities off Alpaca-when-keyed-else-Yahoo total-return. A class absent here has NO default funding
# venue → its survivors are SKIPPED unless their own cell venue can execute (never forced onto a crypto symbol).
_FUNDING_VENUE_BY_ASSET_CLASS: dict[str, str] = {"crypto": "binance", "equity": "alpaca"}


def _funding_venue_for_cell(cell_venue: str | None, asset_class: str) -> str | None:
    """The venue a passing cell FUNDS on, PRESERVING the cell's OWN screen venue (the S×A×V triple) whenever that
    venue has a real exec adapter — so a cell the gate passed on KRAKEN funds on Kraken, NOT collapsed back onto
    Binance (the bug that re-collapses the venue axis at funding time, defeating the whole universal-price layer).
    Only when the cell's own venue can't execute (a data/research-only venue, or a missing venue_id on a legacy
    row) do we fall back to the asset class's DEFAULT execution venue. None when neither resolves → the cell is
    SKIPPED (never mispriced onto a venue it wasn't proven on)."""
    if cell_venue and cell_venue in EXEC_ADAPTER_VENUES:
        return cell_venue
    return _FUNDING_VENUE_BY_ASSET_CLASS.get(asset_class)


def _instrument_venue(catalog: VenueCatalog, instrument_id: str) -> str | None:
    """The catalog venue an instrument trades on, looked up by instrument id. Positions opened through the
    ONE order path persist venue='sim' — a fill-ledger label, NOT a catalog venue — so pricing/routing must
    recover the real venue from the instrument (an equity survivor funded via the order path would otherwise
    route to the crypto leg and never mark). None for an unknown instrument (the caller skips honestly)."""
    for inst in catalog.instruments:
        if inst.id == instrument_id:
            return inst.venue_id
    return None


def _venue_symbols(catalog: VenueCatalog, venue_id: str, asset_class: str) -> list[str]:
    """Symbols that actually exist as instruments at `venue_id` for `asset_class` (so a sim fill can resolve an
    instrument). A track only funds tradable instruments — no fabricated symbols."""
    return [i.symbol for i in catalog.instruments if i.venue_id == venue_id and i.asset_class == asset_class]


def assess_cell_drift(store: Store, version_id: str, symbol: str, venue_id: str) -> DriftVerdict:
    """Anticipatory alpha-decay verdict for ONE cell, read off ITS OWN cell-keyed realized trajectory
    (scope='track' portfolio_snapshots ref_id = version:symbol:venue, with a version-only legacy fallback). So the
    auto-defund pulls the right cell — never a sibling cell's drift. Emits a `drift_assessed` (+ `track_defunded`)
    audit event per cell. On first funding there is no history → insufficient-history (no defund)."""
    cid = cell_id(version_id, symbol, venue_id)
    series = track_return_series(store, version_id, symbol=symbol, venue_id=venue_id)
    verdict = assess_drift(cid, series)
    store.append_event(
        actor="master", kind="drift_assessed", ref_type="strategy_version", ref_id=cid,
        payload={
            "defund": verdict.defund, "reason": verdict.reason, "symbol": symbol, "venue_id": venue_id,
            "half_life": verdict.decay.half_life, "realized_edge": verdict.drift.realized_edge,
            "z": verdict.drift.z, "cusum": verdict.drift.cusum, "n": verdict.drift.n,
        },
    )
    if verdict.defund:
        store.append_event(
            actor="master", kind="track_defunded", ref_type="strategy_version", ref_id=cid,
            payload={"reason": verdict.reason, "anticipatory": True, "symbol": symbol, "venue_id": venue_id},
        )
    return verdict


def _survivor_asset_class(raw_spec: object) -> str:
    """The asset class a survivor should be FUNDED against, read from its persisted StrategySpec
    (`universe.asset_classes`). Defaults to crypto when the spec is missing/unparsable or declares no asset class
    — the historical default for this loop (never crash on an unexpected row)."""
    if not raw_spec:
        return "crypto"
    try:
        spec = json.loads(raw_spec) if isinstance(raw_spec, str) else raw_spec
    except (ValueError, TypeError):
        return "crypto"
    if not isinstance(spec, dict):
        return "crypto"
    classes = (spec.get("universe") or {}).get("asset_classes") or []
    return str(classes[0]) if classes else "crypto"


@dataclass
class TrackFundingReport:
    survivors: int
    funded: int = 0
    funded_tracks: list[str] = field(default_factory=list)   # version_ids of the standalone tracks opened this cycle
    equity: float = 0.0
    pnl: float = 0.0
    drift_defunded: int = 0   # tracks the anticipatory drift monitor pulled this cycle (edge half-life / live drift)


def _survivor_tracks(store: Store, catalog: VenueCatalog) -> list[tuple[str, Track, str, str]]:
    """BRUT fan-out: read the real config-library / research survivors and emit one funding entry PER FUNDABLE CELL.

    A cell is a tradeable triple (strategy_version × symbol × venue). TWO generous-paper lanes both fund the SAME
    standalone zero-real-capital paper track:
      • GATE lane — verdict='pass': the gate passed it ON ITS OWN data (version-level passed_gates=1 + holdout=1).
        These are the live-arming survivors.
      • WATCH lane — verdict='watch': a gate-FAILED near-miss (sharpe>1 / trades>=30 / return>0, tagged by the
        finder/loop). Routed to paper INSTEAD of killed so the forward test separates real from lucky. A watch cell
        is NOT a gate pass — its version is 'killed' with passed_gates=0, so the version gate flags are NOT required
        for it (only for the gate lane). It is never live-armable (live-eligibility reads the per-cell pass passport,
        which a watch cell lacks); it just paper-trades + defunds on drift like any paper cell.

    Each cell funds on the EXACT symbol it was proven/near-missed on (never a round-robin index, never a sibling-
    compared pick — the brut model has no siblings to compare). UNCAPPED, no human, no cross-cell logic: the forward/
    paper test is the fluke safeguard (live stays human-only, and watch never reaches it). Returns (version_id,
    Track, symbol, funding_venue_id) — one tuple per fundable cell. `rolling_dsr` = the cell's deflated Sharpe.

    The funding venue PRESERVES the cell's OWN screen venue (bs.venue_id — the S×A×V triple) whenever that venue
    has a real exec adapter, so a cell proven on KRAKEN funds on Kraken and the venue axis stays de-collapsed; only
    a data/research-only screen venue falls back to the asset class's default execution venue (crypto → Binance,
    equity → Alpaca). A cell with no resolvable funding venue, or whose symbol isn't a catalog instrument there, is
    SKIPPED (never mislabel/misprice a position)."""
    rows = store.rows(
        f"""
        SELECT sv.id AS version_id, sv.spec AS spec,
               bs.symbol AS symbol, bs.venue_id AS cell_venue,
               b.deflated_sharpe AS deflated_sharpe, bs.verdict AS verdict
        FROM strategy_versions sv
        JOIN backtests b ON b.strategy_version_id = sv.id AND b.kind = 'screen'
        JOIN backtest_symbols bs ON bs.strategy_version_id = sv.id
        WHERE sv.status IN {sql_in_list(ALIVE_STATUSES)}
          AND (
            (bs.verdict = 'pass' AND b.passed_gates = 1 AND b.holdout_passed = 1)
            OR bs.verdict = 'watch'
          )
        ORDER BY CAST(b.deflated_sharpe AS REAL) DESC
        """
    )
    symbols_by_venue: dict[tuple[str, str], set[str]] = {}
    out: list[tuple[str, Track, str, str]] = []
    seen: set[tuple[str, str, str]] = set()  # de-dup (version, symbol, funding_venue) across rescreens
    for r in rows:
        asset_class = _survivor_asset_class(r.get("spec"))
        # PRESERVE the cell's OWN venue at funding (the fix): only fall back to the class default when the cell's
        # screen venue can't execute. This is what stops the venue axis re-collapsing onto Binance at funding time.
        venue_id = _funding_venue_for_cell(r.get("cell_venue"), asset_class)
        if venue_id is None:
            continue  # no resolvable funding venue for this cell → SKIP (never force onto a crypto symbol)
        tradable = symbols_by_venue.setdefault(
            (venue_id, asset_class), set(_venue_symbols(catalog, venue_id, asset_class))
        )
        symbol = r["symbol"]
        if symbol not in tradable:
            continue  # the proven cell's symbol isn't a catalog instrument at the funding venue → SKIP (no fabrication)
        key = (r["version_id"], symbol, venue_id)
        if key in seen:
            continue
        seen.add(key)
        track = Track(id=r["version_id"], rolling_dsr=float(r["deflated_sharpe"] or 0.0))
        out.append((r["version_id"], track, symbol, venue_id))
    return out


def fund_tracks_from_survivors(
    store: Store,
    *,
    market_data: MarketDataProvider | None = None,
    catalog: VenueCatalog | None = None,
    bankroll: Decimal = Decimal("100000"),
    router: PricingRouter | None = None,
) -> TrackFundingReport:
    """Close the loop, BRUT per-cell: open a STANDALONE paper track for EACH PASSING CELL (its own fixed
    per-strategy capital — never a pooled share), open sim positions through the one order path, and
    mark-to-market. UNCAPPED, no human, no cross-cell logic: every cell the gate passed on its OWN data fans out
    to its own forward test (the fluke safeguard). Live stays OFF (sim fills).

    ASSET-AWARE: each cell is funded on the venue/symbol it was PROVEN on (crypto → Binance, equity → Alpaca — the
    venue with a real exec adapter), marked via the SAME router the paper clock uses. A cell whose asset class has
    no funding venue, or an unpriceable symbol, is SKIPPED. `market_data` overrides only the crypto mark leg."""
    cat = catalog or default_catalog()
    pricer = router or PricingRouter(cat, crypto=market_data, settings=store.settings)
    portfolio = Portfolio(store, bankroll=bankroll)

    cells = _survivor_tracks(store, cat)
    report = TrackFundingReport(survivors=len(cells))
    if not cells:
        marks = portfolio.mark_to_market({})
        report.equity = float(marks["equity"])
        report.pnl = float(marks["pnl"])
        return report

    # ANTICIPATORY defund (master/drift), PER CELL: assess each funded cell's OWN realized trajectory (its
    # cell-keyed scope='track' snapshots) and pull capital BEFORE P&L turns. Reads prior marks; on first funding
    # there is no history → no defund. The Track id is the CELL id so select_tracks gates each cell independently.
    cell_keyed = []
    for vid, track, symbol, venue_id in cells:
        cid = cell_id(vid, symbol, venue_id)
        verdict = assess_cell_drift(store, vid, symbol, venue_id)
        cell_keyed.append((
            vid,
            replace(track, id=cid,
                    drift_defund=verdict.defund if verdict else False,
                    edge_half_life=verdict.decay.half_life if verdict else None),
            symbol, venue_id,
        ))
    report.drift_defunded = sum(1 for (_v, t, _s, _vn) in cell_keyed if t.drift_defund)

    track_by_cid = {cell_id(vid, symbol, venue_id): (vid, symbol, venue_id) for vid, _t, symbol, venue_id in cell_keyed}
    fundable_cids = {v.version_id for v in select_tracks([t for _v, t, _s, _vn in cell_keyed]) if v.funded}

    # A CELL that already holds a sim position (its own instrument) is NOT re-opened: re-funding a held cell every
    # tick would average a fresh same-bar entry into the basis and reset its paper clock. The funder funds each
    # cell ONCE; from then on the executor (orchestrator/paper_step.py) owns every entry/exit. already_funded is
    # keyed by (version, instrument_id) so a SECOND cell of the same version (different symbol) still funds.
    already_funded = {
        (r["strategy_version_id"], r["instrument_id"])
        for r in store.rows(
            "SELECT DISTINCT strategy_version_id, instrument_id FROM positions WHERE strategy_version_id IS NOT NULL"
        )
    }

    marks: dict[str, Decimal] = {}
    registered: list[str] = []
    for cid in fundable_cids:
        vid, symbol, venue_id = track_by_cid[cid]
        instrument = cat.instrument(symbol, venue_id)
        if (vid, instrument.id) in already_funded:
            continue
        price = pricer.last_price(symbol, venue_id)
        if price <= 0:
            continue
        marks[instrument.id] = price
        # venue='sim' matches the fill-ledger label the order path persists. The position's instrument_id encodes
        # the cell's symbol+venue, so one version can hold one flat position per passing cell.
        portfolio.register_track(
            instrument_id=instrument.id, symbol=symbol, venue="sim", strategy_version_id=vid
        )
        registered.append(cid)

    report.funded = len(registered)
    report.funded_tracks = registered

    # Cell-keyed marked snapshot: each fresh cell's per-track trajectory begins on its OWN (version,symbol,venue)
    # ref_id, so its forward-proof reads its own series (the real venue is recovered from the instrument).
    def _cell_resolver(p) -> tuple[str, str, str] | None:  # noqa: ANN001 — PositionView
        if p.strategy_version_id is None:
            return None
        venue = _instrument_venue(cat, p.instrument_id) or p.venue
        if venue == "sim" or not venue:
            return None
        return (p.strategy_version_id, p.symbol, venue)

    snapshot = portfolio.mark_to_market(marks, cell_resolver=_cell_resolver)
    report.equity = float(snapshot["equity"])
    report.pnl = float(snapshot["pnl"])
    store.append_event(
        actor="master",
        kind="tracks_funded",
        ref_type="portfolio",
        ref_id="aggregate",
        payload={"survivors": report.survivors, "funded": report.funded, "equity": report.equity, "pnl": report.pnl},
    )
    return report


def _default_equity_provider(settings: Settings | None) -> MarketDataProvider:
    """The equity mark source when none is injected: prefer Alpaca daily bars (IEX, adjustment=all — dividend-
    adjusted, with the closed-candle guard + stale-cache refetch the keyless equity providers lack) when ALPACA
    keys are configured, else the keyless Yahoo v8 total-return path. AlpacaDailyBarsProvider.from_settings
    returns None without keys, so this degrades HONESTLY to Yahoo — never a fabricated bar. (The Alpaca DATA
    lane shipped key-gated in #172; this is the wiring that actually selects it for the paper clock once
    keys land — both providers price the same total-return closes, so a track's P&L is consistent either way.)"""
    if settings is not None:
        alpaca = AlpacaDailyBarsProvider.from_settings(settings)
        if alpaca is not None:
            return alpaca
    return YahooDailyBarsProvider()


class PricingRouter:
    """ASSET-AWARE mark source for the paper clock. One router routes each held position to the REAL
    pricing source for its asset class — crypto → Binance spot, equity/ETF → Alpaca (IEX, dividend-adjusted) when
    ALPACA keys are set else keyless Yahoo total-return — so an equity (GEM, the TAA fleet) accrues honest P&L
    instead of marking to 0 against a Binance symbol that does not exist. The asset class is read from the
    instrument the position references in the catalog (looked up by (symbol, venue)); an unknown instrument falls
    back to the venue's declared kind. NO synthetic/zero-fill: a genuinely unavailable close (offline, gap day,
    unknown symbol) returns 0 and the caller SKIPS that position, leaving it at its last basis. Deterministic for
    a fixed catalog + provider responses; offline-safe.

    The crypto and equity providers are constructed lazily and reused across every position in one run (one cache
    each), and either can be injected for tests/alternate venues — there is no per-call-site provider, this is the
    single pricing-router for the clock. Pass `settings` to let the equity leg pick Alpaca-when-keyed (an injected
    `equity` provider always wins)."""

    def __init__(
        self,
        catalog: VenueCatalog,
        *,
        crypto: MarketDataProvider | None = None,
        equity: MarketDataProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.catalog = catalog
        # Crypto leg: injected wins (tests); else the default reference — Binance direct, or the Railway EU bars
        # engine when COSMU_BARS_URL is set (so a geo-blocked compute account still marks crypto closes).
        self._crypto = crypto or default_crypto_reference()
        # Equity leg: an injected provider always wins (tests / alternate venues); otherwise prefer Alpaca when
        # keyed, else keyless Yahoo total-return — the same total-return closes the equity_dual_momentum_arm uses.
        self._equity = equity or _default_equity_provider(settings)

    def _asset_class(self, symbol: str, venue: str) -> str:
        """The asset class to price `symbol`@`venue` against. Prefer the instrument's own asset_class; if the
        instrument is not in the catalog, fall back to the venue's declared kind; if neither resolves, treat it
        as crypto (the historical default for this clock — never crash on an unknown row)."""
        try:
            return self.catalog.instrument(symbol, venue).asset_class
        except KeyError:
            pass
        try:
            return self.catalog.venue(venue).kind
        except KeyError:
            return "crypto"

    def provider_for(self, symbol: str, venue: str) -> MarketDataProvider:
        """The REAL pricing source for this position's asset class. equity/ETF → Yahoo total-return; everything
        else (crypto, the default) → Binance spot."""
        return self._equity if self._asset_class(symbol, venue) == "equity" else self._crypto

    def last_price(self, symbol: str, venue: str) -> Decimal:
        """Latest REAL daily close for a held position via its asset-class provider. 0 on any failure
        (offline / gap / unknown symbol) — never a synthetic fill; the caller skips the position."""
        return _last_price(self.provider_for(symbol, venue), symbol, self.catalog)


def mark_tracks(
    store: Store,
    *,
    market_data: MarketDataProvider | None = None,
    catalog: VenueCatalog | None = None,
    router: PricingRouter | None = None,
) -> dict[str, Decimal]:
    """THE PAPER CLOCK. Re-mark every HELD sim position against the latest REAL close — without opening,
    re-funding, or averaging anything — and write a portfolio_snapshot. This is what makes a track a genuine
    paper run: a funded track lives across bars and reveals honest net-of-fee P&L over calendar time, instead
    of the same-bar entry==mark snapshot the funding step produces. Cron-able (run on a schedule independent of
    the 4h author/fund tick); offline-safe (a missing mark just leaves that position at its last basis); live
    stays OFF (no orders — marks only).

    ASSET-AWARE: each held position is priced via a PricingRouter that routes by asset class — crypto → Binance,
    equity/ETF → Yahoo total-return — so equity tracks (GEM, the TAA fleet) accrue P&L instead of sitting flat.
    `market_data` (kept for back-compat) overrides ONLY the crypto leg; pass `router` to control both legs."""
    cat = catalog or default_catalog()
    pricer = router or PricingRouter(cat, crypto=market_data, settings=store.settings)
    portfolio = Portfolio(store, bankroll=store.settings.sim_bankroll)
    positions = [p for p in portfolio.positions() if p.qty != 0]
    marks: dict[str, Decimal] = {}
    for p in positions:
        # Route by the instrument's REAL catalog venue: order-path fills persist venue='sim' (a ledger label),
        # which the router can't price — an equity survivor funded via the order path would silently route to
        # the crypto leg and never mark. Arm-opened positions carry the real venue already; both resolve here.
        venue = _instrument_venue(cat, p.instrument_id) or p.venue
        price = pricer.last_price(p.symbol, venue)
        if price > 0:
            marks[p.instrument_id] = price
    # TWO-LEG NEUTRAL tracks (DERIVATIVES_PLAN P0.3): pair a held long-spot leg with its short-perp leg, accrue one
    # funding period on the short perp against its latest mark, and carry the running funding into the mark. A
    # single-leg spot track has no short leg → it is not a neutral pair → it falls straight through to the
    # unchanged spot mark path below. Offline-safe: no funding data for a perp leg accrues nothing this tick.
    funding_by_track = _accrue_neutral_funding(store, positions, marks)
    # BRUT cell resolver: place each position on its (version, symbol, venue) cell so the per-track snapshot
    # trajectory is cell-keyed — the cell's forward-proof + drift read ITS OWN series, never a sibling cell's.
    # The real venue is recovered from the instrument (order-path fills persist venue='sim'); None when unknown →
    # the portfolio falls back to the legacy version-only key.
    def _cell_resolver(p) -> tuple[str, str, str] | None:  # noqa: ANN001 — PositionView
        if p.strategy_version_id is None:
            return None
        venue = _instrument_venue(cat, p.instrument_id) or p.venue
        if venue == "sim" or not venue:
            return None  # can't place the cell honestly → legacy version-only key
        return (p.strategy_version_id, p.symbol, venue)

    snapshot = portfolio.mark_to_market(marks, funding_by_track=funding_by_track, cell_resolver=_cell_resolver)
    # Drive each CELL's tracks.return_pct from the LIVE marked trajectory (the cell-keyed per-track snapshot
    # mark_to_market just wrote), so the paper net P&L — not a stale seed — is what the leaderboard +
    # master/live_eligibility read for live_ready. EVERY held cell updates, including FLAT cells the executor
    # closed (their realized P&L must land in return_pct, not freeze pre-close).
    cells = [
        (r["strategy_version_id"], r["symbol"], _instrument_venue(cat, r["instrument_id"]) or r["venue"])
        for r in store.rows(
            "SELECT DISTINCT strategy_version_id, symbol, instrument_id, venue FROM positions WHERE strategy_version_id IS NOT NULL"
        )
    ]
    updated = _update_track_returns(store, cells)
    # STAGE PROMOTION: a paper entrant is born "screened" (badge: Backtest, backtest evidence only).
    # The paper clock — THIS function — promotes it to "paper" (badge: Paper) the moment it has accrued a real
    # forward day, so "Paper" honestly means "has forward evidence", never backtest-only. Badge-only relabel.
    tracked = {vid for vid, _s, _v in cells}
    promoted = _promote_screened_on_first_fill(store, tracked)
    store.append_event(
        actor="master",
        kind="tracks_marked",
        ref_type="portfolio",
        ref_id="aggregate",
        payload={
            "positions": len(positions),
            "marked": len(marks),
            "neutral_tracks": len(funding_by_track),
            "tracks_updated": updated,
            "promoted_to_paper": promoted,
            "equity": float(snapshot["equity"]),
            "pnl": float(snapshot["pnl"]),
        },
    )
    return snapshot


def _update_track_returns(store: Store, cells: list[tuple[str, str, str]]) -> int:
    """Refresh tracks.return_pct + tracks.equity for each held CELL from its latest cell-keyed per-track marked
    value (portfolio_snapshots scope='track' ref_id = version:symbol:venue), vs the cell track's own
    starting_capital. Each cell is matched on (version, symbol, venue) with a VERSION-only legacy fallback (a
    pre-migration version-wide track + version-keyed snapshot). Returns the count updated. A cell with no marked
    snapshot or no starting_capital is left untouched (offline-safe — never zero/synthetic-fill)."""
    updated = 0
    # Probe the LIVE tracks schema ONCE. Post-migration the cell columns exist → match on (version,symbol,venue)
    # and read the cell-keyed snapshot. Pre-migration (prod, columns absent) the cell-keyed SQL would raise
    # UndefinedColumn BEFORE any `if track is None` fallback could run, so we go STRAIGHT to the legacy
    # version-only path — byte-for-byte the pre-PR behaviour (mark_to_market also version-keys pre-migration).
    has_cell_cols = tracks_has_cell_columns(store)
    for vid, symbol, venue_id in cells:
        cid = cell_id(vid, symbol, venue_id)
        track = None
        ref = vid
        if has_cell_cols:
            # Cell-keyed first, then the legacy version-only key (legacy version-wide rows left by the migration).
            track = store.row(
                "SELECT starting_capital FROM tracks WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                (vid, symbol, venue_id),
            )
            if track is not None:
                ref = cid
                snap = store.row(
                    "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
                    (cid,),
                )
        if track is None:  # pre-migration table, OR a post-migration legacy version-wide track
            track = store.row("SELECT starting_capital FROM tracks WHERE strategy_version_id = ?", (vid,))
            ref = vid
            # mark_to_market cell-keys the snapshot (ref_id=version:symbol:venue) even for a legacy version-wide
            # track when the position resolves to a real cell — so read the CELL key FIRST (when columns exist),
            # then fall back to the legacy version key. Without this a version-wide equity track froze at its seed.
            snap = None
            if has_cell_cols:
                snap = store.row(
                    "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
                    (cid,),
                )
            if snap is None:
                snap = store.row(
                    "SELECT equity FROM portfolio_snapshots WHERE scope='track' AND ref_id=? ORDER BY ts DESC LIMIT 1",
                    (vid,),
                )
        if track is None or track.get("starting_capital") is None or snap is None or snap.get("equity") is None:
            continue
        starting = Decimal(str(track["starting_capital"]))
        if starting <= 0:
            continue
        marked_value = Decimal(str(snap["equity"]))
        return_pct = (marked_value / starting - Decimal("1")) * Decimal("100")
        if ref == cid:
            store.rows(
                "UPDATE tracks SET return_pct = ?, equity = ?, updated_at = ? "
                "WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
                (str(return_pct.quantize(Decimal("0.01"))), str(marked_value.quantize(Decimal("0.01"))),
                 utcnow(), vid, symbol, venue_id),
            )
        else:
            store.rows(
                "UPDATE tracks SET return_pct = ?, equity = ?, updated_at = ? WHERE strategy_version_id = ?",
                (str(return_pct.quantize(Decimal("0.01"))), str(marked_value.quantize(Decimal("0.01"))),
                 utcnow(), vid),
            )
        updated += 1
    return updated


def _has_paper_fills(store: Store, version_id: str) -> bool:
    """The precise "has this strategy actually STARTED TRADING on paper?" signal: >= 1 REAL paper fill in the
    executions log. This is exactly what the detail sheet reads ("no fills yet" / "needs >= 2 fills for a curve"),
    so the Paper badge and the sheet agree. NOTE: the documented rotation arms (research/*_arm.py) only
    apply_fill into the positions table and NEVER write executions, so a freshly-deployed arm that merely holds a
    static allocation has ZERO fills → it stays "screened" (Backtest) until a real forward trade lands, matching
    the operator's rule: 'Paper means the strategy has started trading.'"""
    return (
        store.row(
            "SELECT 1 FROM executions WHERE strategy_version_id = ? AND CAST(is_paper AS INTEGER) = 1 LIMIT 1",
            (version_id,),
        )
        is not None
    )


def _promote_screened_on_first_fill(store: Store, version_ids: set[str]) -> int:
    """Promote screened→paper for any just-marked version that has now recorded its FIRST real paper fill. This is
    what makes "Paper" honestly mean "has started trading on paper", never backtest-only or allocate-and-hold: a
    paper entrant is born "screened" (badge: Backtest) and earns the "Paper" badge only once a real trade
    lands in the executions log. Badge-only — the live/money gate reads track_opened, NOT status
    (master/live_eligibility), so this never changes what is live-armable. Idempotent: a version already 'paper',
    or still with no fills, is left untouched for the next tick to re-check. Returns the count promoted this tick."""
    promoted = 0
    for vid in version_ids:
        row = store.row("SELECT status FROM strategy_versions WHERE id = ?", (vid,))
        if row is None or row.get("status") != "screened":
            continue
        if not _has_paper_fills(store, vid):
            continue
        store.rows("UPDATE strategy_versions SET status = 'paper' WHERE id = ?", (vid,))
        store.append_event(
            actor="master",
            kind="status_promoted",
            ref_type="strategy_version",
            ref_id=vid,
            payload={"from": "screened", "to": "paper", "reason": "first_real_fill"},
        )
        promoted += 1
    return promoted


def reclassify_unforwarded_paper(store: Store) -> int:
    """The inverse of _promote_screened_on_first_fill, for EXISTING rows: demote any status='paper'
    version that has NO real paper fills yet back to 'screened' (badge: Backtest). Fixes rows stamped/promoted to
    'paper' without ever trading on paper (e.g. a documented arm that only holds a static allocation) — so "Paper"
    honestly means "has started trading". Idempotent + self-correcting: the paper clock re-promotes each one the
    moment its first real fill lands. Badge-only — the live gate reads track_opened, not status. Wired into boot
    via api._lifespan; lives here so the stage-transition logic stays in ONE module with its forward twin."""
    demoted = 0
    # Match every paper-ish status via PAPER_ALIASES (canonical 'paper' + the LEGACY 'forward_test' the
    # 2026-06-11 rename, applied by hand in Supabase, may not yet have collapsed). Matching only 'paper' once
    # left the documented arms stranded as 'forward_test' → badged "Paper" with ZERO fills. The has-fills guard
    # is unchanged, so a track that has genuinely traded on paper is never demoted.
    for r in store.rows(f"SELECT id, status FROM strategy_versions WHERE status IN {sql_in_list(PAPER_ALIASES)}"):
        vid = r["id"]
        if not _has_paper_fills(store, vid):
            store.rows("UPDATE strategy_versions SET status = 'screened' WHERE id = ?", (vid,))
            store.append_event(
                actor="master",
                kind="status_demoted",
                ref_type="strategy_version",
                ref_id=vid,
                payload={"from": r["status"], "to": "screened", "reason": "no_fills_yet"},
            )
            demoted += 1
    return demoted


def kickstart_paper_fills(store: Store) -> int:
    """One-shot, idempotent: record the documented arms' REAL held allocation as paper fills, so a strategy
    that is genuinely paper-trading (it HOLDS marked positions opened via apply_fill) finally reads "Paper"
    with a real fill blotter — instead of staying "Backtest" because its fills landed in `positions` but never
    in the `executions` ledger. For every screened version that holds open positions yet has ZERO paper fills,
    log one paper execution per open leg (the entry that established the leg: its real qty + average basis) and
    promote it screened→paper. HONEST: each execution MIRRORS a position the arm actually opened — it back-fills
    the missing ledger row, never invents a trade. Idempotent: once a version has fills it's skipped, so this is
    a no-op on every boot after the first."""
    candidates = store.rows(
        """
        SELECT DISTINCT sv.id FROM strategy_versions sv
        JOIN positions p ON p.strategy_version_id = sv.id
        WHERE sv.status = 'screened' AND CAST(p.qty AS REAL) <> 0
          AND NOT EXISTS (
              SELECT 1 FROM executions e WHERE e.strategy_version_id = sv.id AND CAST(e.is_paper AS INTEGER) = 1
          )
        """
    )
    promoted: set[str] = set()
    for c in candidates:
        vid = c["id"]
        legs = store.rows(
            "SELECT instrument_id, symbol, venue, qty, avg_price FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) <> 0",
            (vid,),
        )
        if not legs:
            continue
        rid = store.insert(
            "runs",
            {"strategy_version_id": vid, "mode": "paper", "venue_id": legs[0]["venue"], "seed": 0, "started_at": utcnow(), "status": "completed"},
        )
        for leg in legs:
            q = float(leg["qty"])
            store.insert(
                "executions",
                {
                    "run_id": rid, "strategy_version_id": vid, "instrument_id": leg["instrument_id"],
                    "venue_id": leg["venue"], "side": "buy" if q > 0 else "sell", "qty": str(abs(q)),
                    "price": str(leg["avg_price"]), "fee": "0", "slippage": "0", "order_type": "market",
                    "is_paper": 1, "ts": utcnow(), "fill_log": json.dumps({"source": "kickstart_backfill"}),
                },
            )
        promoted.add(vid)
    if promoted:
        _promote_screened_on_first_fill(store, promoted)
    return len(promoted)


def _accrue_neutral_funding(
    store: Store, positions: list, marks: dict[str, Decimal]
) -> dict[str, Decimal]:
    """For each two-leg neutral track, accrue one funding period on the short-perp leg (point-in-time rate from
    the `alt_data` store) and return {strategy_version_id: cumulative funding}. Empty when there are no neutral
    pairs — so the spot-only path adds nothing. Funding accrues only when a fresh perp mark exists this tick (the
    venue charges funding on live notional); a missing rate or mark accrues nothing (offline-safe, deterministic
    for a fixed store + marks)."""
    tracks = neutral_tracks(store, positions)
    out: dict[str, Decimal] = {}
    for track in tracks:
        perp_mark = marks.get(track.perp.instrument_id)
        rate = _funding_rate_asof(store, track.perp.symbol)
        if perp_mark is not None and perp_mark > 0 and rate is not None:
            total = accrue_funding(store, track, funding_rate=rate, perp_mark=perp_mark)
        else:
            # No fresh rate/mark → accrue nothing this tick (carry the prior cumulative forward unchanged). But a
            # LIVE perp leg WITH a fresh mark and NO funding rate is a DATA GAP (the alt_data funding series fell
            # behind / aged out), not "no funding due" — surface it LOUDLY instead of silently under-accruing P&L.
            # Invariant: the alt_data hot-retention horizon MUST exceed the funding mark cadence (cold-tier plan).
            # The cumulative is still carried unchanged; only the silence is removed.
            if perp_mark is not None and perp_mark > 0 and rate is None:
                store.append_event(
                    actor="loop",
                    kind="funding_rate_missing",
                    ref_type="strategy_version",
                    ref_id=track.strategy_version_id,
                    payload={"symbol": track.perp.symbol},
                )
            total = track.funding_accrued
        out[track.strategy_version_id] = total
    return out


def _funding_rate_asof(store: Store, symbol: str) -> Decimal | None:
    """The latest point-in-time funding rate for a perp symbol from the central alt_data store (the same series
    the ingest pass fills: provider 'binance', metric 'funding_rate'). None when no rate is on file — accrue
    nothing this tick (offline-safe).

    The symbol is mapped canonical→bare (alt_ingest_symbol) BEFORE the exact `WHERE symbol = ?` lookup: after the
    universal price layer (#338) a universe-path perp cell stamps the CANONICAL slash pair (BTC/USDT) on its
    position, but ingest keys funding by the BARE full-pair Binance perp symbol (BTCUSDT) — without the map the
    exact match misses on the prod Postgres store and the short-perp leg silently UNDER-ACCRUES funding P&L,
    distorting the forward record. Idempotent on an already-bare symbol (the empty-universe fallback path), so
    both screen paths read the identical key — mirrors the #341 fix on the screen path (_alt_by_cell)."""
    ingest_symbol = alt_ingest_symbol(symbol)
    # COLLATE "C" so the "latest available" pick is binary/chronological on Postgres (its en_US.UTF-8 collation
    # would otherwise mis-order a fractional-second available_at — see PgAltDataStore.read_asof). Postgres-only.
    c = ' COLLATE "C"' if getattr(store, "_is_pg", False) else ""
    row = store.row(
        "SELECT value FROM alt_data WHERE provider = 'binance' AND symbol = ? AND metric = 'funding_rate' "
        f"ORDER BY available_at{c} DESC, id DESC LIMIT 1",
        (ingest_symbol,),
    )
    return Decimal(str(row["value"])) if row else None


# The hourly intraday lane steps ONLY sub-daily horizons: crypto bars are closed-candle-guarded (data/market),
# while the Yahoo equity source serves an in-progress day bar — so daily tracks stay on the daily clocks.
_INTRADAY_BAR_SIZES = frozenset({"1h", "4h"})


def _main(argv: list[str] | None = None) -> int:
    """Railway cron entrypoint for the PAPER CLOCK: first the EXECUTOR (paper_step.step_tracks — each
    gate-lane track's OWN spec/params decide exits and re-entries through the one order path, sim-only), then
    the MARK (re-mark every held sim position against the latest REAL close, routed by asset class — crypto →
    Binance, equity/ETF → Yahoo total-return). Step-then-mark so the snapshot reflects post-trade state.

    Three cadences, one entrypoint (re-running on the same closed bar is always a no-op — decision-bar coids):
      `python3 -m cosmu.orchestrator.loop`             full clock (daily crons, 00:10 + 22:10 UTC)
      `python3 -m cosmu.orchestrator.loop --intraday`  hourly lane: step sub-daily (1h/4h) tracks, then mark all
      `python3 -m cosmu.orchestrator.loop --mark-only` marks only (no executor step) — freshness without trades
    """
    import argparse

    from cosmu.config.settings import Settings
    from cosmu.orchestrator.paper_step import step_tracks

    parser = argparse.ArgumentParser(
        description="Run the paper executor (each track's own exits/entries, sim-only) then mark held positions to the latest real close, asset-aware."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--intraday", action="store_true",
                      help="step only sub-daily (1h/4h) tracks, then mark all held positions (the hourly lane)")
    mode.add_argument("--mark-only", action="store_true",
                      help="skip the executor step; just re-mark held positions to the latest real close")
    args = parser.parse_args(argv)
    store = Store(Settings())
    if not args.mark_only:
        step = step_tracks(store, bar_sizes=_INTRADAY_BAR_SIZES if args.intraday else None)
        lane = "intraday" if args.intraday else "full"
        print(f"FORWARD-TEST STEP ({lane}) — managed={step.managed} closed={step.closed} opened={step.opened} "
              f"skipped(deploy/unmanaged)={step.skipped_deploy}/{step.skipped_unmanaged}")
    snap = mark_tracks(store)
    print(f"SIM MARK-TO-MARKET — equity={float(snap['equity']):.2f} pnl={float(snap['pnl']):+.2f} drawdown={float(snap['drawdown']):.4f}")
    return 0


def _last_price(provider: MarketDataProvider, symbol: str, catalog: VenueCatalog) -> Decimal:
    try:
        bars = provider.fetch_bars(symbol, "1d", limit=2)
    except Exception:  # noqa: BLE001 — offline/no-network: no fresh mark for this symbol, skip it
        return Decimal("0")
    if not bars:
        return Decimal("0")
    return bars[-1].close


if __name__ == "__main__":
    raise SystemExit(_main())
