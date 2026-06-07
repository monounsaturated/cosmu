# intent: RE-TEST the two equities wave-1 near-misses — (1) SHORT-TERM CROSS-SECTIONAL REVERSAL and
# (2) BETTING-AGAINST-BETA / LOW-VOL — at REAL, DEFENSIBLE IBKR equity fees instead of the conservative
# made-up 7-13 bps/side that wave-1 used. The wave-1 verdict logged reversal as a KNIFE-EDGE near-miss
# ("breakeven 12.44 bps vs 13 bps cost — failed by ~0.6 bps; correct sign"), so the FAIL may be a fee
# artifact. inputs: the OFFLINE equities daily JSON cache; outputs: a printed PASS/FAIL per signal per fee.
#
# DOCTRINE (unchanged, NOT tuned to pass):
#   * route through the EXISTING cohort.promote_cohort + Benjamini-Hochberg (q=0.10) ONLY — never the leaky
#     gate.evaluate_cross_asset_ablation path. We reuse the BLESSED wave-1 modules' run()/construction verbatim
#     and only swap the per-side fee constant, so the gate logic, trial ledger, deflation and FDR are identical.
#   * count EVERY variant as a trial (the wave-1 modules already register every grid arm); fresh tempfile store.
#   * NO synthetic / zero-fill / look-ahead (signal through close[t], forward return) — inherited from the modules.
#   * survivorship is FLAGGED: the single-name universe is TODAY's survivors. The honest constructions are the
#     dollar-neutral L/S spread (survivorship hits both legs ~symmetrically) and (for BAB) the long tranche vs the
#     equal-weight survivorship-matched basket. Long-only absolute books are upward-biased and flagged as such.
#
# FEE MODEL — REAL IBKR PRO, DEFENDED (not cherry-picked, not zero-fill):
#   The codebase venue catalog (spine/venue.py) already carries IBKR at maker=taker=0.5 bps/side COMMISSION
#   ("IBKR ... nets to well under a basis point on liquid names"). That is COMMISSION ONLY. Real all-in retail
#   cost on liquid US large-caps / ETFs = ~0.5 bps commission + ~0.5-2 bps bid-ask half-spread + small market
#   impact = ~1.5-3 bps/side. We adopt ~2 bps/side as the central IBKR all-in estimate, and run a SENSITIVITY
#   sweep over {1, 2, 3, 5} bps/side so the verdict is not knife-edge-dependent. The conservative wave-1 value
#   (13 bps stock / 6 bps ETF) is included as the REFERENCE column so the reader sees exactly what the fee did.
#   ETFs get HALF the single-name per-side cost at each sweep point (tighter spreads on SPY/QQQ/sector ETFs).
#
# This module is propose/measure-only — it never moves money. It is a re-pricing of an already-blessed gate run.

from __future__ import annotations

import sys
from datetime import UTC, datetime

from cosmu.research import equity_lowvol_bab_cohort as bab
from cosmu.research import equity_reversal_cohort as rev

# Per-side stock fee (fraction) for each sweep point; ETF gets HALF (tighter). 1 bp = 0.0001.
# 13 bps is the wave-1 conservative reference (kept LAST so the sweep reads cheap->expensive->reference).
SWEEP_STOCK_BPS = [1.0, 2.0, 3.0, 5.0, 13.0]


def _etf_bps(stock_bps: float) -> float:
    # ETFs trade ~half the single-name all-in cost (tighter half-spread + lower impact on SPY/QQQ/sector ETFs).
    # The wave-1 reference (13 stock) paired with 6 ETF, so keep that exact pairing at the reference point.
    return 6.0 if stock_bps == 13.0 else stock_bps / 2.0


def _set_fees(module, stock_bps: float) -> None:
    """Monkeypatch the module-level per-side cost constants. The construction reads these via _per_side_cost,
    so this re-prices the SAME gate run at a new fee without touching any gate / FDR / trial logic."""
    module.COST_STOCK_PER_SIDE = stock_bps / 1e4
    module.COST_ETF_PER_SIDE = _etf_bps(stock_bps) / 1e4


