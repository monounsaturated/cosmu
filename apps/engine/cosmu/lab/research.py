# intent: the autonomous RESEARCH BRAIN pass — LLM PROPOSES, deterministic DISPOSES. It (1) gathers
# context via the propose-only lab tool bus (web_search / news_read / social / pine_fetch / rag_read), (2)
# authors N candidate StrategySpecs via lab/author (LLM-OPTIONAL — offline it uses the deterministic template
# matcher), each referencing NAMED features incl. the new OSINT source, (3) compiles + static-checks them,
# and (4) runs them through the DETERMINISTIC evolution screen / gate (FarmLoop → out-of-reach scorer), then
# records survivors + graveyard WITH reasons. Invariants: the scorer/gate stay out of every LLM path and
# decide what survives; the whole pass runs fully offline (no key, no network, no live DB) and is
# reproducible for a fixed seed; BOUNDED (one pass per call, --n N), not a daemon; secrets stay server-side.

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.config.settings import Settings
from cosmu.data.market import Bar, MarketDataProvider
from cosmu.evolution.loop import CohortSummary, Evaluated, FarmLoop, fit_params
from cosmu.knowledge.store import Store
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.lab.tools.registry import ToolBus
from cosmu.lab.tools.research_tools import research_tool_bus
from cosmu.research.fixtures import edge_bearing_screen_market
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.static_check import validate_spec

# The HAND-WRITTEN candidate briefs the research brain proposes. Each pairs a plain-language thesis with the
# NAMED features it should reference (validated to the asset class downstream). The OSINT air-activity source
# appears here so it can earn — or fail to earn — its place via the deterministic gate. This list is the
# LLM-OPTIONAL seam: with a key, the model rewrites/extends these; offline they are the deterministic corpus.
_BRIEFS: tuple[tuple[str, list[str]], ...] = (
    ("Fade oversold RSI on crypto when the band z-score is washed out, swing horizon", ["rsi", "bb_z"]),
    ("Trend-confirmed momentum on crypto with ADX confirmation", ["ret_Nd", "adx"]),
    ("Funding-pressure carry: fade crowded perp leverage on crypto", ["funding_rate"]),
    ("Volatility breakout on crypto gated by realized vol", ["ret_Nd", "vol_realized"]),
    ("Buy fear on crypto when the crowd is washed out (fear & greed)", ["fear_greed"]),
    ("OSINT macro proxy: condition crypto entries on aircraft activity (low-confidence, must earn its place)", ["ret_Nd", "osint_air_activity"]),
)


def _registry_briefs() -> tuple[tuple[str, list[str]], ...]:
    """One falsifiable brief per enabled REGISTRY alt feature the hand-written corpus doesn't already cover —
    so the brain's hypothesis space is the data layer's whole enabled surface, not 6 frozen ideas (the audit's
    novelty-starvation finding: `_BRIEFS[i % 6]` re-proposed the same six theses forever). Two structural
    angles per feature (level condition + confirmation overlay) give the screen distinct shapes to judge.
    Deterministic (sorted registry read at call time); a newly registered+ingested feature is proposed
    automatically on the next tick; volume can't manufacture a winner — every extra brief is one more trial
    the SAME deflation/BH-FDR brake must absorb."""
    from cosmu.config.feature_registry import feature_names
    from cosmu.data.backtest import PRICE_FEATURES

    covered = {f for _, feats in _BRIEFS for f in feats}
    out: list[tuple[str, list[str]]] = []
    for name in sorted(feature_names() - PRICE_FEATURES - covered):
        plain = name.replace("_", " ")
        out.append((f"Condition crypto entries on {plain} extremes (registry-derived; must earn its place)", [name]))
        out.append((f"Momentum on crypto confirmed by {plain} (registry-derived overlay; must earn its place)", ["ret_Nd", name]))
    return tuple(out)


def _brief_offset(store: Store | None) -> int:
    """The rotation cursor for the brief corpus: the number of autonomy ticks started so far. Each tick's
    window therefore ADVANCES through the corpus instead of re-proposing briefs 0..n-1 forever. Deterministic
    for a fixed store state; no store (bare CLI) → 0 (the hand-written corpus leads, exactly as before)."""
    if store is None:
        return 0
    try:
        row = store.row("SELECT COUNT(*) AS n FROM events WHERE kind = 'autonomy_tick_started'")
        return int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — a store without the events table authors from the corpus head
        return 0


