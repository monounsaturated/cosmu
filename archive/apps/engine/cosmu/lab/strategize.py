# intent: the ONE front-door router for strategy intake — classify a free-form operator input (a vibe, a URL, a
# pasted Pine script, "find me something on funding", "evolve the winner", or "generate N from a theme") and
# route it to the RIGHT existing path; for the offline-authorable intents it authors typed StrategySpec(s) via
# the SAME draft_from_brief / translate_pine machinery and drops them in strategies/inbox (so the deterministic
# Gate disposes); for the network/gate-heavy intents (url scrape, cross-asset scan, cohort evolve) it returns a
# route that names the sibling skill for Claude Code to drive. invariants: THIN orchestrator — it REUSES the
# skills' building blocks, never reimplements the scorer/Gate; no magic numbers (draft_from_brief / translate_pine
# guarantee thresholds stay in param_space); everything authored is tracked (an audited event per spec) and
# offline-safe (no keys/network on the authoring path).

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from cosmu.lab.author import draft_from_brief
from cosmu.strategy.spec import StrategySpec
from cosmu.strategy.static_check import validate_spec

if TYPE_CHECKING:
    from cosmu.data.market import MarketDataProvider
    from cosmu.evolution.loop import CohortSummary
    from cosmu.knowledge.store import Store

# The canonical inbox — identical resolution to cosmu.lab.inbox (parents[2] == apps/engine), so what strategize
# authors is exactly what the boot scan / autonomy tick later gates. CWD-agnostic.
_INBOX_DIR = Path(__file__).resolve().parents[2] / "strategies" / "inbox"

Intent = Literal["url", "pine", "scan", "evolve", "batch", "vibe"]

# Each intent maps to the EXISTING skill that owns that path — strategize only routes; the skill does the work.
SKILL_FOR: dict[str, str] = {
    "url": "import-pine",
    "pine": "import-pine",
    "scan": "scan-signals",
    "evolve": "evolve-strategy",
    "batch": "create-strategy",
    "vibe": "dump-idea",
}

# Intents strategize can fully author OFFLINE (deterministic, no network) — it writes the typed spec(s) to the
# inbox itself. The rest need a live page fetch / the cross-asset Gate / a FarmLoop cohort, so they are delegated
# to Claude Code driving the named skill.
_AUTHORABLE: frozenset[str] = frozenset({"vibe", "batch", "pine"})

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_PINE_RE = re.compile(r"//@version=|\bstrategy\s*\(|\bindicator\s*\(|\bta\.[a-z]", re.IGNORECASE)
_SCAN_RE = re.compile(
    r"\b(scan|sweep|discover|find me|find something|what (should we|to) try|what'?s next|propose|hunt)\b",
    re.IGNORECASE,
)
_EVOLVE_RE = re.compile(
    r"\b(evolve|compound|graft|recombine|replicate|the winner|gate-?passed survivor)\b", re.IGNORECASE
)
_BATCH_TRIGGER_RE = re.compile(
    r"\b(?:generate|give me|author|make|create|spin up|produce|build|draft)\s+(\d+|a few|several|some|a couple|a dozen)\b",
    re.IGNORECASE,
)
_N_THINGS_RE = re.compile(
    r"\b(\d+)\s+(?:strateg(?:y|ies)|specs?|vari(?:ant|ation)s?|ideas?|candidates?|hypothes[ie]s)\b",
    re.IGNORECASE,
)
_WORD_COUNTS: dict[str, int] = {"a couple": 2, "a few": 3, "some": 3, "several": 4, "a dozen": 12}
# How a theme is introduced in prose — the text AFTER one of these is the theme.
_THEME_LEAD_RE = re.compile(r"\b(?:on|about|around|from|for|using|with|themed?(?: on| around)?)\s+(.+)$", re.IGNORECASE)
# Default batch size when phrasing says "a batch / some" with no explicit number.
_DEFAULT_BATCH = 3
# Hard cap so a runaway "generate 1000" can't flood the inbox; surfaced in notes when clamped. RAISED + env-tunable
# 2026-06-25 (widest-honest universe pivot): 64→128 to author a deeper hypothesis batch per theme. Throughput only
# — every authored spec still flows through the SAME deterministic gate + BH-FDR, so more ideas never loosen the
# bar. Override with COSMU_MAX_BATCH.
def _env_max_batch(default: int = 128) -> int:
    import os

    raw = os.environ.get("COSMU_MAX_BATCH", "").strip()
    try:
        val = int(raw) if raw else default
    except ValueError:
        return default
    return val if val > 0 else default


