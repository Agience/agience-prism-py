"""The decay / attenuation law entroptics governs — applied, in ONE place.

`optics.py` MEASURES: it reads a length or a rate off an ordered frame through the aperture
(`correlation_length`, `diffraction`, `decay_profile`, `fit_dynamics`). This module APPLIES the
physics those readings parameterise. There is exactly one such physics in this codebase and it
appears under four names:

    the screened propagator      match.propagate / match.expand_associative — `exp(-distance/xi)`
    forgetting                   forgetting.Trace.amplitude — `exp(-dt/tau)`
    spreading activation         activation.spread — `exp(-hop)`
    demurrage                    demurrage.cool — `exp(-dt/tau)`  (the 2nd law, as accounting)

All four are `exp(-x / scale)`: the fraction of a quantity that survives after travelling `x` at a
correlation scale `scale`. Written four times, they drifted — different clamps, different guards,
one of them (forgetting's fast band) missing the backwards-clock clamp its own docstring promised.
Written once, the exponent is correct everywhere and the `scale` that goes into it is the one the
aperture measured, never a second hand-rolled copy.

WHY THE LAW LIVES IN BEAM
-------------------------
The kernel is `exp` — arithmetic. What makes it an entroptics quantity is its PARAMETER: `scale` is
a correlation length / decay rate, and those are read off the instrument (`optics.correlation_length`,
`optics.fit_dynamics(...).rates()`), never chosen. Keeping the law beside the measurement is what
lets a call site write `law.attenuate(d, length=optics.correlation_length(frame))` — measured
constant, single-sourced kernel, no bare `math.exp` anywhere downstream.

Every entry clamps the travelled quantity at 0 (a negative distance / a backwards clock may never
AMPLIFY — `exp(-x/s) <= 1` is the whole point) and keeps `scale` strictly positive (a zero scale is
instantaneous total loss, a singularity, not a physics). Pure and stdlib+numpy only, so the leaf and
the server apply the identical law.

⚠ MOVED FROM `beam.law` TO PRISM ON 2026-07-31, for the same reason `vector` was. These are KERNELS
— exponential survival, attenuation, cooling — not measurements. beam measures signals and applies
these; mantle's demand decay applies the same ones. The declared layering says mantle may reach only
origin and prism, and beam and mantle are siblings, so a kernel both use has to sit below both.

⚠ IT NEEDS numpy, so it ships in the `vector` extra, NOT prism's dependency-free contract core.

This move deleted a second decay kernel: `mantle/mesh/demand.py` carried
`math.exp(-dt / tau)` behind `except ImportError` with the comment "identical kernel; only if beam
is unavailable". Identical today is not identical after the next edit to `cool`, and the divergence
would have shown up only on hosts where the import failed.
"""
from __future__ import annotations

import math
from typing import Union

import numpy as np

Number = Union[float, int, np.ndarray]


def _survive(x: Number, scale: float) -> Number:
    """`exp(-x/scale)` — the surviving fraction after `x`, at correlation scale `scale`.

    `x` clamped at 0 (no amplification from a negative travel). Scalar in, scalar out; array in,
    array out, so the same law screens a single distance or a whole field.

    ⛔ `scale` WAS CLAMPED WITH `max(1e-12, ...)`. That is a typed constant standing in the middle of
    the one attenuation law the whole system decays through, and it did not merely guard — it
    ANSWERED. A caller handing in `scale = 0` got `exp(-x/1e-12)`, a number produced by the guard
    rather than by the physics, and the guard's value was the only thing that set it.
    [John, 2026-08-01: *"if you write `ln(1/eps)`, `eps` must be MEASURED"*.]

    ⭐ THE LIMIT IS EXACT, SO NOTHING HAS TO BE CHOSEN. As `scale → 0⁺` the survival `exp(-x/scale)`
    tends to 0 for every `x > 0` and to 1 at `x = 0` — the module's own documented physics
    ("instantaneous total loss"), evaluated instead of approximated. A non-positive scale now
    returns that limit exactly, and no literal appears anywhere in the law."""
    s = float(scale)
    if isinstance(x, np.ndarray):
        d = np.maximum(0.0, x.astype(float))
        if not (s > 0.0):
            return np.where(d > 0.0, 0.0, 1.0)      # the scale -> 0+ limit, exactly
        return np.exp(-d / s)
    d = max(0.0, float(x))
    if not (s > 0.0):
        return 0.0 if d > 0.0 else 1.0              # the scale -> 0+ limit, exactly
    return math.exp(-d / s)