@dataclass
class CandidateRecord:
    brief: str
    name: str
    base_template: str
    features: list[str]
    data_sources: list[str]
    valid: bool
    compiled: bool
    issues: list[str] = field(default_factory=list)
    code_hash: str | None = None


@dataclass
class ResearchReport:
    n_requested: int
    context_tools: list[str]
    context_samples: dict[str, object]
    authored: list[CandidateRecord]
    cohort: CohortSummary
    llm_enabled: bool
    seed: int

    @property
    def survivors(self) -> list[Evaluated]:
        return self.cohort.survivors

    @property
    def graveyard(self) -> list[Evaluated]:
        return self.cohort.graveyard

    @property
    def survival_ranking(self) -> list[Evaluated]:
        """The gate-survivors in validation-queue order (survival-score descending) — the model's only job:
        prioritize scarce full-validation compute. Already ordered by FarmLoop; surfaced here for the API."""
        return self.cohort.survivors


class _EdgeBearingBars:
    """Deterministic offline bars that CARRY a real momentum edge, so at least one authored crypto candidate
    clears the deterministic gate (exercises the survivor track-open path end-to-end). Reuses the shared
    edge_bearing_screen_market fixture; the screen/scorer still judge honestly (no injected returns)."""

    def __init__(self, *, seed: int = 3) -> None:
        self._by_symbol = edge_bearing_screen_market(seed=seed)
        self._default = next(iter(self._by_symbol.values()))

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._by_symbol.get(symbol, self._default)[-limit:]


def _web_query_from_symbol(symbol: str, brief: str | None = None) -> str:
    """Derive a meaningful Tavily/web search query from the symbol and optional brief.
    Avoids the hardcoded "crypto swing strategy edge" that covered the same ground every tick."""
    coin = symbol[:-4].upper() if symbol.upper().endswith("USDT") else symbol.upper()
    if brief:
        # Condense the brief to its first 80 chars as the topic anchor.
        topic = brief[:80].rstrip()
        return f"{coin} trading edge {topic}"
    return f"{coin} crypto trading strategy signal 2024 2025"


def gather_context(
    bus: ToolBus,
    *,
    symbol: str = "BTCUSDT",
    offline: bool = True,
    store: "Store | None" = None,
    brief: str | None = None,
) -> dict[str, object]:
    """Read context off the propose-only tool bus before authoring. Pure context — NO execution, NO scoring.
    Returns a small machine-readable digest the author/LLM would condition on.

    Enhancements over the original:
    - web_search query is derived from brief/symbol (not hardcoded "crypto swing strategy edge").
    - tweets: the already-ingested twitter_sentiment is read PIT-honestly from the store ($0, no live call).
    - xai_live: the xAI live_search tool is called (key-gated; degrades offline to fixture) for current
      X/web market intelligence; this is the live-search complement to the static web_search.
    """
    web_query = _web_query_from_symbol(symbol, brief)
    ctx: dict[str, object] = {
        "tools": [t["name"] for t in bus.list_tools()],
        "web_search": bus.call("web_search", {"query": web_query}),
        "news_read": bus.call("news_read", {"symbol": symbol, "limit": 4, "offline": offline}),
        "social": bus.call("social", {"symbol": symbol}),
        "rag_read": bus.call("rag_read", {"query": "prior art"}),
        "pine_fetch": bus.call("pine_fetch", {}),
        "xai_live": bus.call("xai_live", {"query": web_query}) if "xai_live" in {t["name"] for t in bus.list_tools()} else {"ok": False, "source": "offline", "results": []},
    }

    # Read already-ingested twitter_sentiment from the store (PIT-honest, $0 per research pass —
    # no live LLM call here; ingest/run.py writes this data from XaiTwitterProvider).
    ctx["tweets"] = _read_store_tweets(store, symbol=symbol)
    return ctx