_MAX_BATCH = _env_max_batch()


@dataclass
class AuthoredSpec:
    """One typed spec strategize wrote to the inbox (or tried to)."""

    name: str
    brief: str
    valid: bool
    issues: list[str] = field(default_factory=list)
    path: str = ""  # the inbox file written ("" if authoring failed and nothing was written)
    notes: list[str] = field(default_factory=list)


@dataclass
class StrategizeRoute:
    """The router's decision: which intent, which skill owns it, what (if anything) was authored, and whether
    Claude Code still needs to drive the named skill (the network/gate-heavy paths)."""

    intent: Intent
    skill: str
    reason: str
    delegated: bool  # True => strategize did NOT author; Claude Code must drive `skill` (url/scan/evolve)
    authored: list[AuthoredSpec] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    theme: str | None = None
    count: int = 0
    cohort: CohortSummary | None = None  # set only when gate=True ran the deterministic screen on what we authored


def classify_intent(text: str, *, n: int | None = None, theme: str | None = None) -> Intent:
    """Deterministically route a free-form input to one of the six intents. Explicit batch params (n>1 or an
    explicit theme) force `batch`; otherwise the shape of the text decides (URL → pine → scan → evolve → batch
    phrasing → vibe). Pure + offline."""
    if (n is not None and n > 1) or theme:
        return "batch"
    t = (text or "").strip()
    if _URL_RE.search(t):
        return "url"
    if _PINE_RE.search(t):
        return "pine"
    low = t.lower()
    if _SCAN_RE.search(low):
        return "scan"
    if _EVOLVE_RE.search(low):
        return "evolve"
    if _BATCH_TRIGGER_RE.search(low) or _N_THINGS_RE.search(low):
        return "batch"
    return "vibe"


def _parse_batch(text: str, *, n: int | None, theme: str | None) -> tuple[int, str]:
    """Resolve (count, theme) for a batch request from explicit args first, then the prose. The theme is the
    subject the N strategies vary around; count is clamped to [1, _MAX_BATCH]."""
    low = (text or "").lower()
    count = n
    if count is None:
        m = _BATCH_TRIGGER_RE.search(low) or _N_THINGS_RE.search(low)
        if m:
            tok = m.group(1).lower()
            count = _WORD_COUNTS.get(tok, int(tok) if tok.isdigit() else _DEFAULT_BATCH)
    if count is None:
        count = _DEFAULT_BATCH
    count = max(1, min(_MAX_BATCH, count))

    resolved_theme = (theme or "").strip()
    if not resolved_theme:
        lead = _THEME_LEAD_RE.search(text or "")
        if lead:
            resolved_theme = lead.group(1).strip()
        else:
            # strip the batch trigger + count, keep the remainder as the theme.
            stripped = _BATCH_TRIGGER_RE.sub("", text or "")
            stripped = _N_THINGS_RE.sub("", stripped)
            resolved_theme = re.sub(r"\b(strateg(?:y|ies)|specs?|ideas?|from a theme|theme)\b", "", stripped, flags=re.IGNORECASE)
            resolved_theme = resolved_theme.strip(" .,-")
    return count, (resolved_theme or "momentum")


