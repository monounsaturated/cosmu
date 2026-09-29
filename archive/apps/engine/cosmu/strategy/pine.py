# intent: translate a TradingView Pine Script strategy/indicator into a typed StrategySpec so mined OSS strategies enter the same deterministic farm; inputs: pine source text; outputs: PineTranslation(spec + parse report); invariants: Pine's hardcoded thresholds are lifted into a fitted param_space (never kept as magic numbers), every referenced feature maps to the registry, and the result passes static_check.

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
    "rsi": "rsi", "cci": "rsi", "mfi": "rsi", "stoch": "rsi",
    "atr": "atr",
    "adx": "adx", "dmi": "adx", "supertrend": "adx",
    "sma": "ret_Nd", "ema": "ret_Nd", "wma": "ret_Nd", "vwma": "ret_Nd",
    "hma": "ret_Nd", "vwap": "ret_Nd", "mom": "ret_Nd", "roc": "ret_Nd",
    "change": "ret_Nd", "macd": "ret_Nd",
    "stdev": "vol_realized", "variance": "vol_realized",
    "bb": "bb_z", "bbw": "bb_z", "kc": "bb_z",
}
BAND_FNS = {"stdev", "variance", "bb", "bbw", "kc"}
BOUNDED_0_100 = {"rsi", "adx"}
PRICE_TOKENS = {"close", "open", "high", "low", "hl2", "hlc3", "ohlc4", "price", "src", "source"}
FEATURE_PRIORITY = ["bb_z", "vol_realized", "rsi", "adx", "atr", "ret_Nd"]

_NUM = r"[-+]?\d*\.?\d+"
_DEFAULT_THRESHOLD = {"rsi": 50.0, "adx": 25.0, "bb_z": 1.0, "vol_realized": 0.02, "atr": 0.02, "ret_Nd": 0.0}


@dataclass
class PineTranslation:
    spec: StrategySpec
    source_hash: str
    indicators: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lifted_params: dict[str, float] = field(default_factory=dict)


def translate_pine(source: str) -> PineTranslation:
    src = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    source_hash = hashlib.sha256(source.encode()).hexdigest()
    known = feature_names()
    notes: list[str] = []
    conditions_log: list[str] = []
    indicators: list[str] = []
    lifted: dict[str, float] = {}
    param_space: dict[str, ParamSpace] = {}
    entry: list[Condition] = []

    input_vars = _parse_input_vars(src)
    var_feature, var_lookback = _parse_indicator_vars(src, input_vars, param_space, lifted, indicators)
    derived = _parse_derived_vars(src, var_feature)
    resolve = _make_resolver(var_feature, derived, known)

    if " or " in src.lower():
        notes.append("OR conditions flattened to AND confluence — review entry logic")

    # Comparisons: `<lhs> <op> <rhs>` with a feature on one side.
    op_map = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte"}
    for m in re.finditer(r"([\w.]+(?:\([^)]*\))?)\s*(>=|<=|>|<)\s*([\w.]+(?:\([^)]*\))?)", src):
        lhs, op, rhs = m.group(1), op_map[m.group(2)], m.group(3)
        cond = _comparison_condition(lhs, op, rhs, resolve, var_lookback, input_vars, param_space, lifted)
        if cond is not None:
            entry.append(cond)
            conditions_log.append(f"{lhs} {m.group(2)} {rhs}")

    # Crossovers.
    for m in re.finditer(r"ta\.(crossover|crossunder)\s*\(([^,]+),([^)]+)\)", src):
        direction, a, b = m.group(1), m.group(2).strip(), m.group(3).strip()
        op = "cross_up" if direction == "crossover" else "cross_down"
        feature = resolve(a) or resolve(b)
        if feature is None:
            feature = "ret_Nd"
            notes.append(f"crossover({a},{b}) mapped to ret_Nd momentum cross")
        literal = _numeric(a, input_vars) or _numeric(b, input_vars) or _DEFAULT_THRESHOLD.get(feature, 0.0)
        pname = _unique(f"x_{feature}", param_space)
        param_space[pname] = _threshold_space(feature, literal)
        lifted[pname] = literal
        entry.append(Condition(feature=FeatureRef(name=feature, lookback=var_lookback.get(feature)), op=op, threshold=ParamRef(param=pname)))
        conditions_log.append(f"ta.{direction}({a}, {b})")

    exit_rules = _parse_exit(src, param_space, lifted, input_vars)

    if not entry:
        notes.append("no parseable entry conditions found — seeded a momentum entry; review mapping")
        param_space["entry_ret"] = ParamSpace(kind="float", lo=0.005, hi=0.08)
        entry.append(Condition(feature=FeatureRef(name="ret_Nd"), op="gt", threshold=ParamRef(param="entry_ret")))

    entry = _dedupe_entry(entry)[:4]
    spec = StrategySpec(
        name=_infer_name(src),
        rationale="Imported from a TradingView Pine strategy; hardcoded thresholds lifted into a fitted param_space for honest out-of-sample search.",
        universe=_infer_universe(src),
        horizon=_infer_horizon(src),
        entry=entry,
        exit=exit_rules,
        risk=RiskRules(max_concurrent_positions=3, max_position_pct=0.04, conviction=0.5),
        param_space=param_space,
    )

    issues = validate_spec(spec)
    if issues:
        notes.append(f"auto-repaired spec issues: {issues}")
        spec = _repair(spec)

    return PineTranslation(
        spec=spec,
        source_hash=source_hash,
        indicators=sorted(set(indicators)),
        conditions=conditions_log,
        notes=notes,
        lifted_params=lifted,
    )


# ---------------------------------------------------------------- parsing helpers