def _accelerate_bab() -> None:
    """PERFORMANCE-ONLY: memoize the BAB module's two pure hot functions (_month_return and _trailing_stats).
    Both are deterministic functions of (panel-contents, args); the wave-1 module recomputes them O(days) times
    inside the bench/rank loops, which is the only reason a full single-name sweep takes minutes. Memoizing
    returns BYTE-IDENTICAL values — it changes wall-clock only, NOT any return, metric, gate, FDR or verdict.
    Cache is keyed on id(panel) (a fresh panel per run() invalidates it implicitly)."""
    if getattr(bab, "_REFEE_ACCEL", False):
        return
    _mr = bab._month_return
    _ts = bab._trailing_stats
    mr_cache: dict = {}
    ts_cache: dict = {}

    def fast_month_return(panel, sym, month):
        key = (id(panel), sym, month)
        if key not in mr_cache:
            mr_cache[key] = _mr(panel, sym, month)
        return mr_cache[key]

    def fast_trailing_stats(panel, day_idx, sym, market):
        key = (id(panel), day_idx, sym, market)
        if key not in ts_cache:
            ts_cache[key] = _ts(panel, day_idx, sym, market)
        return ts_cache[key]

    bab._month_return = fast_month_return
    bab._trailing_stats = fast_trailing_stats
    bab._REFEE_ACCEL = True


def _restrict_recent(universe: dict, start_year: int) -> None:
    """In-place: trim every Series to bars on/after Jan 1 of start_year. The literature's reversal result is on
    LARGE-CAP, POST-1990-ish data (decimalized, tight-spread). The full 1970 window mixes in the wide-spread,
    pre-decimalization era that is NOT investable at IBKR fees today — so we ALSO report a recent-era window."""
    cut = int(datetime(start_year, 1, 1, tzinfo=UTC).timestamp() * 1000)
    for sym, s in list(universe.items()):
        keep = [(t, c) for t, c in zip(s.ts, s.close, strict=True) if t >= cut]
        if len(keep) < 200:
            del universe[sym]
            continue
        s.ts = [t for t, _ in keep]
        s.close = [c for _, c in keep]


# ----------------------------------------------------------------------------------------------------------
# Re-run the two BLESSED cohort modules' run() at each fee. We patch load_universe so the recent-era window can
# be injected, then restore. Each module's run() does the full promote_cohort + BH-FDR + trial-ledger itself.
# ----------------------------------------------------------------------------------------------------------

def _run_reversal(fee_bps: float, window_start: int | None) -> dict:
    _set_fees(rev, fee_bps)
    orig_load = rev.load_universe
    if window_start is not None:
        def patched_load():
            u = orig_load()
            _restrict_recent(u, window_start)
            return u
        rev.load_universe = patched_load
    try:
        u = rev.load_universe()
        all_syms = sorted(u)
        stocks = [s for s in all_syms if s not in rev.ETFS]
        v = rev.run("LARGE-CAP SINGLE-STOCKS", stocks, [0.2, 0.25, 1 / 3, 0.5])
    finally:
        rev.load_universe = orig_load
    row = next((r for r in v.candidates if r["name"] == "reversal"), {})
    plc = next((r for r in v.candidates if r["name"] == "random_placebo"), {})
    mom = next((r for r in v.candidates if r["name"] == "momentum_control"), {})
    return {"verdict": v.verdict, "n": v.n_weeks, "rev": row, "placebo": plc, "momentum": mom}


def _run_bab(fee_bps: float) -> dict:
    _set_fees(bab, fee_bps)
    u = bab.load_universe()
    all_syms = sorted(u)
    stocks = [s for s in all_syms if s not in bab.ETFS]
    v = bab.run("SINGLE-STOCKS (survivor-biased)", stocks, [0.2, 0.25, 1 / 3, 0.5])
    prim = {n: next((r for r in v.candidates if r["name"] == n), {})
            for n in ("lowvol_long_only", "lowbeta_long_only", "bab_vol_neutral", "bab_beta_neutral")}
    plc = next((r for r in v.candidates if r["name"] == "random_placebo"), {})
    return {"verdict": v.verdict, "n": v.n_months, "primaries": prim, "placebo": plc}


def _fmt_rev(tag: str, fee: float, res: dict) -> str:
    r = res["rev"]
    if not r:
        return f"  [{tag}] fee={fee:>4.1f}bps  (no reversal row)"
    promo = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
    return (f"  [{tag}] stockFee={fee:>4.1f}bps  {promo:>9}  "
            f"net={r['net_total_return']:+.3f} gross={r['gross_total_return']:+.2f} "
            f"costRatio={r['cost_ratio']} annSR={r['ann_sharpe']:+.2f} DSR={r['deflated_sharpe_prob']:.3f} "
            f"maxDD={r['max_dd']:.3f} pbo={r['pbo']:.2f} folds+={r['folds_positive']:.2f} "
            f"turn={r['mean_weekly_turnover']:.2f}  reasons={r['reasons']}")


