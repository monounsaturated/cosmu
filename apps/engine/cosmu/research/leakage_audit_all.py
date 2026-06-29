# intent: the STANDING leakage audit over the WHOLE WIRED alt-feature surface — run the three-disconfirmer
# leakage tripwire (cosmu.research.leakage_tripwire.audit_feature) on EVERY enabled, store-routed alt-data
# feature's REAL point-in-time series, not just the synthetic controls. The ~36 wired free/xAI alt features
# (social_authority, funding, sentiment, on-chain, GKG, …) were hand-stamped PIT-honest BY CONVENTION; this
# module BEHAVIOURALLY audits that convention against the data itself. A baked-in look-ahead in even one feature
# is Gate-INVISIBLE (the Gate validates edge-after-costs, not pipeline honesty) and silently feeds the live Gate
# a peek — the #1 blow-up risk ([[vibe_coding_leakage_risk]]). This is REPORT-ONLY + PROPOSE-ONLY: it never
# moves money, runs no backtest, changes no Gate constant, and mutates no data (read-only store reads).
#
# WHAT IT DOES (per feature, capped/sampled, bounded):
#   1. Enumerate the WIRED features = feature_registry.feature_names() (enabled) ∩ store route (_STORE_PROVIDER_OF),
#      MINUS the bar-computed PRICE_FEATURES (those have no store series — they ARE the bars). This is exactly the
#      leading-signal universe the gate's as-of join consumes.
#   2. For each feature, reuse the EXISTING fetch path (StoreBackedAltProvider.fetch_series — the SAME read the
#      correlation scan + gate use): try each asset symbol, then the market-wide "MARKET" scope; keep the
#      (scope, bars) pairing with the MOST joined observations. Down-sample a very long point series for runtime.
#   3. Run leakage_tripwire.audit_feature on the real (points, bars) and classify:
#        FAIL  — a POSITIVE look-ahead: the available_at audit found a value joined before it was knowable,
#                OR the forward-shift sanity found that LAGGING the feature beats the live read (a baked-in peek).
#                THIS IS A REAL LEAK. The script EXITS NON-ZERO if ANY feature FAILs.
#        WARN  — no look-ahead, but the IC sits inside the shuffled band (a noise/artefact smell). Advisory only:
#                a dead/noisy feature is not a leak, and most honest tier1 alt-features have near-zero IC. Never
#                fails the run (the Gate is the disposal layer for weak signals — this audit guards LEAKAGE).
#        SKIP  — insufficient data to reason about (no store series, or too few joined PIT observations).
#        PASS  — strictly backward-looking join AND no baked-in peek AND a shuffle-surviving IC.
#
# INVARIANTS: idempotent + deterministic (string-seeded shuffle null, fixed asset list, sorted feature order);
# hermetic-where-possible (the provider + bar loader are INJECTABLE so the test drives a fixture set with no DB,
# no network); bounded (a small asset cap, a per-series sample cap, a modest shuffle-trial count). NEVER crashes
# on a missing/unreadable feature — that is an honest SKIP, never a fabricated series. Reuses the codebase's
# fetch + align_asof + audit_feature; never a second hand-rolled join or correlation.

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from cosmu.config.feature_registry import FEATURE_REGISTRY, feature_names
from cosmu.data.backtest import PRICE_FEATURES, align_asof
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import _STORE_PROVIDER_OF
from cosmu.research.leakage_tripwire import TripwireReport, audit_feature

# --- bounds (CONSERVATIVE on the M2 + network): keep the audit fast, light, and offline-friendly. ---
_DEFAULT_ASSETS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")  # a small, liquid, deep-history sample
_BARS_LIMIT: int = 600              # ~1.6y of daily bars — enough to score an IC, cheap to load from cache
_MAX_POINTS: int = 1500            # down-sample a longer PIT series to this many points (stride sampling)
_MIN_OBS: int = 30                 # below this many joined PIT obs the IC is too thin to reason about → SKIP
_SHUFFLE_TRIALS: int = 100         # the shuffle-null trial count (deterministic; modest for runtime)
_SEED: int = 0
_HORIZON: int = 1

