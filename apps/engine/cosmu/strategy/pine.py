# intent: translate a TradingView Pine Script strategy/indicator into a typed StrategySpec so mined OSS strategies can enter the same deterministic farm; inputs: pine source text; outputs: PineTranslation(spec + parse report); invariants: Pine's hardcoded thresholds are lifted into a fitted param_space (never kept as magic numbers), every referenced feature maps to the registry, and the result passes static_check.

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from cosmu.config.feature_registry import feature_names
from cosmu.strategy.spec import (
    Condition,
    ExitRules,
    FeatureRef,
    Horizon,
    ParamRef,
    ParamSpace,
    RiskRules,
    StrategySpec,
    UniverseSelector,
)
from cosmu.strategy.static_check import validate_spec

# Pine ta.* function → our named feature vocabulary.
PINE_FEATURE_MAP: dict[str, str] = {
    "rsi": "rsi",
    "cci": "rsi",
    "mfi": "rsi",
    "stoch": "rsi",
    "atr": "atr",
    "adx": "adx",
    "dmi": "adx",
    "sma": "ret_Nd",
    "ema": "ret_Nd",
    "wma": "ret_Nd",
    "vwma": "ret_Nd",
    "hma": "ret_Nd",
    "mom": "ret_Nd",
    "roc": "ret_Nd",
    "change": "ret_Nd",
    "stdev": "vol_realized",
    "variance": "vol_realized",
    "bb": "bb_z",
    "bbw": "bb_z",
}

# 0–100 bounded oscillators → keep thresholds inside [0, 100] when widening.
BOUNDED_0_100 = {"rsi", "adx"}

_NUM = r"[-+]?\d*\.?\d+"


@dataclass
class PineTranslation:
    spec: StrategySpec
    source_hash: str
    indicators: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lifted_params: dict[str, float] = field(default_factory=dict)