def _parse_input_vars(src: str) -> dict[str, float]:
    """`len = input.int(14)` / `mult = input.float(2.0)` / `x = input(30)` → numeric constants."""
    out: dict[str, float] = {}
    for m in re.finditer(rf"(\w+)\s*=\s*input(?:\.\w+)?\s*\(\s*({_NUM})", src):
        out[m.group(1)] = float(m.group(2))
    return out


def _parse_indicator_vars(src, input_vars, param_space, lifted, indicators):
    """Map variables assigned from ta.* (incl. tuple destructuring) to features + lifted lookbacks."""
    var_feature: dict[str, str] = {}
    var_lookback: dict[str, ParamRef | int | None] = {}
    pattern = re.compile(r"(?:\[([^\]]+)\]|(\w+))\s*=\s*ta\.(\w+)\s*\(([^)]*)\)")
    for m in pattern.finditer(src):
        targets = [t.strip() for t in (m.group(1) or m.group(2)).split(",") if t.strip() and t.strip() != "_"]
        fn, args = m.group(3), m.group(4)
        feature = PINE_FEATURE_MAP.get(fn.lower())
        if feature is None:
            continue
        lookback: ParamRef | int | None = None
        length = _last_length(args, input_vars)
        if length is not None:
            primary = targets[0] if targets else fn
            pname = _unique(f"len_{primary}", param_space)
            param_space[pname] = _lookback_space(int(length))
            lifted[pname] = float(int(length))
            lookback = ParamRef(param=pname)
        for t in targets:
            var_feature[t] = feature
            indicators.append(f"{t}=ta.{fn}")
            if feature not in var_lookback:
                var_lookback[feature] = lookback
    return var_feature, var_lookback


def _parse_derived_vars(src: str, var_feature: dict[str, str]) -> dict[str, str]:
    """Resolve `upper = basis + dev` style vars to a feature by scanning their expression."""
    derived: dict[str, str] = {}
    assigns = re.findall(r"(\w+)\s*=\s*([^\n=][^\n]*)", src)
    for _ in range(3):  # propagate through chains
        for name, expr in assigns:
            if name in var_feature or name in derived or "input" in expr or "ta.crossover" in expr or "ta.crossunder" in expr:
                continue
            feat = _expr_feature(expr, var_feature, derived)
            if feat:
                derived[name] = feat
    return derived


def _expr_feature(expr: str, var_feature, derived) -> str | None:
    found: set[str] = set()
    if any(re.search(rf"\b{fn}\b", expr) for fn in BAND_FNS) or "ta.bb" in expr:
        found.add("bb_z")
    for m in re.finditer(r"ta\.(\w+)", expr):
        f = PINE_FEATURE_MAP.get(m.group(1).lower())
        if f:
            found.add(f)
    for tok in re.findall(r"\b\w+\b", expr):
        if tok in var_feature:
            found.add(var_feature[tok])
        elif tok in derived:
            found.add(derived[tok])
    for pref in FEATURE_PRIORITY:
        if pref in found:
            return pref
    return None


def _make_resolver(var_feature, derived, known):
    def resolve(token: str) -> str | None:
        token = token.strip()
        if token in PRICE_TOKENS:
            return None
        if token in var_feature:
            return var_feature[token]
        if token in derived:
            return derived[token]
        inline = re.match(r"ta\.(\w+)", token)
        if inline:
            return PINE_FEATURE_MAP.get(inline.group(1).lower())
        if token in known:
            return token
        return None

    return resolve


def _comparison_condition(lhs, op, rhs, resolve, var_lookback, input_vars, param_space, lifted) -> Condition | None:
    left_feat, right_feat = resolve(lhs), resolve(rhs)
    left_num, right_num = _numeric(lhs, input_vars), _numeric(rhs, input_vars)
    if left_feat and (right_num is not None or right_feat is None):
        feature, literal = left_feat, right_num
    elif right_feat and left_num is not None:
        feature, literal, op = right_feat, left_num, {"gt": "lt", "lt": "gt", "gte": "lte", "lte": "gte"}[op]
    elif right_feat and _is_price(lhs):
        feature, literal = right_feat, None
    else:
        return None
    if literal is None:
        literal = _DEFAULT_THRESHOLD.get(feature, 0.0)
    pname = _unique(f"th_{feature}", param_space)
    param_space[pname] = _threshold_space(feature, literal)
    lifted[pname] = literal
    return Condition(feature=FeatureRef(name=feature, lookback=var_lookback.get(feature)), op=op, threshold=ParamRef(param=pname))


def _parse_exit(src, param_space, lifted, input_vars) -> ExitRules:
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


# ---------------------------------------------------------------- small utilities


def _last_length(args: str, input_vars: dict[str, float]) -> float | None:
    parts = [p.strip() for p in args.split(",")]
    for token in reversed(parts):
        if re.fullmatch(_NUM, token):
            return float(token)
        if token in input_vars:
            return input_vars[token]
    return None


def _numeric(token: str, input_vars: dict[str, float]) -> float | None:
    token = token.strip()
    if re.fullmatch(_NUM, token):
        return float(token)
    return input_vars.get(token)


def _is_price(token: str) -> bool:
    return token.strip() in PRICE_TOKENS


def _threshold_space(feature: str, literal: float) -> ParamSpace:
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


def _pct_space(literal: str | None, lo: float, hi: float) -> ParamSpace:
    if literal is None:
        return ParamSpace(kind="float", lo=lo, hi=hi)
    val = float(literal)
    if val > 1:
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
    return UniverseSelector(venues=sorted({venue_map[c] for c in classes}), asset_classes=classes, min_liquidity_usd=5_000_000, min_instruments=5)


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


def _repair(spec: StrategySpec) -> StrategySpec:
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
