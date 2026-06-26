# Top of Queue — 2026-06-06 session (archived snapshot)

> **Archived from `BACKLOG.md` on 2026-06-26** (backlog status-first restructure, per
> `docs/reports/backlog-structure-audit-2026-06-26.md`). This was the oldest dated session-block in the
> backlog and self-contradicted the "Now" bucket (it claimed to *supersede* it while sitting below it).
> Relocated here verbatim for provenance. **Still-open items from this block were carried forward** into
> the live `BACKLOG.md` buckets (Now/Next/Later/Operator-Actions) during the restructure — nothing was
> dropped. The `[x]` items below are shipped and recorded here for history only.

---

## ⭐ TOP OF QUEUE — 2026-06-06 session (SUPERSEDES the stale "Now" above; detail in docs/HANDOFF_NEXT.md + docs/reports/)
> Big reframe this session: the "0 edges" verdict was untrustworthy — the harness was broken. P0 now FIXED (#123/#126).
- [x] **Bar backbone** — `BinanceVisionBarBackfiller` shipped (#129, 2026-06-06). Run it locally to fill the cache.
- [x] **Honesty fixes** — all 4 shipped (#132, 2026-06-06): exchange_netflow disabled, funding annualization fixed, FRED ALFRED vintage, registry⊆routable guard.
- [ ] **Re-run the crypto cohort** on the trustworthy harness — btc-social risk-on OVERLAY first + Polymarket family on
      historical odds (data-only); one BH-FDR family → honest edge verdict. (local)
- [x] **MCP layer** — Supabase + Postgres + engine read-only MCPs shipped (#128, 2026-06-06).
- [ ] **P2 integrity** — route/disable the 5 enabled-but-unrouted registry features; harden `ingest/ml_panel.py`. (engine, sonnet)
- [ ] **Ingest off leaky gate** — remove / quarantine the leaky cross-asset ingest paths (`evaluate_cross_asset_ablation` seam + its `StoreBackedAltProvider`) from the live cron so only PIT-honest features feed Gate runs. (engine, sonnet)
- [ ] **scan-signals reads the registry** — wire `/scan-signals` to iterate the feature registry so every enabled, routable feature gets a hypothesis generated and submitted to the Gate. Today it works off a fixed brief list. (engine+config, sonnet)
- [ ] **Run new-source ingest** — after the 10 sources shipped in #155, trigger a real `python3 -m cosmu.ingest.run` pass against Supabase to populate the new features end-to-end (needs live Railway env or Modal). (local/Railway, operator)
- [ ] **Hot/cold data tiering** — archive full history to parquet on Cloudflare R2 (DuckDB reads), keep hot in PG; build when
      the 8 GB Supabase Pro cap nears (~6 GB now) → infra <$100/mo at scale. (engine+infra) — see docs/reports/scaling-economics.md
- [x] **Data-viz overlay charts** — shipped in frontend overhaul (#155, 2026-06-07).
- [x] **"cohort" UI tooltip** — shipped (#155, 2026-06-07).
- [ ] **Branch graveyard cleanup** — prune stale worktrees/branches WHEN no agents active. (git)
- [ ] **$15 LunarCrush BUILDER mega-grab** (when wanted): upgrade Builder 1 day (100 req/min) → `scripts/lunarcrush_max_extract.py
      --coins 4000 --stocks 2000 --topics 800 --categories 300 --sleep 0.7` (gated-skip + batched writes already in) → store → CANCEL.
- [ ] **Lane A2 buys** (AFTER the Gate is proven): LlamaParse filings (`.claude/tasks/lane-a-filings-llamaparse.md`),
      Firecrawl/GDELT/Quiver, Cohere Rerank, Renovate + CodeRabbit. See docs/reports/generalization-plan-2026-06-06.md.
- [x] **Decided 2026-06-06:** keep GitHub-hosted CI (PR-only, lean) — NOT self-hosted/Codespaces; NO VPS; Polymarket =
      backtest-only (live parked, US blocked); Supabase Pro (8 GB) is the data home until tiering.
