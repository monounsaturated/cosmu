# intent: reject unsafe or overfit-prone strategy specs/code before execution; inputs: StrategySpec and optional Python code; outputs: validation issues; invariants: no magic entry numbers, unknown features, network/filesystem imports, eval, or exec.

from __future__ import annotations

import ast

from cosmu.config.feature_registry import feature_names
from cosmu.strategy.spec import ParamRef, StrategySpec


SAFE_IMPORTS = {"math", "statistics", "decimal", "typing"}
BLOCKED_NAMES = {"eval", "exec", "open", "__import__", "compile", "globals", "locals"}


def validate_spec(spec: StrategySpec) -> list[str]:
    issues: list[str] = []
    params = set(spec.param_space)
    features = feature_names()
    refs = [condition.threshold.param for condition in spec.entry]
    refs.extend([spec.exit.stop_loss.param, spec.exit.take_profit.param])
    if spec.exit.time_stop_days:
        refs.append(spec.exit.time_stop_days.param)
    refs.extend(condition.threshold.param for condition in spec.exit.signal_exits)
    refs.extend(_composable_param_refs(spec))
    for ref in refs:
        if ref not in params:
            issues.append(f"unknown_param:{ref}")
    for condition in [*spec.entry, *spec.exit.signal_exits]:
        if condition.feature.name not in features:
            issues.append(f"unknown_feature:{condition.feature.name}")
        if not isinstance(condition.threshold, ParamRef):
            issues.append("literal_threshold")
    # A perp funding leg must name a real PIT feature — same registry guard as entry/exit features.
    if spec.funding_feature is not None and spec.funding_feature not in features:
        issues.append(f"unknown_feature:{spec.funding_feature}")
    if spec.universe.min_instruments < 5:
        issues.append("universe_too_small")
    if spec.horizon.min_hold_days < 1 or spec.horizon.max_hold_days < spec.horizon.min_hold_days:
        issues.append("invalid_horizon")
    return issues


def _composable_param_refs(spec: StrategySpec) -> list[str]:
    """Every ParamRef introduced by the composable exit-plan / entry-setup modules, so static_check enforces
    the same 'no magic numbers' rule on them (all thresholds must resolve in param_space)."""
    refs: list[str] = []
    plan = spec.exit.plan
    if plan is not None:
        for leg in plan.multi_tp:
            refs.extend([leg.at.param, leg.size_pct.param])
        if plan.runner_trail is not None:
            refs.append(plan.runner_trail.param)
    setup = spec.setup
    if setup is not None:
        if setup.ma_trend_filter is not None:
            refs.append(setup.ma_trend_filter.ma_lookback.param)
        if setup.orb is not None:
            refs.extend([setup.orb.range_bars.param, setup.orb.buffer.param])
        if setup.fvg is not None:
            refs.extend([setup.fvg.max_retests.param, setup.fvg.gap_min.param])
    return refs


def validate_python(code: str) -> list[str]:
    issues: list[str] = []
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in SAFE_IMPORTS:
                    issues.append(f"blocked_import:{alias.name}")
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module not in SAFE_IMPORTS:
                issues.append(f"blocked_import:{node.module}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BLOCKED_NAMES:
            issues.append(f"blocked_call:{node.func.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            issues.append("dunder_attribute")
    return sorted(set(issues))

