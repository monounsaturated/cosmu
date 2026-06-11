# intent: a MINIMAL, READ-ONLY engine/Gate query surface for Claude Code — pure handler functions that
# take an explicit Store and answer "what does the machine currently know / decide?" without moving money;
# inputs: a Store (a tmp SQLite store in tests, the live store in prod) + small read params; outputs: plain
# JSON-able dicts/lists; invariants: every handler is READ-ONLY (SELECT-only DB reads + propose-only Gate
# evaluation on deterministic fixtures), reuses engine functions (never reimplements the Gate), and NEVER
# arms an order, funds a track, toggles live, or loosens the Gate. Offline-testable: pass a tmp Store, no network.
#
# The server.py FastMCP wrappers are thin shells over these handlers; the deterministic Gate stays entirely
# in apps/engine/cosmu/research/gate.py — we import and call it, we do not copy its logic.

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cosmu.knowledge.store import Store


# ---------------------------------------------------------------------------
# DB read tools — SELECT-only, via the engine's own Store.rows() reader.
# ---------------------------------------------------------------------------


def list_strategies(store: Store, *, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """The N most recent strategies, each with its LATEST version's status.

    status filter: 'funded' | 'killed' | 'active' | None (all). Read-only: a single SELECT — never writes,
    never authors, never funds. `limit`/`status` are bound as parameters (no SQL string interpolation)."""
    limit = max(1, min(int(limit), 200))
    params: list[Any] = []
    where = ""
    if status is not None:
        where = "AND sv.status = ? "
        params.append(status)
    params.append(limit)
    rows = store.rows(
        """
        SELECT s.id, s.name, s.thesis, sv.status, sv.origin, sv.created_at, sv.killed_at, sv.kill_reason
        FROM strategies s
        JOIN strategy_versions sv ON sv.strategy_id = s.id
        WHERE sv.id = (
            SELECT id FROM strategy_versions WHERE strategy_id = s.id ORDER BY created_at DESC LIMIT 1
        )
        """
        + where
        + "ORDER BY sv.created_at DESC LIMIT ?",
        tuple(params),
    )
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "thesis": r["thesis"],
            "status": r["status"],
            "origin": r["origin"],
            "created_at": r["created_at"],
            "killed_at": r["killed_at"],
            "kill_reason": r["kill_reason"],
        }
        for r in rows
    ]


def list_tracks(store: Store, *, limit: int = 20) -> list[dict[str, Any]]:
    """The N most recently-updated paper tracks (one standalone track per funded survivor — there is NO
    pooled wallet). Read-only: a single SELECT. `equity`/`return_pct` here are the track's marked state; this
    tool reads them, it never marks or moves them."""
    limit = max(1, min(int(limit), 200))
    rows = store.rows(
        """
        SELECT t.id, t.strategy_version_id, s.name, t.starting_capital, t.equity, t.return_pct, t.updated_at
        FROM tracks t
        JOIN strategy_versions sv ON sv.id = t.strategy_version_id
        JOIN strategies s ON s.id = sv.strategy_id
        ORDER BY t.updated_at DESC LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "track_id": r["id"],
            "strategy_version_id": r["strategy_version_id"],
            "name": r["name"],
            "starting_capital": _num(r["starting_capital"]),
            "equity": _num(r["equity"]),
            "return_pct": _num(r["return_pct"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def read_gate_verdicts(store: Store, *, limit: int = 10) -> list[dict[str, Any]]:
    """The N most recent Gate verdicts (PASS/STOP) from the verdict ledger. Read-only: a single SELECT over
    gate_verdicts. `payload` is the stored JSON string left as-is (the caller parses it if needed)."""
    limit = max(1, min(int(limit), 100))
    rows = store.rows(
        "SELECT ts, decision, data_source, payload FROM gate_verdicts ORDER BY ts DESC LIMIT ?",
        (limit,),
    )
    return [
        {"ts": r["ts"], "decision": r["decision"], "data_source": r["data_source"], "payload": r["payload"]}
        for r in rows
    ]


def read_leaderboard(store: Store, *, limit: int = 20) -> list[dict[str, Any]]:
    """The gate-ranked strategy leaderboard (most-significant first), joined to each version's backtest. A
    pure read-out — SELECT-only, no money path. Mirrors the shape the API leaderboard router serves, kept
    minimal here so Claude Code can read the standings without a running web server."""
    limit = max(1, min(int(limit), 100))
    rows = store.rows(
        """
        SELECT sv.id, s.name, sv.status, sv.origin,
               b.deflated_sharpe, b.oos_return, b.pbo, b.num_trades, b.max_dd
        FROM strategy_versions sv
        JOIN strategies s ON s.id = sv.strategy_id
        LEFT JOIN backtests b ON b.strategy_version_id = sv.id
        ORDER BY CAST(COALESCE(b.deflated_sharpe, 0) AS REAL) DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "version_id": r["id"],
            "name": r["name"],
            "status": r["status"],
            "origin": r["origin"],
            "deflated_sharpe": _num(r["deflated_sharpe"]),
            "oos_return": _num(r["oos_return"]),
            "pbo": _num(r["pbo"]),
            "num_trades": _int(r["num_trades"]),
            "max_drawdown": _num(r["max_dd"]),
        }
        for r in rows
    ]


