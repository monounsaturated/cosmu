# The honest per-symbol verdict (master/per_symbol.py): a VISIBILITY label, never a funding gate. These prove the
# anti-best-of-N contract — a lone winner among losers is FRAGILE (caution), a corroborated edge is ROBUST — plus
# the thin/negative/edge cases. The label uses only stored summary stats (return + trades), no streams.

from __future__ import annotations

from cosmu.master.per_symbol import (
    FRAGILE,
    GENERALIZE_FRACTION,
    MIN_TRADES_PER_SYMBOL,
    NEGATIVE,
    ROBUST,
    THIN,
    VERDICTS,
    classify_per_symbol,
    edge_generalizes,
    rank_deploy_symbols,
)


def _cell(symbol, verdict, sharpe=0.0):
    return {"symbol": symbol, "verdict": verdict, "sharpe": sharpe}


def test_rank_deploy_symbols_robust_before_fragile_then_sharpe():
    """The funder must land capital on the PROVEN cell: ROBUST ranks strictly above FRAGILE (a lone best-of-N
    winner), and within a verdict the higher Sharpe leads. THIN/NEGATIVE are never deployable (dropped)."""
    cells = [
        _cell("XRP", FRAGILE, 9.0),     # high sharpe but only fragile → must rank BELOW any robust
        _cell("SOL", ROBUST, 1.0),
        _cell("BTC", ROBUST, 2.5),      # best: robust + highest sharpe
        _cell("DOGE", NEGATIVE, 5.0),   # dropped
        _cell("ADA", THIN, 5.0),        # dropped
    ]
    assert rank_deploy_symbols(cells) == ["BTC", "SOL", "XRP"]


def test_rank_deploy_symbols_excludes_non_edges_and_handles_empty():
    """A version with no ROBUST/FRAGILE cell yields an empty deploy order (caller falls back to round-robin)."""
    assert rank_deploy_symbols([_cell("BTC", THIN), _cell("ETH", NEGATIVE)]) == []
    assert rank_deploy_symbols([]) == []


def test_rank_deploy_symbols_dedup_and_bad_sharpe_safe():
    """Repeated symbols (a re-screened version) keep the best-ranked occurrence; a non-numeric Sharpe is treated
    as 0.0, never raising."""
    cells = [_cell("BTC", FRAGILE, 1.0), _cell("BTC", ROBUST, "n/a"), _cell("ETH", ROBUST, 3.0)]
    assert rank_deploy_symbols(cells) == ["ETH", "BTC"]  # ETH robust+3.0 > BTC robust+0.0; BTC de-duped to robust


def _ps(**symbols: tuple[float, int]) -> dict[str, dict[str, float]]:
    """Build a BacktestResult.per_symbol-shaped dict: name=(return, trades)."""
    return {s: {"return": r, "sharpe": 0.0, "max_drawdown": 0.0, "trades": float(t)} for s, (r, t) in symbols.items()}


def test_lone_winner_among_losers_is_fragile_not_celebrated():
    """THE best-of-N trap: 1 strong winner, 4 losers — all judgeable. The winner must be FRAGILE (the edge does not
    generalize: 1/5 < 0.5), surfaced with caution, never sold as a proven edge. This is the exact thing the operator
    refused to let the machine fund on."""
    out = classify_per_symbol(_ps(BTC=(0.40, 50), ETH=(-0.05, 50), SOL=(-0.08, 50), XRP=(-0.02, 50), BNB=(-0.10, 50)))
    assert out["BTC"] == FRAGILE
    assert out["ETH"] == out["SOL"] == out["XRP"] == out["BNB"] == NEGATIVE


def test_corroborated_edge_is_robust():
    """A genuinely generalizing edge: 3 of 5 judgeable symbols win (3/5 >= 0.5). Every winner is ROBUST; the losers
    are NEGATIVE. This is the cross-asset corroboration the best-of-N artefact lacks."""
    out = classify_per_symbol(_ps(BTC=(0.20, 40), ETH=(0.12, 40), SOL=(0.08, 40), XRP=(-0.03, 40), BNB=(-0.05, 40)))
    assert out["BTC"] == out["ETH"] == out["SOL"] == ROBUST
    assert out["XRP"] == out["BNB"] == NEGATIVE


def test_thin_cells_are_excluded_from_generalization_denominator():
    """A cell below the trade floor is THIN and cannot anchor or dilute generalization. Here only 2 cells are
    judgeable (both winners → 2/2 generalizes), so the thin cell is THIN and the two judgeable winners are ROBUST —
    a swarm of zero-trade symbols can neither prove nor poison the edge."""
    out = classify_per_symbol(_ps(BTC=(0.20, 40), ETH=(0.10, 40), SOL=(0.50, MIN_TRADES_PER_SYMBOL - 1)))
    assert out["SOL"] == THIN
    assert out["BTC"] == out["ETH"] == ROBUST


def test_single_symbol_winner_is_robust_no_selection_bias():
    """N=1 judgeable symbol: there was NO best-of-N selection, so a positive single-symbol result is ROBUST (not
    fragile). Fragility is specifically about picking the best of MANY; one symbol can't be cherry-picked."""
    assert classify_per_symbol(_ps(BTC=(0.15, 30)))["BTC"] == ROBUST


def test_all_thin_or_empty_yields_no_winners():
    """No judgeable cell → nothing generalizes; every cell is THIN. Empty input → empty map. Never raises."""
    out = classify_per_symbol(_ps(BTC=(0.9, 1), ETH=(0.9, 2)))
    assert out == {"BTC": THIN, "ETH": THIN}
    assert classify_per_symbol({}) == {}
    assert classify_per_symbol(None) == {}


def test_zero_return_is_negative_not_winner():
    """Exactly-zero return is non-positive → NEGATIVE (a flat book is not an edge), so it never counts toward
    generalization. The lone real winner beside it is therefore FRAGILE."""
    out = classify_per_symbol(_ps(BTC=(0.20, 40), ETH=(0.0, 40), SOL=(-0.1, 40)))
    assert out["ETH"] == NEGATIVE
    assert out["BTC"] == FRAGILE  # 1/3 judgeable winners < 0.5 → does not generalize


def test_edge_generalizes_threshold_is_the_single_knob():
    """edge_generalizes is the one tunable: 2/4 winners == GENERALIZE_FRACTION (0.5) generalizes; raising the bar
    flips it. Proves the methodology is a localized change, not a scattered constant."""
    cells = classify_per_symbol  # alias to keep the import used; build cells directly below
    from cosmu.master.per_symbol import _cells_from_per_symbol

    c = _cells_from_per_symbol(_ps(A=(0.1, 20), B=(0.1, 20), C=(-0.1, 20), D=(-0.1, 20)))
    assert GENERALIZE_FRACTION == 0.5
    assert edge_generalizes(c) is True                                  # 2/4 == 0.5
    assert edge_generalizes(c, generalize_fraction=0.6) is False        # 2/4 < 0.6
    assert cells is classify_per_symbol


def test_every_verdict_is_in_the_vocabulary():
    """Whatever the inputs, the label is always one of the four known verdicts (no stray strings leak to the DB)."""
    out = classify_per_symbol(_ps(BTC=(0.2, 40), ETH=(-0.1, 40), SOL=(0.5, 2)))
    assert set(out.values()) <= VERDICTS