def _strip_comments(src: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


def _threshold_space(feature: str, literal: float) -> ParamSpace:
    """Lift a hardcoded threshold into a search range around it (numbers fit from data)."""
    if feature in BOUNDED_0_100:
        lo = max(0.0, round(literal * 0.6, 3))
        hi = min(100.0, round(literal * 1.4 + 1, 3))
    elif abs(literal) >= 1:
        lo = round(literal - abs(literal) * 0.5, 4)
        hi = round(literal + abs(literal) * 0.5, 4)
    else:
        lo = round(literal * 0.5, 5)
        hi = round(literal * 1.5 + 0.01, 5)
    if hi <= lo:
        hi = lo + abs(lo) * 0.5 + 0.01
    return ParamSpace(kind="float", lo=lo, hi=hi)


def _lookback_space(length: int) -> ParamSpace:
    lo = max(2, int(length * 0.5))
    hi = max(lo + 1, int(length * 1.5))
    return ParamSpace(kind="int", lo=float(lo), hi=float(hi), step=1)


def _map_function(fn: str) -> str | None:
    return PINE_FEATURE_MAP.get(fn.lower())


def translate_pine(source: str) -> PineTranslation:
    src = _strip_comments(source)
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    known = feature_names()
    notes: list[str] = []
    conditions_log: list[str] = []
    indicators: list[str] = []
    lifted: dict[str, float] = {}

    param_space: dict[str, ParamSpace] = {}
    entry: list[Condition] = []

    # 1) Resolve variable → (feature, lookback-param) from `var = ta.fn(src, LEN)` assignments.
    var_feature: dict[str, tuple[str, ParamRef | int | None]] = {}
    assign_re = re.compile(rf"(\w+)\s*=\s*ta\.(\w+)\s*\(([^)]*)\)")
    for m in assign_re.finditer(src):
        var, fn, args = m.group(1), m.group(2), m.group(3)
        feature = _map_function(fn)
        if feature is None:
            continue
        indicators.append(f"{var}=ta.{fn}")
        lookback: ParamRef | int | None = None
        nums = re.findall(_NUM, args)
        if nums:
            length = int(float(nums[-1]))
            pname = _unique(f"len_{var}", param_space)
            param_space[pname] = _lookback_space(length)
            lifted[pname] = float(length)
            lookback = ParamRef(param=pname)
        var_feature[var] = (feature, lookback)

    # 2) Comparison conditions: `<lhs> <op> <rhs>` where one side is a feature, the other a literal.
    cmp_re = re.compile(r"([\w.]+(?:\([^)]*\))?)\s*(>=|<=|>|<)\s*([\w.]+(?:\([^)]*\))?)")
    op_map = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
    for m in cmp_re.finditer(src):
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        cond = _comparison_to_condition(lhs, op_map[op], rhs, var_feature, known, param_space, lifted)
        if cond is not None:
            entry.append(cond)
            conditions_log.append(f"{lhs} {op} {rhs}")

    # 3) Crossover / crossunder.
    cross_re = re.compile(r"ta\.(crossover|crossunder)\s*\(([^,]+),([^)]+)\)")
    for m in cross_re.finditer(src):
        direction, a, b = m.group(1), m.group(2).strip(), m.group(3).strip()
        op = "cross_up" if direction == "crossover" else "cross_down"
        feature = _resolve_feature(a, var_feature, known) or _resolve_feature(b, var_feature, known)
        if feature is None:
            feature = "ret_Nd"  # MA-vs-MA cross → relative momentum crossing
            notes.append(f"{direction}({a},{b}) mapped to ret_Nd momentum cross")
        nums = re.findall(_NUM, f"{a} {b}")
        literal = float(nums[0]) if nums else 0.0
        pname = _unique(f"x_{feature}", param_space)
        param_space[pname] = _threshold_space(feature, literal if literal else (50.0 if feature in BOUNDED_0_100 else 0.0))
        lifted[pname] = literal
        entry.append(Condition(feature=FeatureRef(name=feature, lookback=_lookback_for(feature, var_feature)), op=op, threshold=ParamRef(param=pname)))
        conditions_log.append(f"ta.{direction}({a}, {b})")

    # 4) Exit: stop / take from strategy.exit(...) percentages, else fitted defaults.
    exit_rules = _parse_exit(src, param_space, lifted, notes)

    # 5) Fallbacks so the spec is always valid and never empty.
    if not entry:
        notes.append("no parseable entry conditions found — seeded a momentum entry; review mapping")
        pname = _unique("entry_ret", param_space)
        param_space[pname] = ParamSpace(kind="float", lo=0.005, hi=0.08)
        entry.append(Condition(feature=FeatureRef(name="ret_Nd"), op="gt", threshold=ParamRef(param=pname)))

    # dedupe entry by (feature, op) keeping first, cap confluence at 4
    entry = _dedupe_entry(entry)[:4]

    horizon = _infer_horizon(src)
    universe = _infer_universe(src)

    spec = StrategySpec(
        name=_infer_name(src),
        rationale="Imported from a TradingView Pine strategy; hardcoded thresholds lifted into a fitted param_space for honest out-of-sample search.",
        universe=universe,
        horizon=horizon,
        entry=entry,
        exit=exit_rules,
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.04, conviction=0.5),
        param_space=param_space,
    )

    issues = validate_spec(spec)
    if issues:
        notes.append(f"auto-repaired spec issues: {issues}")
        spec = _repair(spec, issues)

    return PineTranslation(
        spec=spec,
        source_hash=source_hash,
        indicators=sorted(set(indicators)),
        conditions=conditions_log,
        notes=notes,
        lifted_params=lifted,
    )


def _comparison_to_condition(lhs, op, rhs, var_feature, known, param_space, lifted) -> Condition | None:
    left_feat = _resolve_feature(lhs, var_feature, known)
    right_num = _as_number(rhs)
    if left_feat and right_num is not None:
        feature, literal = left_feat, right_num
    else:
        right_feat = _resolve_feature(rhs, var_feature, known)
        left_num = _as_number(lhs)
        if right_feat and left_num is not None:
            feature, literal = right_feat, left_num
            op = {"gt": "lt", "lt": "gt", "gte": "lte", "lte": "gte"}[op]
        else:
            return None
    pname = _unique(f"th_{feature}", param_space)
    param_space[pname] = _threshold_space(feature, literal)
    lifted[pname] = literal
    return Condition(feature=FeatureRef(name=feature, lookback=_lookback_for(feature, var_feature)), op=op, threshold=ParamRef(param=pname))


def _resolve_feature(token: str, var_feature, known) -> str | None:
    token = token.strip()
    if token in var_feature:
        return var_feature[token][0]
    inline = re.match(r"ta\.(\w+)", token)
    if inline:
        return _map_function(inline.group(1))
    if token in known:
        return token
    return None


