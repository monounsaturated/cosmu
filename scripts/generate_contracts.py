from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "engine"))
os.environ.setdefault("DATABASE_URL", "sqlite:///./.cosmu/contracts.sqlite3")

try:
    from cosmu.api.app import app  # noqa: E402
except ImportError:
    app = None


def ts_type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    if "anyOf" in schema:
        return " | ".join(ts_type(part) for part in schema["anyOf"] if part.get("type") != "null") + (" | null" if any(part.get("type") == "null" for part in schema["anyOf"]) else "")
    kind = schema.get("type")
    if kind == "array":
        return f"{ts_type(schema.get('items', {}))}[]"
    if kind in {"integer", "number"}:
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "object":
        if "additionalProperties" in schema:
            return "Record<string, unknown>"
        return "Record<string, unknown>"
    if "enum" in schema:
        return " | ".join(json.dumps(item) for item in schema["enum"])
    return "string"


def main() -> None:
    openapi_path = ROOT / "packages" / "contracts-ts" / "openapi.json"
    if app is not None:
        openapi = app.openapi()
        openapi_path.parent.mkdir(parents=True, exist_ok=True)
        openapi_path.write_text(json.dumps(openapi, indent=2, sort_keys=True) + "\n")
    elif openapi_path.exists():
        openapi = json.loads(openapi_path.read_text())
    else:
        print("warning: Python deps unavailable and no cached openapi.json — skipping contract generation", file=sys.stderr)
        return
    out_dir = ROOT / "packages" / "contracts-ts" / "src"
    out_dir.mkdir(parents=True, exist_ok=True)
    schemas = openapi["components"]["schemas"]
    lines = ["// Generated from apps/engine FastAPI OpenAPI. Do not edit by hand.", ""]
    for name, schema in sorted(schemas.items()):
        if schema.get("type") != "object":
            continue
        required = set(schema.get("required", []))
        lines.append(f"export interface {name} {{")
        for prop, prop_schema in sorted(schema.get("properties", {}).items()):
            optional = "" if prop in required else "?"
            lines.append(f"  {prop}{optional}: {ts_type(prop_schema)};")
        lines.append("}")
        lines.append("")
    lines.extend(
        [
            "export type ApiRoutes = {",
            "  portfolio: PortfolioResponse;",
            "  leaderboard: LeaderboardResponse;",
            "  recommendations: RecommendationsResponse;",
            "  events: EventsResponse;",
            "  skills: SkillsResponse;",
            "  'memory/insights': MemoryInsightsResponse;",
            "  costs: CostsResponse;",
            "};",
            "",
        ]
    )
    (out_dir / "index.ts").write_text("\n".join(lines))


if __name__ == "__main__":
    main()