# Deterministic angle set: turn ONE theme into N distinct, falsifiable briefs (different economic priors /
# directions / horizons / feature combinations). Expanded from 8 to 32 so that a batch of 50 cycles across
# enough structural variation to clear novelty_gate min_distance=0.25 — each angle picks a different
# bar size, operator direction (mean-reversion vs trend vs carry), and entry feature family, so two adjacent
# briefs that share a theme produce specs with clearly different feature sets.
_THEME_ANGLES: tuple[str, ...] = (
    # --- contrarian / mean-reversion family (fade, reversal) ---
    "Fade crowded {theme} — go contrarian when the {theme} signal is one-sided and extended, daily bar.",
    "{theme} washout reversion — enter after an extreme {theme} print and fade it back, using RSI to confirm oversold, 4h bar.",
    "{theme} dislocation bounce — buy after a statistical outlier {theme} event using Bollinger z-score, 1d bar.",
    "{theme} overshoot fade — short when {theme} spikes above two standard deviations, intraday 4h horizon.",
    "Contrarian {theme} with vol filter — fade the signal when realized volatility is in its calm regime, 1d bar.",
    # --- carry / persistence / regime-follow family ---
    "{theme} carry/persistence — ride the {theme} signal while it stays in the same regime, daily horizon.",
    "{theme} regime persistence — enter momentum only when {theme} confirms the macro regime is supportive, 1d bar.",
    "{theme} positive carry gate — take the trend only when {theme} carry is positive and funding is low, 4h bar.",
    "Low-{theme} carry accumulation — enter a long when {theme} drops below zero (shorts are paying longs), 1d bar.",
    "{theme} carry reversal — when {theme} carry turns negative after a positive streak, exit and reverse, swing.",
    # --- cross-asset / macro family ---
    "Cross-asset {theme} — use {theme} as a leading signal into crypto rather than same-asset price, daily.",
    "{theme} macro divergence — enter when crypto price diverges from {theme} macro signal, 1d bar.",
    "DXY-gated {theme} — only take the {theme} signal when the dollar is in a weakening trend, 1d bar.",
    "{theme} cross-venue arbitrage — measure {theme} dispersion across assets and enter the laggard, 4h bar.",
    "Risk-on {theme} — enter only when VIX confirms a low-fear environment alongside {theme} signal, 1d bar.",
    # --- trend / momentum family ---
    "ADX-confirmed {theme} trend — take the {theme} trend when ADX confirms the move is real, 1d bar.",
    "{theme} momentum confirmation on a breakout — only take the breakout the {theme} signal agrees with, 4h.",
    "Dual-horizon {theme} momentum — require both fast and slow {theme} lookbacks to align before entering, daily.",
    "{theme} breakout with volume — enter on a {theme} extreme only when volume confirms the move, 4h bar.",
    "{theme} trend with ATR sizing — ride the {theme} trend but scale entry size by realized ATR, 1d bar.",
    # --- regime filter family (the signal gates an independent entry) ---
    "{theme} as a regime filter on a trend-following entry — stand aside when {theme} says risk-off, 1d bar.",
    "{theme} stress gate — size down / skip when the {theme} signal is in its stressed tail, daily bar.",
    "{theme} calm-market gate — enter a mean-reversion trade only when {theme} is in the low-stress bucket.",
    "Volatility-regime {theme} — enter trend trades only when {theme} and vol regime both say expansion, 4h.",
    "{theme} liquidity gate — enter only when {theme} confirms on-chain/market liquidity is supportive, 1d.",
    # --- divergence / relative-value family ---
    "{theme} divergence vs price — enter when {theme} and price disagree, swing horizon, 4h bar.",
    "{theme} intra-asset divergence — enter the asset where {theme} rank is cheapest vs its own history, daily.",
    "Social vs {theme} divergence — enter when social sentiment diverges from {theme} fundamentals, 1d.",
    "{theme} open-interest divergence — trade when price and {theme} open interest disagree in direction, 4h.",
    # --- multi-leg / composite family (combines the theme with a second independent signal) ---
    "{theme} with RSI confirmation — take the {theme} entry only when RSI agrees (avoid false signals), 1d.",
    "{theme} plus funding gate — use funding rate as a secondary filter on the {theme} signal, 4h bar.",
    "{theme} composite — require {theme} AND a momentum signal before entering; exit when either flips, 1d.",
)


def _theme_briefs(theme: str, count: int) -> list[str]:
    """N distinct briefs varying a single theme across economic angles (deterministic, dedup-stable)."""
    out: list[str] = []
    for i in range(count):
        out.append(_THEME_ANGLES[i % len(_THEME_ANGLES)].format(theme=theme))
    return out


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:48] or "strategy"


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_spec(store: Store, spec: StrategySpec, *, intent: str, brief: str, directory: Path, authored_by: str = "human") -> str:
    """Write a typed, already-validated StrategySpec to the inbox as `.json` (the scanner gates it verbatim — no
    re-drafting, so the authored structure is preserved) and record an audited `strategize_authored` event for
    tracking. Returns the file path written. Content-addressed filename → re-authoring the same spec is idempotent.
    `authored_by` is the event actor (human chat vs the agent batch master) so the flywheel can grade winners by
    who wrote them — no schema change, the events table actor is free-text."""
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    chash = _content_hash(payload)
    filename = f"strat-{_slugify(spec.name)}-{chash[:8]}.json"
    path = directory / filename
    path.write_text(payload, encoding="utf-8")
    store.append_event(
        actor=authored_by,
        kind="strategize_authored",
        ref_type="strategy_spec",
        payload={
            "path": str(path),
            "filename": filename,
            "name": spec.name,
            "content_hash": chash,
            "intent": intent,
            "brief": brief[:200],
        },
    )
    return str(path)


