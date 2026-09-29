# intent: the DATA-VERSION fingerprint — turn the exact bars a finder/gate run consumed into a short,
# deterministic hash so two runs are COMPARABLE (same fingerprint ⇒ same data) and a result is EXACTLY
# REGENERABLE (record the fingerprint, re-supply matching data, re-run → identical numbers). inputs: a market
# dict (single- or cross-asset shape); outputs: a 16-hex content hash + a structured fingerprint; invariants:
# PURE + offline (no clock, no store, no network), order-independent (symbols sorted), and stable across runs
# for identical inputs — the same property `config_tag` relies on in the finder.

from __future__ import annotations

import hashlib
import json
from typing import Any

# The sentinel data_version for a run that consumed NO bars (e.g. fully offline with an empty cache). Still a
# valid, comparable key — it says "this run saw nothing", which is itself reproducible.
EMPTY_DATA_VERSION = "data:empty"


def _bar_fingerprint(bars: list[Any]) -> dict[str, Any]:
    """A compact, deterministic fingerprint of ONE bar series: count + first/last timestamp + first/last close.
    Enough to detect any change in the data window or its contents without hashing every bar (cheap + stable).
    A Bar exposes `.ts` (datetime) and `.close` (Decimal/float); both render deterministically via str()."""
    if not bars:
        return {"n": 0}
    first, last = bars[0], bars[-1]
    return {
        "n": len(bars),
        "first_ts": str(first.ts),
        "last_ts": str(last.ts),
        "first_close": str(first.close),
        "last_close": str(last.close),
    }


def _is_nested(market: dict[str, Any]) -> bool:
    """Cross-asset shape is dict[class -> dict[symbol -> bars]]; single-asset is dict[symbol -> bars]."""
    for v in market.values():
        return isinstance(v, dict)
    return False


def _flatten(market: dict[str, Any]) -> dict[str, list[Any]]:
    """Collapse a cross-asset {class: {symbol: bars}} into {class/symbol: bars} so both shapes fingerprint the
    same way. Single-asset markets pass through unchanged."""
    if not _is_nested(market):
        return dict(market)
    out: dict[str, list[Any]] = {}
    for klass, symbols in market.items():
        for symbol, bars in symbols.items():
            out[f"{klass}/{symbol}"] = bars
    return out


def fingerprint(market: dict[str, Any]) -> dict[str, Any]:
    """The structured, human-readable fingerprint of a run's input data: per-series counts/spans, sorted by
    series key so it is order-independent. The hash in `data_version` is computed over exactly this object."""
    flat = _flatten(market)
    return {series: _bar_fingerprint(bars) for series, bars in sorted(flat.items())}


def data_version(market: dict[str, Any]) -> str:
    """A short deterministic hash of the EXACT bars a run consumed — accepts both the single-asset
    (dict[symbol -> bars]) and cross-asset (dict[class -> dict[symbol -> bars]]) shapes. Returns
    `EMPTY_DATA_VERSION` for an empty market. Same data ⇒ same string, so runs are comparable and regenerable."""
    fp = fingerprint(market)
    if not fp or all(v.get("n", 0) == 0 for v in fp.values()):
        return EMPTY_DATA_VERSION
    blob = json.dumps(fp, sort_keys=True, separators=(",", ":"))
    return "data:" + hashlib.sha256(blob.encode()).hexdigest()[:16]