def _read_store_tweets(store: "Store | None", *, symbol: str = "BTCUSDT") -> dict[str, object]:
    """Read the latest twitter_sentiment points from the ingested alt_data store (PIT-honest, $0).
    Returns a small digest: {"ok": bool, "source": "store"|"none", "points": [{"value": float, "ts": str}]}.
    Fails silently (returns {"ok": False, ...}) so a missing store or empty series never aborts the pass."""
    if store is None:
        return {"ok": False, "source": "none", "points": []}
    try:
        from datetime import UTC, datetime
        from cosmu.data.providers.store import PgAltDataStore

        alt_store = PgAltDataStore(store)
        pts = alt_store.read_asof("xai", "MARKET", "twitter_sentiment", datetime.now(tz=UTC))
        if not pts:
            return {"ok": True, "source": "store", "points": []}
        # Return the last 5 points (most recent; read_asof orders oldest→newest)
        recent = pts[-5:]
        return {
            "ok": True,
            "source": "store",
            "points": [{"value": float(p.value), "ts": p.ts.isoformat()} for p in recent],
        }
    except Exception:  # noqa: BLE001 — missing store/table is normal offline; never aborts the pass
        return {"ok": False, "source": "none", "points": []}


def _prior_art_from_context(context: dict[str, object]) -> tuple[list[str], list[str]]:
    """Distill the propose-only research bus digest into (prior_art_features, citations) the author can condition
    on. Features come from rag_read prior-art matches; citations are short source titles for the audit trail.
    Also folds in twitter_sentiment signal from ingested store and xai_live results.
    Read-only and deterministic — the offline fixtures yield the same digest in CI."""
    feats: list[str] = []
    cites: list[str] = []
    rag = context.get("rag_read") if isinstance(context.get("rag_read"), dict) else {}
    for m in (rag or {}).get("matches", []):  # type: ignore[union-attr]
        f = m.get("feature")
        if f and f not in feats:
            feats.append(f)
        title = m.get("title")
        if title:
            cites.append(f"prior-art: {title}")
    web = context.get("web_search") if isinstance(context.get("web_search"), dict) else {}
    for r in ((web or {}).get("results", []) or [])[:2]:  # type: ignore[union-attr]
        title = r.get("title")
        if title:
            cites.append(f"web: {title}")
    # Fold in xAI live-search results (real-time X/web intelligence, key-gated).
    xai = context.get("xai_live") if isinstance(context.get("xai_live"), dict) else {}
    for r in ((xai or {}).get("results", []) or [])[:2]:  # type: ignore[union-attr]
        title = r.get("title")
        if title:
            cites.append(f"xai-live: {title}")
    # Fold twitter_sentiment signal: if the store returned points, note the feature as available context so
    # the author is aware crowd sentiment data is ingested. The numeric value conditions the brief's direction
    # (bullish/bearish tilt); a missing or empty store is a no-op (never fabricates).
    tweets = context.get("tweets") if isinstance(context.get("tweets"), dict) else {}
    tweet_pts = (tweets or {}).get("points", [])  # type: ignore[union-attr]
    if tweet_pts:
        if "twitter_sentiment" not in feats:
            feats.append("twitter_sentiment")
        # Summarize direction for the citation trail.
        try:
            last_val = float(tweet_pts[-1]["value"])
            direction = "bullish" if last_val > 0.1 else ("bearish" if last_val < -0.1 else "neutral")
        except (KeyError, IndexError, TypeError, ValueError):
            direction = "unknown"
        cites.append(f"store-tweets: twitter_sentiment latest={direction} (n={len(tweet_pts)} pts)")
    return feats, cites


def author_candidates(
    n: int,
    *,
    llm_enabled: bool = False,
    store: Store | None = None,
    chat=None,  # noqa: ANN001
    prior_art: list[str] | None = None,
    research_citations: list[str] | None = None,
) -> list[tuple[AuthorDraft, CandidateRecord]]:
    """Author N candidate specs via lab/author (LLM-OPTIONAL), compile + static-check each. The author only
    produces STRUCTURE (thresholds stay in param_space); the gate, not this path, decides what survives. When a
    `store` is given the author consults LONG-TERM MEMORY (graveyard RAG + distilled skills) to avoid recently
    dead structures and lean toward winners. `prior_art` are features the propose-only research bus surfaced —
    the author folds them in (validated + memory-pruned), closing the gather→author loop. Still proposal-only."""
    out: list[tuple[AuthorDraft, CandidateRecord]] = []
    # The corpus = hand-written theses + one brief per enabled registry alt feature; the window rotates by
    # the tick counter so successive ticks EXPLORE the corpus instead of re-proposing the same first n briefs.
    corpus = (*_BRIEFS, *_registry_briefs())
    offset = _brief_offset(store) * max(1, n)
    briefs = [corpus[(offset + i) % len(corpus)] for i in range(max(1, n))]
    for brief, feats in briefs:
        # When the LLM is enabled the model PROPOSES the structure from the plain-language brief (the named-feature
        # hints become a fallback, not a hard pin); offline the deterministic template matcher uses the hints.
        author_feats = None if llm_enabled else feats
        draft = draft_from_brief(
            brief, features=author_feats, llm_enabled=llm_enabled, store=store, chat=chat,
            prior_art=prior_art, research_citations=research_citations,
        )
        issues = list(draft.issues) or validate_spec(draft.spec)
        compiled_ok = False
        code_hash: str | None = None
        if not issues:
            try:
                compiled = compile_spec(draft.spec, fit_params(draft.spec))
                compiled_ok = True
                code_hash = compiled.code_hash
            except ValueError as exc:  # static_check inside compile_spec rejected it
                issues.append(str(exc))
        record = CandidateRecord(
            brief=brief,
            name=draft.spec.name,
            base_template=draft.base_template,
            features=draft.features,
            data_sources=draft.data_sources,
            valid=draft.valid and not issues,
            compiled=compiled_ok,
            issues=issues,
            code_hash=code_hash,
        )
        out.append((draft, record))
    return out