def _author_one(
    store: Store,
    brief: str,
    *,
    intent: str,
    directory: Path,
    llm_enabled: bool,
    authored_by: str = "human",  # "agent" for the theme-batch master → hard novelty reject (inbox flood guard)
    chat=None,  # noqa: ANN001 — injectable LLM seam (lab.llm.ChatFn) so CI runs offline
) -> AuthoredSpec:
    """Draft ONE brief into a typed spec (reusing draft_from_brief — same no-magic-numbers guarantee), validate
    it, and write the valid ones to the inbox. Never raises into the router. `authored_by` flows to draft_from_brief
    so an agent batch hard-rejects near-duplicates (a human's intentional re-run stays advisory)."""
    try:
        draft = draft_from_brief(brief, llm_enabled=llm_enabled, store=store, authored_by=authored_by, chat=chat)
    except Exception as exc:  # noqa: BLE001 — authoring is best-effort; a bad brief is reported, not fatal
        return AuthoredSpec(name=brief[:48], brief=brief, valid=False, issues=[f"author_error:{type(exc).__name__}"])
    issues = draft.issues or validate_spec(draft.spec)
    authored = AuthoredSpec(
        name=draft.spec.name, brief=brief, valid=not issues, issues=issues, notes=list(draft.notes)
    )
    if not issues:
        authored.path = _write_spec(store, draft.spec, intent=intent, brief=brief, directory=directory, authored_by=authored_by)
    return authored


def strategize(
    text: str,
    *,
    store: Store,
    n: int | None = None,
    theme: str | None = None,
    pine_source: str | None = None,
    inbox_dir: Path | None = None,
    llm_enabled: bool = False,
    gate: bool = False,
    market_data: MarketDataProvider | None = None,
    chat=None,  # noqa: ANN001 — injectable LLM seam; None → deterministic/offline authoring
) -> StrategizeRoute:
    """The front door. Classify `text`, then:
      • vibe  → author ONE spec from the brief → inbox.
      • batch → author N specs varying a theme → inbox (Claude Code authors, cheap LLM formats when keyed).
      • pine  → translate the pasted Pine → typed spec → inbox.
      • url / scan / evolve → return a delegated route naming the sibling skill (needs a fetch / the Gate / a cohort).
    Authored specs are TRACKED (one event each) and, when `gate=True`, run through the DETERMINISTIC inbox screen
    (reusing scan_inbox → FarmLoop) right away. THIN: it composes the existing building blocks, judges nothing."""
    directory = inbox_dir or _INBOX_DIR
    intent = classify_intent(text, n=n, theme=theme)
    skill = SKILL_FOR[intent]
    route = StrategizeRoute(intent=intent, skill=skill, reason="", delegated=intent not in _AUTHORABLE)

    if intent == "vibe":
        route.reason = "free-form idea → authored one spec via dump-idea's drafter"
        route.authored = [_author_one(store, text, intent=intent, directory=directory, llm_enabled=llm_enabled, chat=chat)]
        route.count = 1

    elif intent == "batch":
        count, resolved = _parse_batch(text, n=n, theme=theme)
        route.theme = resolved
        if n is not None and n > _MAX_BATCH:
            route.notes.append(f"requested {n} clamped to {_MAX_BATCH} (inbox flood guard)")
        briefs = _theme_briefs(resolved, count)
        route.authored = [
            _author_one(store, b, intent=intent, directory=directory, llm_enabled=llm_enabled, authored_by="agent", chat=chat)
            for b in briefs
        ]
        route.count = len(route.authored)
        route.reason = f"theme batch → authored {sum(a.valid for a in route.authored)}/{count} specs varying '{resolved}'"

    elif intent == "pine":
        src = pine_source if pine_source is not None else text
        route.authored = [_author_pine(store, src, directory=directory)]
        route.count = 1
        route.delegated = not route.authored[0].valid  # if local translate failed, fall back to the import-pine skill
        route.reason = (
            "pasted Pine → translated to a typed spec via import-pine's translator"
            if route.authored[0].valid
            else "Pine translate incomplete — hand to the import-pine skill for review"
        )

    elif intent == "url":
        route.reason = "URL → paste the source into import-pine (TradingView renders Pine client-side; auto-scrape unsupported)"
    elif intent == "scan":
        route.reason = "discovery → drive scan-signals (cross-asset sweep → Gate); propose-only"
    elif intent == "evolve":
        route.reason = "compound a winner → drive evolve-strategy (cohort → existing FDR Gate)"

    if gate and any(a.valid for a in route.authored):
        route.cohort = _gate_authored(store, directory=directory, market_data=market_data)

    return route