# --- leak-CONFIRMATION bar (above the tripwire's own forward-shift trip) so the audit does not cry wolf on the
# thin, smooth daily real series most alt-features actually have. The tripwire's forward_shift_sanity trips on a
# backward (more-honest) IC beating the live read by > its 15% margin once the live IC clears 0.05. On a SHORT
# real series (n≈50-80) with OVERLAPPING horizon-1 returns the EFFECTIVE n is tiny, so a near-zero, slowly-varying
# feature's |IC| jitters ±0.03 across a one-bar shift and clears that margin by chance — and a NON-CAUSAL CONTROL
# (the astro ephemeris) cannot have a real look-ahead by construction, so a "leak" verdict on it is a FALSE
# POSITIVE, full stop. A GENUINE baked-in 1-bar peek is unmistakable by contrast: the live IC is STRONG (the
# synthetic leaked control: live|IC| 0.58-0.82) and lagging it recovers a much stronger alignment. So the audit
# only CONFIRMS a forward-shift FAIL as a real leak when the live IC is genuinely strong AND the sample is not
# thin; a weak/thin forward-shift trip is downgraded to WARN (surfaced, never silently dropped) — the honest
# verdict is "shift-noise on a thin/smooth series", not a leak. CONSERVATIVE: errs toward WARN, never a false FAIL.
_LEAK_MIN_LIVE_IC: float = 0.30    # the live |IC| a forward-shift FAIL needs before it is a CONFIRMED peek
_LEAK_MIN_OBS: int = 60            # and the joined-obs floor below which h=1 overlap makes the shift IC unreliable


# --- the seam the script consumes (so the test injects fixtures with no DB / no network). ---


class AltProvider(Protocol):
    """The fetch seam — exactly StoreBackedAltProvider.fetch_series (the SAME read the scan + gate use)."""

    def fetch_series(self, symbol: str, metric: str, *, limit: int) -> list[AltDataPoint]: ...


BarsLoader = Callable[[str], list[Bar]]  # symbol -> its bars (cache-backed; injectable for the test)


# --- verdicts ---

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class FeatureAuditResult:
    feature: str
    source: str
    verdict: str               # PASS | WARN | FAIL | SKIP
    scope: str                 # the asset symbol or "MARKET" the series was scored against ("" when skipped)
    n_obs: int
    real_ic: float
    reason: str                # human-readable: WHY this verdict (look-ahead / artefact smell / no data)
    report: TripwireReport | None = None  # the full tripwire report (None when skipped)

    @property
    def is_leak(self) -> bool:
        """A FAIL is a positive look-ahead — a REAL leak that must fail the run."""
        return self.verdict == FAIL


def wired_store_features() -> list[tuple[str, str]]:
    """The audit universe as (name, source) pairs: every ENABLED feature (feature_names()) that has a STORE
    ROUTE (_STORE_PROVIDER_OF) and is NOT a bar-computed PRICE_FEATURE. These are exactly the leading-signal
    alt-features the gate's as-of join reads from the store — the surface a baked-in look-ahead could hide in.
    Read from the registry so a newly-wired source is audited automatically. Deterministic (sorted by name)."""
    enabled = feature_names()
    routed = set(_STORE_PROVIDER_OF)
    source_of = {f.name: f.source for f in FEATURE_REGISTRY}
    names = sorted(n for n in enabled if n in routed and n not in PRICE_FEATURES)
    return [(n, source_of.get(n, "?")) for n in names]


