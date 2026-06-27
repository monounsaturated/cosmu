# intent: the SCREEN-DEPTH lever (LOT C) — one helper that decides how many bars the finder/loop read PER SCREEN.
# DEFAULT (deep=False) returns TODAY's exact 1500-if-1h-else-1000 mapping, so a normal production screen passes the
# IDENTICAL `limit` it always has → byte-identical bars in, byte-identical gate verdict out. `deep=True` (an explicit
# OPT-IN, never a persisted spec field) returns a large sentinel (DEEP_BAR_LIMIT) that means "serve everything the
# merged cache already holds": data/market.py truncates on the way out via `merged[-limit:]`, so a limit larger than
# the cache returns the whole cache unchanged (it does NOT backfill — a deep screen only sees the depth already in the
# local cache). The opt-in is sourced from the env knob COSMU_SCREEN_DEEP (mirrors data/price_cells.per_venue_bars_
# enabled) OR an explicit caller argument (the re-screen harness) — so the Gate inputs of an authored spec never change.

from __future__ import annotations

import os

from cosmu.strategy.spec import StrategySpec

# Today's shallow-window mapping — the EXACT constants finder.py:418 and loop._bar_limit compute today. 1h gets the
# deeper 1500-bar window (an hour-bar strategy needs more bars for the same calendar span); everything else (4h/1d)
# reads 1000. Keep these in ONE place so the two screen choke points can never drift.
_SHALLOW_1H_LIMIT = 1500
_SHALLOW_DEFAULT_LIMIT = 1000

# The deep sentinel — large enough that `merged[-limit:]` (data/market.py) returns the WHOLE merged cache unchanged.
# It is NOT a fetch target (ccxt/REST single-page fetch still caps at its own page size); it only un-truncates what the
# local cache already holds. 100_000 bars = ~11 years of hourly data, far beyond any cached series.
DEEP_BAR_LIMIT = 100_000

# The env knob — DEFAULT OFF (mirrors per_venue_bars_enabled). When unset, screen_depth(deep defaulting to this) is the
# shallow mapping, so the cron/finder are byte-identical.
_DEEP_ENV = "COSMU_SCREEN_DEEP"


def screen_deep_enabled() -> bool:
    """True iff COSMU_SCREEN_DEEP is set truthy. DEFAULT OFF → the byte-identical 1500/1000 shallow window."""
    return os.environ.get(_DEEP_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def screen_depth(spec: StrategySpec, *, deep: bool | None = None) -> int:
    """The per-screen bar `limit`.

    deep is None (the DEFAULT) → read the env knob (screen_deep_enabled); deep True/False → an explicit caller override
    (the re-screen harness). When the resolved flag is False the result is TODAY's 1500-if-1h-else-1000 mapping (a normal
    production screen is byte-identical); when True it is DEEP_BAR_LIMIT (serve the whole merged cache). The flag is an
    EXECUTION-TIME knob (env / arg), never a persisted spec field — so an authored spec's Gate inputs never change."""
    use_deep = screen_deep_enabled() if deep is None else deep
    if use_deep:
        return DEEP_BAR_LIMIT
    return _SHALLOW_1H_LIMIT if spec.horizon.bar_size == "1h" else _SHALLOW_DEFAULT_LIMIT