def _lookback_for(feature: str, var_feature) -> ParamRef | int | None:
    for feat, lb in var_feature.values():
        if feat == feature:
            return lb
    return None


def _as_number(token: str) -> float | None:
    token = token.strip()
    return float(token) if re.fullmatch(_NUM, token) else None


def _parse_exit(src: str, param_space: dict[str, ParamSpace], lifted: dict[str, float], notes: list[str]) -> ExitRules:
    stop_param = _unique("stop", param_space)
    take_param = _unique("take", param_space)
    stop_lit = _first(re.findall(rf"stop(?:Loss)?\s*=\s*({_NUM})", src, re.IGNORECASE))
    take_lit = _first(re.findall(rf"(?:limit|profit|take(?:Profit)?)\s*=\s*({_NUM})", src, re.IGNORECASE))
    param_space[stop_param] = _pct_space(stop_lit, 0.02, 0.12)
    param_space[take_param] = _pct_space(take_lit, 0.04, 0.24)
    if stop_lit is not None:
        lifted[stop_param] = float(stop_lit)
    if take_lit is not None:
        lifted[take_param] = float(take_lit)
    time_param = _unique("time_stop", param_space)
    param_space[time_param] = ParamSpace(kind="int", lo=3, hi=21, step=1)
    return ExitRules(stop_loss=ParamRef(param=stop_param), take_profit=ParamRef(param=take_param), time_stop_days=ParamRef(param=time_param))


def _pct_space(literal: str | None, lo: float, hi: float) -> ParamSpace:
    if literal is None:
        return ParamSpace(kind="float", lo=lo, hi=hi)
    val = float(literal)
    if val > 1:  # e.g. percent expressed as 5 → 0.05
        val = val / 100.0
    return ParamSpace(kind="float", lo=round(max(0.005, val * 0.5), 5), hi=round(val * 1.6 + 0.005, 5))


def _infer_horizon(src: str) -> Horizon:
    tf = re.search(r"timeframe\s*=\s*[\"'](\w+)[\"']", src)
    bar = "4h"
    if tf:
        raw = tf.group(1).lower()
        if raw in {"1h", "60"}:
            bar = "1h"
        elif raw in {"1d", "d", "1440"}:
            bar = "1d"
    return Horizon(bar_size=bar, min_hold_days=2, max_hold_days=14)


def _infer_universe(src: str) -> UniverseSelector:
    lowered = src.lower()
    classes = []
    if any(k in lowered for k in ("usdt", "btc", "eth", "crypto", "binance")):
        classes.append("crypto")
    if any(k in lowered for k in ("spy", "nasdaq", "equity", "stock", "syminfo")):
        classes.append("equity")
    if not classes:
        classes = ["crypto", "equity"]
    venue_map = {"crypto": "binance", "equity": "ibkr"}
    return UniverseSelector(
        venues=sorted({venue_map[c] for c in classes}),
        asset_classes=classes,
        min_liquidity_usd=5_000_000,
        min_instruments=5,
    )


def _infer_name(src: str) -> str:
    m = re.search(r"(?:strategy|indicator)\s*\(\s*[\"']([^\"']+)[\"']", src)
    base = m.group(1).strip() if m else "Imported Pine strategy"
    return f"{base} (pine)"[:80]


def _dedupe_entry(entry: list[Condition]) -> list[Condition]:
    seen: set[tuple[str, str]] = set()
    out: list[Condition] = []
    for cond in entry:
        key = (cond.feature.name, cond.op)
        if key not in seen:
            seen.add(key)
            out.append(cond)
    return out


def _repair(spec: StrategySpec, issues: list[str]) -> StrategySpec:
    known = feature_names()
    repaired = spec.model_copy(deep=True)
    repaired.entry = [c for c in repaired.entry if c.feature.name in known and c.threshold.param in repaired.param_space]
    if not repaired.entry:
        repaired.param_space["entry_ret"] = ParamSpace(kind="float", lo=0.005, hi=0.08)
        repaired.entry = [Condition(feature=FeatureRef(name="ret_Nd"), op="gt", threshold=ParamRef(param="entry_ret"))]
    if repaired.universe.min_instruments < 5:
        repaired.universe.min_instruments = 5
    return repaired


def _unique(base: str, space: dict) -> str:
    name, i = base, 1
    while name in space:
        i += 1
        name = f"{base}_{i}"
    return name


def _first(items: list[str]) -> str | None:
    return items[0] if items else None