def _sample(points: list[AltDataPoint], cap: int) -> list[AltDataPoint]:
    """Stride-sample a long PIT series down to <= cap points (keeps chronological order + the latest point),
    so a feature with years of dense history doesn't blow the runtime. Identity when already small."""
    n = len(points)
    if n <= cap:
        return points
    stride = (n + cap - 1) // cap
    sampled = points[::stride]
    if sampled and sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def _best_scope(
    provider: AltProvider, feature: str, assets: list[str], bars_by_asset: dict[str, list[Bar]],
    *, bars_limit: int,
) -> tuple[str, list[AltDataPoint], list[Bar]] | None:
    """Pick the (scope, points, bars) pairing with the MOST joined PIT observations across the asset universe +
    the market-wide MARKET scope. Mirrors correlation_scan.scan_feature_asset's scope order (asset then MARKET).
    A missing/unreadable series is an honest skip (never fabricated). None when nothing joins anywhere."""
    best: tuple[str, list[AltDataPoint], list[Bar]] | None = None
    best_n = 0
    # MARKET is scored against each asset's bars; pick whichever asset's bars maximise the join.
    for scope in (*assets, "MARKET"):
        for asset in assets:
            bars = bars_by_asset.get(asset)
            if not bars:
                continue
            sym = asset if scope != "MARKET" else "MARKET"
            try:
                pts = provider.fetch_series(sym, feature, limit=bars_limit + _MAX_POINTS)
            except Exception:  # noqa: BLE001 — a missing/unreadable series is an honest skip, never a crash
                pts = []
            if not pts:
                continue
            pts = _sample(pts, _MAX_POINTS)
            joined = align_asof(pts, bars)
            if len(joined) > best_n:
                best_n = len(joined)
                best = (f"{sym}@{asset}" if scope == "MARKET" else asset, pts, bars)
            if scope != "MARKET":
                break  # a per-asset series is scored against its OWN bars only — no cross-asset pairing
    return best


