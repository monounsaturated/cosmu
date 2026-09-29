# intent: compile StrategySpec into deterministic trusted strategy code; inputs: StrategySpec and fit params; outputs: code artifact and hash; invariants: no LLM/network/clock at runtime and same input yields same hash.

from __future__ import annotations

import hashlib
import json
from pydantic import BaseModel

from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec


class CompiledStrategy(BaseModel):
    code: str
    code_hash: str


def compile_spec(spec: StrategySpec, params: dict[str, float]) -> CompiledStrategy:
    issues = validate_spec(spec)
    if issues:
        raise ValueError(f"invalid strategy spec: {issues}")
    missing = set(spec.param_space) - set(params)
    if missing:
        raise ValueError(f"missing fitted params: {sorted(missing)}")
    payload = {"spec": spec.model_dump(mode="json"), "params": params}
    code = "COSMU_STRATEGY_V1 = " + json.dumps(payload, sort_keys=True)
    return CompiledStrategy(code=code, code_hash=hashlib.sha256(code.encode()).hexdigest())