def run_research_pass(
    store: Store,
    *,
    n: int = 4,
    seed: int = 7,
    llm_enabled: bool = False,
    market_data: MarketDataProvider | None = None,
    tool_bus: ToolBus | None = None,
    edge_market: bool = False,
    persist: bool = True,
    chat=None,  # noqa: ANN001 — injectable LLM seam; None → real OpenRouter seam from settings (offline → fallback)
) -> ResearchReport:
    """ONE bounded research pass: gather context → author N specs → compile+static_check → run through the
    DETERMINISTIC evolution screen/gate (scorer out of any LLM's reach) → record survivors + graveyard. The
    authored specs enter the cohort as `extra_seeds`; FarmLoop screens + scores them exactly like seeds, so
    the deterministic wall is the sole judge. The survival model (loaded inside FarmLoop) ORDERS the survivors
    for full validation — it never vetoes. Reproducible for a fixed (n, seed) offline.

    By DEFAULT (edge_market=False, no injected market_data) the screen runs on REAL Binance spot bars — the
    only honest source. `edge_market=True` is CI/offline ONLY: it screens over the edge-bearing fixture so the
    survivor track-open path is exercised deterministically with no network. Production must never run with
    edge_market=True. `persist=True` writes a research_pass event so the API can read the run
    (authored/gated/survivors/graveyard) without re-running — not CLI-only."""
    if tool_bus is None:
        # Build the bus with server-side keys so the xAI live_search tool can run (key-gated; offline → fixture).
        try:
            from cosmu.config.settings import get_settings as _get_settings
            _s = _get_settings()
            bus = research_tool_bus(xai_key=_s.xai_api_key)
        except Exception:  # noqa: BLE001 — settings unavailable offline → no-key bus (fixtures only)
            bus = research_tool_bus()
    else:
        bus = tool_bus
    context = gather_context(bus, store=store)
    # CLOSE THE AGENTIC LOOP: distil the gathered tool-bus context into prior-art features the author conditions
    # on. Gather (read-only tools) → author (informed proposal) → the DETERMINISTIC screen/gate disposes.
    prior_art, research_citations = _prior_art_from_context(context)

    # Author with research context + long-term memory (avoid recently-dead structures, lean toward winners + skills).
    authored = author_candidates(
        n, llm_enabled=llm_enabled, store=store, chat=chat,
        prior_art=prior_art, research_citations=research_citations,
    )
    extra_seeds = [draft.spec for draft, rec in authored if rec.compiled]

    if market_data is not None:
        provider: MarketDataProvider | None = market_data
    elif edge_market:
        provider = _EdgeBearingBars()
    else:
        # PRODUCTION default: no provider → FarmLoop._screen fetches REAL Binance spot bars
        # (BinanceSpotOHLCVProvider, cache-backed). Synthetic fixtures are CI/offline only. We never
        # screen — or fund — SIM tracks on fabricated data; the app must not display synthetic edge.
        provider = None
    loop = FarmLoop(settings=store.settings, store=store, market_data=provider)
    # Cohort = the authored candidates only (no extra mutation/explore waves) so the report maps 1:1 onto
    # what the brain proposed; the deterministic screen + out-of-reach scorer decide PASS/STOP per candidate.
    cohort = loop.run_cohort(seed=seed, cohort_size=len(extra_seeds), explore_pct=0.0, extra_seeds=extra_seeds)

    report = ResearchReport(
        n_requested=n,
        context_tools=context["tools"],  # type: ignore[arg-type]
        context_samples=context,
        authored=[rec for _, rec in authored],
        cohort=cohort,
        llm_enabled=llm_enabled,
        seed=seed,
    )
    if persist:
        _persist_pass(store, report)
    return report