def audit_one(
    provider: AltProvider, feature: str, source: str, assets: list[str],
    bars_by_asset: dict[str, list[Bar]], *, bars_limit: int = _BARS_LIMIT,
    horizon: int = _HORIZON, shuffle_trials: int = _SHUFFLE_TRIALS, seed: int = _SEED,
) -> FeatureAuditResult:
    """Audit ONE wired feature: fetch its real PIT series (best scope), run the leakage tripwire, classify.
    Pure given (provider, bars) — never raises (a fetch/audit failure is an honest SKIP, not a crash)."""
    try:
        picked = _best_scope(provider, feature, assets, bars_by_asset, bars_limit=bars_limit)
    except Exception as exc:  # noqa: BLE001 — defensive: a provider blow-up is a skip, never a crashed run
        return FeatureAuditResult(feature, source, SKIP, "", 0, 0.0, f"fetch error: {type(exc).__name__}")
    if picked is None:
        return FeatureAuditResult(feature, source, SKIP, "", 0, 0.0, "no store series / never joins any bar")
    scope, points, bars = picked

    try:
        report = audit_feature(
            points, bars, horizon=horizon, feature=feature,
            shuffle_trials=shuffle_trials, seed=seed,
        )
    except Exception as exc:  # noqa: BLE001 — a degenerate series is a skip, never a crashed run
        return FeatureAuditResult(feature, source, SKIP, scope, 0, 0.0, f"audit error: {type(exc).__name__}")

    if report.n_obs < _MIN_OBS:
        return FeatureAuditResult(
            feature, source, SKIP, scope, report.n_obs, report.real_ic,
            f"only {report.n_obs} joined PIT obs (< {_MIN_OBS}) — too thin to reason about", report,
        )

    failed = set(report.failed_checks)
    warns: list[str] = []

    # (A) AVAILABLE_AT audit: a real LOOK-AHEAD is a future-value VIOLATION (a value joined before it was
    # knowable). A bare WRONG-WINNER with ZERO violations is a same-available_at tie-break (two revisions stamped
    # at the same instant, ordered differently than max() picks) — a join-ordering nit, NOT a peek into the
    # future. Confirm a leak only on a violation; downgrade a pure tie-break to WARN (surfaced, never dropped).
    avail_leak = "available_at_audit" in failed and report.available_at.violations > 0
    if "available_at_audit" in failed and not avail_leak:
        warns.append(
            f"available_at wrong-winner x{report.available_at.mismatches} with 0 future-value violations "
            "(same-timestamp revision tie-break, not a look-ahead)"
        )

    # (B) FORWARD-SHIFT sanity: the tripwire trips when the more-honest -1 lag beats the live read. CONFIRM it
    # as a real baked-in peek ONLY when the live IC is genuinely STRONG and the sample is not thin — otherwise it
    # is shift-noise on a thin/smooth daily series (the regime where a near-zero IC jitters across a one-bar
    # shift), which a NON-CAUSAL CONTROL proves by failing identically (it cannot have a real look-ahead).
    fs = report.forward_shift
    fs_strong = abs(fs.live_ic) >= _LEAK_MIN_LIVE_IC and report.n_obs >= _LEAK_MIN_OBS
    fs_leak = "forward_shift_sanity" in failed and fs_strong
    if "forward_shift_sanity" in failed and not fs_leak:
        warns.append(
            f"forward-shift tripped but UNCONFIRMED (live|IC|={fs.live_ic:.4f} < {_LEAK_MIN_LIVE_IC} or "
            f"n={report.n_obs} < {_LEAK_MIN_OBS}) — shift-noise on a thin/smooth series, NOT a confirmed leak"
        )

    if avail_leak or fs_leak:
        why = []
        if avail_leak:
            why.append(
                f"LOOK-AHEAD in join ({report.available_at.violations} future-value, "
                f"{report.available_at.mismatches} wrong-winner)"
            )
        if fs_leak:
            why.append(
                f"BAKED-IN PEEK (live|IC|={fs.live_ic:.4f} strong; lagging -1 IC={fs.backward_ic:.4f} beats it)"
            )
        return FeatureAuditResult(
            feature, source, FAIL, scope, report.n_obs, report.real_ic, "; ".join(why), report,
        )

    # No CONFIRMED look-ahead. Carry any unconfirmed-trip notes, then fold in the shuffle verdict.
    if not report.shuffle.survives:
        warns.append(
            f"IC inside shuffled band (real|IC|={abs(report.real_ic):.4f}, "
            f"null_mean|IC|={report.shuffle.null_mean_abs:.4f}, p={report.shuffle.p_value:.4f}) — "
            "noise/artefact smell, NOT a leak (the Gate disposes weak signals)"
        )
    if warns:
        return FeatureAuditResult(
            feature, source, WARN, scope, report.n_obs, report.real_ic, "; ".join(warns), report,
        )

    return FeatureAuditResult(
        feature, source, PASS, scope, report.n_obs, report.real_ic,
        "strictly as-of join, no baked-in peek, IC survives shuffle", report,
    )


