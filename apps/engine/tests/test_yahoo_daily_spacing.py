# intent: lock the Yahoo daily-bars provider against the `range=max` → MONTHLY-downgrade bug. Yahoo silently
# served ~30-day-spaced bars despite interval=1d (and the _1d.json filename), corrupting every equity daily
# backtest. The provider now uses an explicit period window; the poison-detector below invalidates any cache
# that is monthly-spaced so it is re-fetched as true daily history.
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from cosmu.data.market import _is_daily_spaced


def _bars(step_days: int, n: int = 30):
    base = datetime(2020, 1, 1, tzinfo=UTC)
    return [SimpleNamespace(ts=base + timedelta(days=step_days * i)) for i in range(n)]


def test_daily_spaced_true_for_daily_bars():
    assert _is_daily_spaced(_bars(1)) is True


def test_daily_spaced_false_for_monthly_bars():
    # the exact corruption shape: ~30-day gaps despite a _1d.json filename
    assert _is_daily_spaced(_bars(30)) is False


def test_short_series_not_flagged():
    assert _is_daily_spaced(_bars(30, n=3)) is True  # too few points to judge — never false-positive
