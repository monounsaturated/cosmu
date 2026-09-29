# intent: decompose a StrategySpec into content-hashed, reusable BUILDING BLOCKS (signal · filter · setup ·
# exit · sizing) so identical logic is recognized across strategies regardless of param NAMES; inputs: a
# StrategySpec; outputs: typed Block rows + a whole-spec combo_hash; invariants: pure + deterministic (same
# structure ⇒ same hash, param names canonicalized away), NEVER consulted by the scorer/Gate/FDR — blocks are
# bookkeeping for dedup + observational lineage, the deterministic Gate alone funds.

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from cosmu.strategy.spec import Condition, ParamRef, StrategySpec

BLOCK_KINDS = ("signal", "filter", "setup", "exit", "sizing")


@dataclass(frozen=True)
class Block:
    """One reusable unit of strategy logic. `payload` is the canonical structure (param names replaced by
    positional placeholders, each placeholder carrying its SEARCH RANGE — never a fitted value), `block_hash`
    its content address, `label` a human one-liner for the UI/leaderboard."""

    kind: str
    label: str
    payload: dict[str, Any]
    block_hash: str


class _Canon:
    """Per-block canonicalizer: maps ParamRef names to positional placeholders (p0, p1, …) in order of first
    appearance and records each placeholder's ParamSpace, so two blocks with identical structure + identical
    search ranges hash equal even when their authors named the params differently."""

    def __init__(self, spec: StrategySpec) -> None:
        self._space = spec.param_space
        self._names: dict[str, str] = {}
        self.space: dict[str, Any] = {}

    def ref(self, ref: ParamRef | None) -> str | None:
        if ref is None:
            return None
        if ref.param not in self._names:
            ph = f"p{len(self._names)}"
            self._names[ref.param] = ph
            ps = self._space.get(ref.param)
            self.space[ph] = ps.model_dump(mode="json") if ps is not None else None
        return self._names[ref.param]

    def lookback(self, lb: ParamRef | int | None) -> Any:
        return self.ref(lb) if isinstance(lb, ParamRef) else lb


def _hash(kind: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(f"{kind}:{json.dumps(payload, sort_keys=True)}".encode()).hexdigest()


def _condition_payload(c: Condition, canon: _Canon) -> dict[str, Any]:
    return {
        "feature": c.feature.name,
        "lookback": canon.lookback(c.feature.lookback),
        "op": c.op,
        "threshold": canon.ref(c.threshold),
    }


def _block(kind: str, label: str, body: dict[str, Any], canon: _Canon) -> Block:
    payload = {**body, "space": canon.space}
    return Block(kind=kind, label=label, payload=payload, block_hash=_hash(kind, payload))


def decompose(spec: StrategySpec) -> list[Block]:
    """Split a spec into its typed blocks. One signal block PER entry condition (the unit `evolve` isolates),
    one block per setup module, one exit block (the whole trade-management plan), one sizing block."""
    blocks: list[Block] = []

    for c in spec.entry:
        canon = _Canon(spec)
        body = _condition_payload(c, canon)
        blocks.append(_block("signal", f"{c.feature.name} {c.op} [fitted]", body, canon))

    setup = spec.setup
    if setup is not None:
        if setup.ma_trend_filter is not None:
            canon = _Canon(spec)
            body = {"ma_lookback": canon.ref(setup.ma_trend_filter.ma_lookback)}
            blocks.append(_block("filter", "MA trend filter", body, canon))
        if setup.orb is not None:
            canon = _Canon(spec)
            body = {
                "range_bars": canon.ref(setup.orb.range_bars),
                "buffer": canon.ref(setup.orb.buffer),
                "anchor": setup.orb.anchor,
            }
            blocks.append(_block("setup", f"ORB breakout ({setup.orb.anchor})", body, canon))
        if setup.fvg is not None:
            canon = _Canon(spec)
            body = {"max_retests": canon.ref(setup.fvg.max_retests), "gap_min": canon.ref(setup.fvg.gap_min)}
            blocks.append(_block("setup", "FVG retest", body, canon))

    canon = _Canon(spec)
    ex = spec.exit
    exit_body: dict[str, Any] = {
        "stop_loss": canon.ref(ex.stop_loss),
        "take_profit": canon.ref(ex.take_profit),
        "time_stop_days": canon.ref(ex.time_stop_days),
        "signal_exits": [_condition_payload(c, canon) for c in ex.signal_exits],
    }
    plan_bits: list[str] = []
    if ex.plan is not None:
        exit_body["plan"] = {
            "multi_tp": [{"at": canon.ref(leg.at), "size_pct": canon.ref(leg.size_pct)} for leg in ex.plan.multi_tp],
            "break_even_after_tp1": ex.plan.break_even_after_tp1,
            "runner_trail": canon.ref(ex.plan.runner_trail),
        }
        if ex.plan.multi_tp:
            plan_bits.append(f"{len(ex.plan.multi_tp)}-leg TP")
        if ex.plan.runner_trail is not None:
            plan_bits.append("runner trail")
    bits = ["stop/take"]
    if ex.time_stop_days is not None:
        bits.append("time-stop")
    if ex.signal_exits:
        bits.append("signal-exit")
    bits.extend(plan_bits)
    blocks.append(_block("exit", " + ".join(bits), exit_body, canon))

    canon = _Canon(spec)
    sizing_body: dict[str, Any] = {
        "max_concurrent_positions": spec.risk.max_concurrent_positions,
        "max_position_pct": spec.risk.max_position_pct,
        "conviction": spec.risk.conviction,
        "direction": spec.direction,
        "funding_feature": spec.funding_feature,
    }
    if spec.meta_label is not None:
        sizing_body["meta_label"] = {
            "features": sorted(f.name for f in spec.meta_label.features),
            "prob_threshold": canon.ref(spec.meta_label.prob_threshold),
            "sizing": spec.meta_label.sizing,
        }
    label = f"risk {spec.risk.max_position_pct:.0%}/pos" + (" · meta-label" if spec.meta_label else "")
    blocks.append(_block("sizing", label, sizing_body, canon))

    return blocks


def combo_hash(spec: StrategySpec) -> str:
    """Content address for the WHOLE hypothesis: the sorted block hashes plus where/when it trades. Two specs
    with the same combo_hash are the SAME hypothesis — re-screening one is a duplicate trial, not a new idea
    (protects the multiple-testing budget). Universe/horizon/lane are part of the identity: the same signal on
    a different market or bar size IS a different hypothesis (that is exactly what a graft tests)."""
    parts = {
        "blocks": sorted(b.block_hash for b in decompose(spec)),
        "venues": sorted(spec.universe.venues),
        "asset_classes": sorted(spec.universe.asset_classes),
        "bar_size": spec.horizon.bar_size,
        "hold": [spec.horizon.min_hold_days, spec.horizon.max_hold_days],
        "lane": spec.lane,
        "direction": spec.direction,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