@dataclass(frozen=True)
class AuditAllReport:
    results: list[FeatureAuditResult]

    @property
    def leaks(self) -> list[FeatureAuditResult]:
        return [r for r in self.results if r.is_leak]

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0}
        for r in self.results:
            out[r.verdict] = out.get(r.verdict, 0) + 1
        return out

    def render(self) -> str:
        c = self.counts()
        lines = [
            "LEAKAGE AUDIT — ALL WIRED ALT-FEATURES (report-only; PROPOSE-ONLY; the Gate disposes)",
            f"  {len(self.results)} features  ·  {c[PASS]} PASS · {c[WARN]} WARN · "
            f"{c[FAIL]} FAIL · {c[SKIP]} SKIP",
            "",
            f"  {'feature':28s} {'source':14s} {'verdict':7s} {'scope':14s} "
            f"{'n':>5s} {'IC':>8s}  reason",
        ]
        for r in self.results:
            lines.append(
                f"  {r.feature[:26]:28s} {r.source[:12]:14s} {r.verdict:7s} {r.scope[:12]:14s} "
                f"{r.n_obs:>5d} {r.real_ic:>+8.4f}  {r.reason}"
            )
        if self.leaks:
            lines.append("")
            lines.append(f"  *** {len(self.leaks)} REAL LEAK(S) — a baked-in look-ahead feeds the Gate a peek ***")
            for r in self.leaks:
                lines.append(f"      LEAK  {r.feature} ({r.scope}): {r.reason}")
        else:
            lines.append("")
            lines.append("  No look-ahead found in any audited wired feature (clean or skipped).")
        return "\n".join(lines)

    def markdown(self) -> str:
        """The committed report body (docs/reports/…): a verdict header + a per-feature table."""
        c = self.counts()
        out = [
            "# Leakage audit — ALL wired alt-features",
            "",
            "Report-only behavioural audit of the three-disconfirmer leakage tripwire "
            "(`cosmu.research.leakage_tripwire.audit_feature`) over EVERY enabled, store-routed alt-data "
            "feature's REAL point-in-time series. The ~36 wired alt-features were hand-stamped PIT-honest by "
            "CONVENTION; this audits that convention against the data. PROPOSE-ONLY: it never moves money, "
            "runs no backtest, changes no Gate constant, and reads the store read-only.",
            "",
            f"**Verdict: {'LEAK FOUND' if self.leaks else 'NO LEAK FOUND'}** — "
            f"{len(self.results)} features · {c[PASS]} PASS · {c[WARN]} WARN · {c[FAIL]} FAIL · {c[SKIP]} SKIP.",
            "",
            "- **FAIL** = a positive look-ahead (value joined before knowable, or lagging the feature beats the "
            "live read = a baked-in peek). A real leak; fails the run (non-zero exit).",
            "- **WARN** = no look-ahead, but the IC sits inside the shuffled band (noise/artefact smell). "
            "Advisory only — a weak/dead feature is not a leak (the Gate disposes weak signals).",
            "- **SKIP** = insufficient data to reason about (no store series, or too few joined PIT obs).",
            "- **PASS** = strictly as-of join, no baked-in peek, IC survives the shuffle null.",
            "",
            "| feature | source | verdict | scope | n_obs | real_ic | reason |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in self.results:
            out.append(
                f"| `{r.feature}` | {r.source} | **{r.verdict}** | {r.scope} | {r.n_obs} | "
                f"{r.real_ic:+.4f} | {r.reason} |"
            )
        if self.leaks:
            out += ["", "## REAL LEAK(S) FOUND", ""]
            for r in self.leaks:
                out.append(f"- **`{r.feature}`** ({r.scope}): {r.reason}")
        out += [
            "",
            "## Limitations (read before trusting a clean verdict)",
            "",
            "- **Thin real history dominates.** Most alt-features have only ~50-82 daily points joined to the bars "
            "(many newly-wired sources have weeks, not years), and 37 have too few / no store rows to score at all "
            "(SKIP). The audit can only CONFIRM or rule out a leak where the data is deep enough — a SKIP is "
            "*not* a clean bill of health, it is *unaudited for lack of data*.",
            "- **The forward-shift check is noisy on short, smooth daily series with overlapping h=1 returns.** A "
            "near-zero, slowly-varying feature's |IC| jitters across a one-bar shift and can trip the tripwire's "
            "forward-shift sanity by chance — proven by the NON-CAUSAL astro controls tripping it identically "
            "(they cannot have a real look-ahead by construction). This audit therefore only CONFIRMS a "
            f"forward-shift trip as a leak when the live |IC| is strong (>= {_LEAK_MIN_LIVE_IC}) AND n >= "
            f"{_LEAK_MIN_OBS}; weaker/thinner trips are surfaced as WARN, never a false FAIL. The synthetic "
            "leaked control (live|IC| ~0.58-0.82) clears that bar, so a genuine baked-in peek is still caught.",
            "- **A pure available_at wrong-winner with zero future-value violations is a same-timestamp revision "
            "tie-break, not a look-ahead** — downgraded to WARN (e.g. `dxy`).",
            "- **Re-run as history deepens.** The right cadence is to re-run this audit periodically; a feature that "
            "is SKIP today should graduate to PASS/WARN/FAIL once it accrues >= 30-60 PIT observations.",
        ]
        return "\n".join(out) + "\n"


def run_audit_all(
    provider: AltProvider, bars_loader: BarsLoader, *, assets: list[str] | None = None,
    features: list[tuple[str, str]] | None = None, bars_limit: int = _BARS_LIMIT,
    horizon: int = _HORIZON, shuffle_trials: int = _SHUFFLE_TRIALS, seed: int = _SEED,
) -> AuditAllReport:
    """Run the leakage tripwire over the WIRED alt-feature universe. `provider` + `bars_loader` are INJECTED so
    the test drives a fixture set with no DB / no network (hermetic). Deterministic + idempotent for a fixed
    (provider, bars, seed). Never raises on a per-feature failure (honest SKIP). Results are sorted by verdict
    severity (FAIL → WARN → SKIP → PASS) then name, so a leak surfaces at the top of the report."""
    asset_list = list(assets) if assets is not None else list(_DEFAULT_ASSETS)
    feats = features if features is not None else wired_store_features()

    bars_by_asset: dict[str, list[Bar]] = {}
    for a in asset_list:
        try:
            bars = bars_loader(a)
        except Exception:  # noqa: BLE001 — an unloadable asset is skipped, never a crashed run
            bars = []
        if bars:
            bars_by_asset[a] = bars

    results = [
        audit_one(
            provider, name, source, asset_list, bars_by_asset,
            bars_limit=bars_limit, horizon=horizon, shuffle_trials=shuffle_trials, seed=seed,
        )
        for name, source in feats
    ]
    order = {FAIL: 0, WARN: 1, SKIP: 2, PASS: 3}
    results.sort(key=lambda r: (order.get(r.verdict, 9), r.feature))
    return AuditAllReport(results=results)


# ---------------------------------------------------------------- live wiring (real store + cache-backed bars)


def _live_provider() -> AltProvider:
    """The real read-only fetch path — StoreBackedAltProvider over the configured store (same as the scan)."""
    from cosmu.config.settings import get_settings
    from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
    from cosmu.knowledge.store import Store

    return StoreBackedAltProvider(PgAltDataStore(Store(get_settings())))


def _live_bars_loader(bars_limit: int = _BARS_LIMIT) -> BarsLoader:
    """Cache-backed crypto bars (default_crypto_reference reads the local .cosmu cache; no live Binance call
    needed when the cache is warm — the M2 is geo-blocked). A symbol with no cached bars returns []."""
    from cosmu.data.market import default_crypto_reference

    prov = default_crypto_reference()

    def _load(symbol: str) -> list[Bar]:
        try:
            return prov.fetch_bars(symbol, "1d", limit=bars_limit)
        except Exception:  # noqa: BLE001 — an unfetchable/geo-blocked symbol is an honest skip
            return []

    return _load


def _main() -> int:
    """`python -m cosmu.research.leakage_audit_all` — run the leakage tripwire over EVERY wired alt-feature's
    real PIT series and print the PASS/WARN/FAIL/SKIP table. EXITS NON-ZERO if ANY feature FAILs (a real
    look-ahead). Read-only; no backtest; no money path; mutates no data. `--write-md PATH` also writes the
    committed report body."""
    argv = sys.argv[1:]
    report = run_audit_all(_live_provider(), _live_bars_loader())
    print(report.render())

    if "--write-md" in argv:
        i = argv.index("--write-md")
        if i + 1 < len(argv):
            from pathlib import Path

            Path(argv[i + 1]).write_text(report.markdown(), encoding="utf-8")
            print(f"\nwrote {argv[i + 1]}")

    return 1 if report.leaks else 0


if __name__ == "__main__":
    raise SystemExit(_main())