def _persist_pass(store: Store, report: ResearchReport) -> None:
    """Persist the research-pass result as an audit event so GET /research/brain can read the latest pass
    (authored/gated/survivors/graveyard) without re-running the cohort. The cohort already wrote the
    strategy_versions/backtests/tracks/graveyard rows; this is the one-row pass summary on top of them."""
    store.append_event(
        actor="master",
        kind="research_pass",
        ref_type="cohort",
        ref_id=report.cohort.cohort_id,
        payload={
            "llm": "on" if report.llm_enabled else "off",
            "n_requested": report.n_requested,
            "seed": report.seed,
            "generated": report.cohort.generated,
            "passed": report.cohort.passed,
            "killed": report.cohort.killed,
            "kill_rate": report.cohort.kill_rate,
            "survivors": [
                {"version_id": s.version_id, "name": s.name, "net_pct": round(s.oos_return_pct, 3), "survival_score": s.survival_score}
                for s in report.survivors
            ],
            "graveyard": [{"name": g.name, "reasons": g.reasons or ["screened_out"]} for g in report.graveyard],
            "survival_ranking": [
                {"version_id": s.version_id, "name": s.name, "score": s.survival_score, "trained": s.survival_trained}
                for s in report.survival_ranking
            ],
        },
    )


def _offline_store() -> Store:
    """A throwaway sqlite store so the CLI runs fully offline (no live DB, no keys). Real schedulers can pass
    their own Store; this keeps `python3 -m cosmu.lab.research` reproducible and side-effect-free in CI."""
    tmp = tempfile.mkdtemp(prefix="cosmu-research-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/research.sqlite3", openrouter_api_key=None))


def _print_report(report: ResearchReport) -> None:
    print(f"RESEARCH BRAIN — authored {len(report.authored)} candidate(s) (n={report.n_requested}, seed={report.seed}, llm={'on' if report.llm_enabled else 'off (deterministic)'})")
    print(f"  context tools on the bus: {', '.join(report.context_tools)}")
    print("  AUTHORED (LLM proposes — structure only, thresholds in param_space):")
    for rec in report.authored:
        flag = "ok" if rec.compiled else ("invalid" if not rec.valid else "uncompiled")
        feats = ", ".join(rec.features) or "-"
        print(f"    [{flag}] {rec.name}  · template={rec.base_template} · features={feats} · sources={','.join(rec.data_sources)}")
        if rec.issues:
            print(f"           issues: {rec.issues}")
    print(f"  GATED (deterministic disposes — scorer out of reach): generated={report.cohort.generated} passed={report.cohort.passed} killed={report.cohort.killed} kill_rate={report.cohort.kill_rate}")
    if report.survivors:
        print("  SURVIVORS (validation queue order — survival model orders, never vetoes):")
        for s in report.survivors:
            tag = "trained" if s.survival_trained else "cold-start"
            print(f"    PASS  {s.name}  · survival={s.survival_score:.3f} [{tag}] · deflated_sharpe={s.deflated_sharpe:.4f} · oos={s.oos_return_pct:+.2f}% · proven_regimes={','.join(s.proven_regimes) or '-'}")
    print("  GRAVEYARD (with reasons):")
    for g in report.graveyard:
        print(f"    STOP  {g.name}  · reasons={','.join(g.reasons) or 'screened_out'}")
    has_osint = any(f.name == "osint_air_activity" for f in FEATURE_REGISTRY)
    print(f"  OSINT source registered in feature vocabulary: {'yes (osint_air_activity)' if has_osint else 'no'}")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bounded autonomous research pass: gather context → author N specs → gate them deterministically (no keys).")
    parser.add_argument("--n", type=int, default=4, help="number of candidate strategies to author (default 4)")
    parser.add_argument("--seed", type=int, default=7, help="cohort seed for reproducibility (default 7)")
    args = parser.parse_args(argv)

    # The CLI demo runs over the edge-bearing fixture so the survivor track-open path is visible offline.
    report = run_research_pass(_offline_store(), n=max(1, args.n), seed=args.seed, edge_market=True)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