def _author_pine(store: Store, source: str, *, directory: Path) -> AuthoredSpec:
    """Translate pasted Pine → typed spec (reuse strategy.pine.translate_pine; magic numbers are lifted into
    param_space there) and write the valid result to the inbox. Never raises into the router."""
    try:
        from cosmu.strategy.pine import translate_pine

        tr = translate_pine(source)
        spec = tr.spec
    except Exception as exc:  # noqa: BLE001 — unsupported/partial Pine degrades to the import-pine skill
        return AuthoredSpec(name="pine", brief=source[:200], valid=False, issues=[f"pine_error:{type(exc).__name__}"])
    issues = validate_spec(spec)
    authored = AuthoredSpec(name=spec.name, brief=source[:200], valid=not issues, issues=issues, notes=list(tr.notes))
    if not issues:
        authored.path = _write_spec(store, spec, intent="pine", brief=spec.name, directory=directory)
    return authored


def _gate_authored(store: Store, *, directory: Path, market_data: MarketDataProvider | None) -> CohortSummary | None:
    """Run the DETERMINISTIC inbox screen on what we just authored (reuse scan_inbox → FarmLoop). strategize
    judges nothing; the Gate disposes. Offline-safe (cached bars / fixtures)."""
    from cosmu.lab.inbox import scan_inbox

    report = scan_inbox(store, inbox_dir=directory, market_data=market_data, run_cohort=True)
    return report.cohort


def _print(route: StrategizeRoute) -> None:
    print(f"STRATEGIZE — intent={route.intent} skill=/{route.skill}")
    print(f"  {route.reason}")
    if route.theme:
        print(f"  theme={route.theme!r} count={route.count}")
    if route.delegated and not route.authored:
        print(f"  → drive /{route.skill} (network/gate-heavy path; strategize routes, the skill does the work)")
    for a in route.authored:
        status = "authored" if a.valid else f"invalid: {a.issues}"
        where = f"  ({a.path})" if a.path else ""
        print(f"    [{status}] {a.name}{where}")
    for note in route.notes:
        print(f"  note: {note}")
    if route.cohort is not None:
        c = route.cohort
        print(f"  GATED (deterministic): generated={c.generated} passed={c.passed} killed={c.killed} kill_rate={c.kill_rate}")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    parser = argparse.ArgumentParser(
        description="The /strategize front door — route a vibe / URL / Pine / 'find me X' / 'generate N from a theme' "
        "to the right strategy path; author typed specs into the inbox (offline-safe, no magic numbers).",
    )
    parser.add_argument("input", help="the operator's free-form input (vibe, URL, Pine source, or 'generate N on <theme>')")
    parser.add_argument("--n", type=int, default=None, help="batch size: author N specs varying a theme")
    parser.add_argument("--theme", default=None, help="explicit theme for batch mode (else parsed from the input)")
    parser.add_argument("--llm", action="store_true", help="enable the cheap-LLM formatter (needs a key); default deterministic")
    parser.add_argument("--gate", action="store_true", help="run the deterministic inbox screen on what was authored")
    args = parser.parse_args(argv)

    store = Store(Settings())
    route = strategize(args.input, store=store, n=args.n, theme=args.theme, llm_enabled=args.llm, gate=args.gate)
    _print(route)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
