# intent: the OBSERVE-ONLY LLM-strategy run — one pass, the tick-cron entry point. Reasons every kind='llm'
# strategy (the Mind panel; LLM-judged when an OpenRouter key is set — cheap/free tier per AGENTS.md — heuristic
# offline) and RECORDS the decision traces. ZERO capital by construction (agent_executor opens no
# track/position/order). Honors AUTONOMY_CRON_ENABLED exactly like the discovery tick. See
# docs/epics/agentic-lane.md.  NOTE: the per-strategy LLM-spend cap (P0.5) is not wired yet — volume is low
# (one global Mind context per run), but cap it before scaling the agent fleet.
from __future__ import annotations

import os

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.mind.judge import judge_from_settings
from cosmu.strategy.agent_executor import run_agent_strategies


def main(argv: list[str] | None = None) -> int:
    enabled = os.environ.get("AUTONOMY_CRON_ENABLED", "1").strip().lower()
    if enabled in ("0", "false", "no"):
        print("AUTONOMY_CRON_ENABLED=0 — LLM observe-run skipped")
        return 0
    settings = Settings()
    store = Store(settings)
    judge = judge_from_settings(settings)  # cheap OpenRouter when a key is set; None = heuristic/offline
    summary = run_agent_strategies(store, judge=judge)
    print(
        f"LLM OBSERVE-RUN (sim-only, $0) — strategies={summary['strategies']} "
        f"would-trade-decisions={summary['decisions']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
