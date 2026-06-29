# intent: SIZE a conviction bet from an account's authority + EV — embodying "profit > hit-rate". A higher
# authority (skill-anchored) AND/OR higher EV-per-call (excess-hit × magnitude) account earns a BIGGER bet, always
# clamped to the per-bet cap, and the max-loss is ALWAYS bounded by the hard cap. PURE: no I/O, no clock, no
# randomness — same inputs → same size. The sizer NEVER up-sizes past the caps; it only scales within them, so a
# hallucinated/over-eager upstream can at worst propose a capped bet (the deterministic envelope is the safety).
#
# The weight is monotone non-decreasing in BOTH authority and EV: authority scales the whole bet (a low-skill
# account that somehow slips through gets a small bet), and EV lifts it toward the cap (a few-but-huge caller's
# big call sizes up). Both saturate — no single axis can blow the bet past the per-bet cap.

from __future__ import annotations

from decimal import Decimal

from cosmu.conviction.authority_source import AccountAuthority
from cosmu.conviction.models import ConvictionCaps, quantize_usd

# EV at which the payoff term reaches half its range. EV = excess_hit_rate (<=1) × avg_hit_magnitude (a fractional
# return, e.g. 0.05), so a strong caller sits around 0.02–0.05; 0.02 puts the half-saturation in that band.
_EV_HALF_SATURATION = 0.02

# A high-authority account with ZERO measured EV still bets this fraction of its authority-scaled envelope (we
# trust calibration even before magnitude shows up); EV lifts it from here toward 1.0.
_PAYOFF_FLOOR = 0.5


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def conviction_weight(authority: AccountAuthority) -> float:
    """The [0, 1] fraction of the per-bet cap this account's call earns, from authority × EV. Monotone in both:
    authority_score scales the envelope; EV-per-call lifts it (a bigger-move caller sizes closer to the cap). A
    zero-authority account → 0 (no bet); a max-authority, high-EV account → ~1 (the full cap)."""
    a = _clamp01(authority.authority_score)
    ev = max(0.0, authority.ev_per_call)
    payoff = ev / (ev + _EV_HALF_SATURATION)  # [0, 1) — saturating in EV
    return _clamp01(a * (_PAYOFF_FLOOR + (1.0 - _PAYOFF_FLOOR) * payoff))


def size_conviction(authority: AccountAuthority, caps: ConvictionCaps) -> tuple[Decimal, Decimal]:
    """(size_usd, max_loss_usd) for this account's call under the caps. Size = per-bet cap × conviction_weight,
    floored at `floor_usd` (a sub-floor bet isn't worth proposing) and capped at `per_bet_usd`. Max-loss =
    size × stop_loss_frac, ALWAYS capped to `max_loss_usd` (the hard risk bound — true for ANY size or cap).
    Returns (0, 0) when the weight is ~0 (no bet)."""
    w = conviction_weight(authority)
    if w <= 0.0:
        return Decimal("0"), Decimal("0")

    raw = caps.per_bet_usd * Decimal(str(w))
    size = max(raw, caps.floor_usd)            # never propose a dust bet once we've decided to bet
    size = min(size, caps.per_bet_usd)         # never exceed the per-bet cap
    size = quantize_usd(size)

    # The directional stop implies a loss of size × stop_loss_frac; the hard cap binds whenever that exceeds it
    # (a tighter implied stop), so max-loss is ALWAYS <= caps.max_loss_usd.
    max_loss = min(size * Decimal(str(caps.stop_loss_frac)), caps.max_loss_usd)
    return size, quantize_usd(max_loss)