def read_overview(store: Store) -> dict[str, Any]:
    """The aggregate paper read-out: the Σ-equity curve across all standalone tracks, net PnL, the
    spend-by-category slice, and whether live trading is enabled. A pure read-out (no pooled wallet) — every
    query is a SELECT and no value is ever written."""
    snapshots = store.rows(
        "SELECT ts, equity, pnl FROM portfolio_snapshots WHERE scope = 'aggregate' ORDER BY ts ASC LIMIT 120"
    )
    curve = [{"ts": r["ts"], "value": _num(r["equity"])} for r in snapshots]
    pnl_net = _num(snapshots[-1]["pnl"]) if snapshots else 0.0
    cost_rows = store.rows("SELECT category, SUM(CAST(amount AS REAL)) AS amount FROM costs GROUP BY category")
    costs = [{"category": r["category"], "amount": _num(r["amount"])} for r in cost_rows]
    live_row = store.row("SELECT enabled FROM live_toggle WHERE id = 'global'")
    return {
        "equity_curve": curve,
        "pnl_net": pnl_net,
        "costs": costs,
        "live_enabled": bool(live_row and live_row["enabled"]),
    }


# ---------------------------------------------------------------------------
# Propose-only Gate evaluation — runs the REAL single-signal Gate on deterministic
# offline fixtures and returns the PASS/STOP verdict. It moves no money and funds
# no track: the Gate only ever EMITS a verdict; arming a survivor is a separate,
# human-gated step that this read-only surface deliberately does not expose.
# ---------------------------------------------------------------------------


def evaluate_signal_gate(store: Store, *, edge: bool = True, seed: int = 7, n: int = 600) -> dict[str, Any]:
    """Run the deterministic single-signal edge Gate (cosmu.research.gate.evaluate_gate) on synthetic,
    point-in-time fixtures and return its PASS/STOP verdict as plain JSON.

    PROPOSE-ONLY / READ-ONLY by construction: evaluate_gate computes a verdict and records the attempts in the
    trial ledger (honest multiple-testing accounting) — it NEVER funds a track, arms an order, or toggles live.
    `edge=True` yields edge-bearing fixtures (the wall should find the planted relationship); `edge=False` is
    the label-permutation-style null where an honest Gate MUST STOP. We import and call the real Gate — we do
    not reimplement or relax its pre-registered bar."""
    from cosmu.research.fixtures import synthetic_gate_inputs
    from cosmu.research.gate import evaluate_gate

    market, altdata = synthetic_gate_inputs(edge=bool(edge), seed=int(seed), n=int(n))
    verdict = evaluate_gate(market, altdata, store)
    return asdict(verdict)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _num(value: Any) -> float:
    """Coerce a possibly-Decimal/None numeric to a finite float (0.0 on missing/garbage) — the API contract."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float("inf"), float("-inf")) else 0.0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
