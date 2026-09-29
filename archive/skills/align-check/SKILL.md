---
name: align-check
description: Strategic alignment review — measure recent work against the north star (autonomous profit, net of fees) and flag drift into tooling/polish. Use periodically to check the project is still pointed at making money.
---

# align-check

Step back and ask: are we building a money machine, or building a tool? Read-only — this produces a judgment, not a change.

## Steps
1. **Read `docs/VISION.md`** — the north star (autonomous profit, net of every fee).
2. **Review recent work:** `git log --oneline -20`.
3. **Drift check:** is the work building toward autonomous money-making, or drifting into tooling/polish for its own sake?
4. **ML pipeline health:** is the survival model training — and on **real** forward outcomes, not synthetic fixtures?
5. **Data coverage:** how many of the registry features are actually ingested and fresh (vs declared but empty)?
6. **Strategy funnel:** authored → screened → gate-passed → funded → live. Where's the bottleneck?
7. **Report:** an alignment gut-check, the **top 3 things to focus on**, and what to **stop doing**.

## Verify
- Report cites the funnel stage that is the current bottleneck.
- Output names ≤3 focus items and at least one thing to stop.