def _fmt_bab(fee: float, res: dict) -> list[str]:
    out = []
    for name, r in res["primaries"].items():
        if not r:
            continue
        promo = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
        out.append(f"    stockFee={fee:>4.1f}bps  {name:<18} {promo:>9}  "
                   f"net={r['net_total_return']:+.3f} alphaVsEW={r['alpha_vs_ew']:+.3f} "
                   f"DSR={r['deflated_sharpe_prob']:.3f} maxDD={r['max_dd']:.3f} "
                   f"folds+={r['folds_positive']:.2f} turn={r['mean_monthly_turnover']:.3f} "
                   f"reasons={r['reasons']}")
    return out


def main() -> int:
    _accelerate_bab()  # performance-only memoization (byte-identical results) so the BAB sweep is tractable
    print("=" * 100)
    print("EQUITIES RE-TEST AT REAL IBKR FEES — short-term reversal + betting-against-beta/low-vol")
    print("Gate path: cohort.promote_cohort + Benjamini-Hochberg q=0.10 (BLESSED wave-1 modules, fee re-priced).")
    print("IBKR all-in central est ~2 bps/side (0.5 commission + ~1.5 spread/impact); sweep 1/2/3/5; ref=13.")
    print("=" * 100)

    # ---- TEST 1: SHORT-TERM REVERSAL ----
    print("\n### TEST 1 — SHORT-TERM (1-week) CROSS-SECTIONAL REVERSAL, dollar-neutral L/S, large-cap single names")
    print("Disconfirmers: momentum control (sign flip) + random-rank placebo. Survivorship: today's survivors (L/S spread cancels both legs).")

    print("\n[A] FULL HISTORY (1970->2026 where available) — includes wide-spread pre-decimalization era:")
    full = {}
    for fee in SWEEP_STOCK_BPS:
        full[fee] = _run_reversal(fee, None)
        print(_fmt_rev("full", fee, full[fee]))
    # placebo / momentum sanity at the central fee
    c = full[2.0]
    if c["placebo"]:
        print(f"      disconfirm@2bps: placebo net={c['placebo']['net_total_return']:+.3f} "
              f"DSR={c['placebo']['deflated_sharpe_prob']:.3f} promoted={c['placebo']['promoted']}; "
              f"momentum net={c['momentum'].get('net_total_return')} promoted={c['momentum'].get('promoted')}")

    print("\n[B] RECENT-ERA window (2004->2026) — decimalized, IBKR-investable, closer to the literature's regime:")
    recent = {}
    for fee in SWEEP_STOCK_BPS:
        recent[fee] = _run_reversal(fee, 2004)
        print(_fmt_rev("rec ", fee, recent[fee]))
    c = recent[2.0]
    if c["placebo"]:
        print(f"      disconfirm@2bps: placebo net={c['placebo']['net_total_return']:+.3f} "
              f"DSR={c['placebo']['deflated_sharpe_prob']:.3f} promoted={c['placebo']['promoted']}; "
              f"momentum net={c['momentum'].get('net_total_return')} promoted={c['momentum'].get('promoted')}")

    # ---- TEST 2: BETTING-AGAINST-BETA / LOW-VOL ----
    print("\n### TEST 2 — BETTING-AGAINST-BETA / LOW-VOL, monthly rebalance (low turnover), single names")
    print("Books: lowvol/lowbeta long-only (survivor-biased; judged on alpha-vs-EW), bab_vol/bab_beta market-neutral.")
    bab_res = {}
    for fee in SWEEP_STOCK_BPS:
        bab_res[fee] = _run_bab(fee)
        for line in _fmt_bab(fee, bab_res[fee]):
            print(line)
    plc = bab_res[2.0]["placebo"]
    if plc:
        print(f"    disconfirm@2bps: placebo net={plc['net_total_return']:+.3f} "
              f"DSR={plc['deflated_sharpe_prob']:.3f} promoted={plc['promoted']}")

    # ---- VERDICT SUMMARY ----
    print("\n" + "=" * 100)
    print("VERDICT SUMMARY (does the verdict FLIP between fees?)")

    def rev_passes(d):
        return d["rev"].get("promoted", False)
    def bab_passes(d):
        return any(r.get("promoted", False) for r in d["primaries"].values())

    print("  Reversal FULL-history  promoted@fee:",
          {f: rev_passes(full[f]) for f in SWEEP_STOCK_BPS})
    print("  Reversal RECENT-era    promoted@fee:",
          {f: rev_passes(recent[f]) for f in SWEEP_STOCK_BPS})
    print("  BAB/low-vol any-book   promoted@fee:",
          {f: bab_passes(bab_res[f]) for f in SWEEP_STOCK_BPS})
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