def attenuate(distance: Number, *, length: float) -> Number:
    """The screened propagator: the fraction of energy that reaches across `distance` at correlation
    length `length`. `length` is `xi` — read it from `optics.correlation_length`, never choose it.
    `exp(-distance/length)`, 1.0 at zero separation and decaying with distance."""
    return _survive(distance, length)


def cool(dt: Number, *, tau: float) -> Number:
    """Temporal decay: the fraction of a stock that survives `dt` frames at decay time `tau` — the
    2nd law read as cooling. `tau` is a decay time; read it from `optics.fit_dynamics(...).rates()`
    where a trajectory exists. Identical kernel to `attenuate`, named for the time domain so a call
    site says what it means (`cool(dt, tau=...)` vs `attenuate(d, length=...)`)."""
    return _survive(dt, tau)


def similarity(distance: Number) -> Number:
    """Coupling from a meaning-distance: `exp(-distance)` — 1.0 identical, decaying with distance.
    `attenuate` with the natural unit length, so a distance already expressed in nats maps straight
    to a [0, 1] coupling without a second scale to choose."""
    return _survive(distance, 1.0)


def cooled_integral(stock: float, dt: float, *, tau: float) -> float:
    """The area under one decay segment, `∫₀^dt stock·exp(-t/tau) dt = stock·tau·(1 − exp(-dt/tau))`
    — the value REALISED by holding `stock` for `dt` frames (demurrage's settlement basis). Converges
    to `stock·tau` as `dt→∞`, so a single deposit's lifetime payout is finite: value is conserved,
    not conjured. `dt` clamped ≥ 0, `stock` floored at 0.

    ⛔ `tau` WAS CLAMPED WITH `max(1e-12, ...)`, which silently made a zero-tau stock earn
    `stock·1e-12` instead of nothing. The limit is exact and needs no constant: as `tau → 0⁺` the
    area under an instantaneously-decaying stock is 0."""
    t = float(tau)
    s = max(0.0, float(stock))
    d = max(0.0, float(dt))
    if not (t > 0.0):
        return 0.0                                   # tau -> 0+ : no area under an instant decay
    return s * t * (1.0 - math.exp(-d / t))


def settle_time(floor: float, *, tau: float) -> float:
    """The inverse of `cool`: how many frames until a unit stock decays to `floor` at time `tau`,
    `tau·ln(1/floor)`. The deterministic crossing forgetting uses to time consolidation without
    recording when someone happened to look. `floor` in (0, 1].

    ⛔ THIS WAS THE WORST OF THE FOUR CLAMPS, BECAUSE IT PUT A TYPED EPSILON INSIDE A HORIZON.
    `f = min(1.0, max(1e-12, floor))` meant `settle_time(floor=0)` returned `tau·ln(1e12)` =
    **27.63·tau** — a horizon whose entire magnitude came from the guard's literal, presented as a
    derived crossing time. [John, 2026-08-01: *"I shipped exactly that error today using machine
    epsilon as ε in a horizon; the honest ε was the frame's measured noise floor."*] This is that
    error, standing in `prism.law` since the module was written.

    ⭐ THE LIMIT IS EXACT: a stock decaying exponentially never reaches zero, so the time to reach a
    floor of zero is INFINITE. `inf` is the honest answer and it is also the safe one — a caller
    cannot mistake it for a schedulable time the way it could mistake 27.63·tau. A non-positive tau
    (instantaneous decay) crosses any floor below 1 immediately, which is 0."""
    t = float(tau)
    f = min(1.0, float(floor))
    if not (t > 0.0):
        return 0.0                                   # tau -> 0+ : the floor is crossed at once
    if not (f > 0.0):
        return float("inf")                          # an exponential never reaches zero
    return t * math.log(1.0 / f)


__all__ = ["attenuate", "cool", "similarity", "cooled_integral", "settle_time"]
