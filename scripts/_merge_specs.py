"""Batch-validate workflow-authored specs against the REAL compiler, merge valid ones to the inbox.

Usage: python3 scripts/_merge_specs.py <workflow_output.json>
Reads result.specs (each {name, spec_json}); for each: parse JSON → StrategySpec.model_validate →
validate_spec (no magic numbers / known features). Writes ONLY valid, non-duplicate specs to
apps/engine/strategies/inbox/ and records their names to /tmp/new_spec_names.json. Reports valid/invalid.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

INBOX = Path("apps/engine/strategies/inbox")


def _slug(n: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", n.lower()).strip("-")[:60]


def main() -> None:
    out_file = sys.argv[1]
    raw = json.loads(Path(out_file).read_text())
    result = raw.get("result", raw)
    specs = result.get("specs", [])
    print(f"raw specs from workflow: {len(specs)}")

    existing = set()
    for p in INBOX.glob("*.json"):
        try:
            existing.add(json.loads(p.read_text()).get("name"))
        except Exception:
            pass

    valid_names, n_bad_json, n_bad_spec, n_dup = [], 0, 0, 0
    seen = set()
    for s in specs:
        sj = s.get("spec_json")
        if not sj:
            n_bad_json += 1
            continue
        try:
            obj = json.loads(sj) if isinstance(sj, str) else sj
        except Exception:
            n_bad_json += 1
            continue
        try:
            spec = StrategySpec.model_validate(obj)
        except Exception:
            n_bad_spec += 1
            continue
        issues = validate_spec(spec)
        if issues:
            n_bad_spec += 1
            continue
        nm = spec.name
        if nm in existing or nm in seen:
            nm = f"{nm} (v{len(seen)})"
            obj["name"] = nm
        seen.add(nm)
        (INBOX / f"campaign200-{_slug(nm)}.json").write_text(json.dumps(obj, indent=2))
        valid_names.append(nm)

    Path("/tmp/new_spec_names.json").write_text(json.dumps(valid_names))
    print(f"VALID written to inbox: {len(valid_names)} | bad_json: {n_bad_json} | bad_spec(validator): {n_bad_spec}")
    print(f"names → /tmp/new_spec_names.json")


if __name__ == "__main__":
    main()
