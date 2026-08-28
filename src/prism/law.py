"""The decay / attenuation law the aperture governs — applied, in one place.

`ember.optics` measures: it reads a length or a rate off an ordered frame through the aperture
(`correlation_length`, `diffraction`, `decay_profile`, `fit_dynamics`). This module applies the
physics those readings parameterise. There is exactly one such physics in this codebase, and every
entry below is `exp(-x / scale)` — the fraction of a quantity that survives after travelling `x` at
a correlation scale `scale`:

    attenuate(distance, length=xi)  the screened propagator — ember.ontology.match,
                                    prism.propagation
    cool(dt, tau=tau)               temporal decay, the 2nd law as accounting — prism.demurrage,
                                    mantle.mesh.demand
    similarity(distance)            coupling from a meaning-distance — ember.signal.forgetting,
                                    ember.ontology.activation
    cooled_integral / settle_time   the area under one decay segment, and the inverse crossing

The `scale` that goes in is one the CALLER measured, in the space the distance was measured in.
That is a real constraint, not a formality — a scale from the wrong space silently rescales every
decay:

  * ordered `(T, F)` frames -> `ember.optics.correlation_length`, or the rates off
    `ember.optics.fit_dynamics`. A decorrelation length along the row order of a frame.
  * ontology / taxonomy distances -> `ember.ontology.match.xi()`. A length in Jiang-Conrath nats,
    derived from the corpus diameter.

The two are not interchangeable. A corpus's is-a structure is not a `(T, F)` frame, and
`Dynamics.rates()` returns `None` on a concept stream, so `correlation_length` has nothing to read
there. Take the scale from whichever instrument measured the distance being attenuated.

Every entry clamps the travelled quantity at 0, so `exp(-x/s) <= 1` holds for a negative distance or
a backwards clock, and keeps `scale` strictly positive (a zero scale is a singularity, handled as
its limit rather than as a physics). stdlib+numpy only, so the leaf and the server apply the
identical law.
"""
from __future__ import annotations

import math
from typing import Union

import numpy as np

Number = Union[float, int, np.ndarray]


def _survive(x: Number, scale: float) -> Number:
    """`exp(-x/scale)` — the surviving fraction after `x`, at correlation scale `scale`.

    `x` clamped at 0, so a negative travel survives whole rather than amplifying. Scalar in, scalar
    out; array in, array out, so the same law screens a single distance or a whole field.

    A non-positive `scale` is taken as the limit `scale -> 0+`: anything that travelled survives at
    0, a zero travel survives at 1. The code returns that limit exactly, so no epsilon literal
    appears anywhere in the law."""
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
    length `length`. `length` is `xi` — read it from `ember.optics.correlation_length` rather than
    choosing it. `exp(-distance/length)`, 1.0 at zero separation and decaying with distance."""
    return _survive(distance, length)


def cool(dt: Number, *, tau: float) -> Number:
    """Temporal decay: the fraction of a stock that survives `dt` frames at decay time `tau` — the
    2nd law read as cooling. `tau` is a decay time; read it from the rates off
    `ember.optics.fit_dynamics` where a trajectory exists. Identical kernel to `attenuate`, named for
    the time domain so a call site says what it means (`cool(dt, tau=...)` vs
    `attenuate(d, length=...)`)."""
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
    not conjured. `dt` clamped ≥ 0, `stock` floored at 0. At `tau -> 0+` the area under an
    instantaneously-decaying stock is 0."""
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

    At `tau -> 0+` decay is instantaneous and any floor below 1 is crossed at once, which is 0. A
    floor of 0 is never reached by an exponential, which is `inf`."""
    t = float(tau)
    f = min(1.0, float(floor))
    if not (t > 0.0):
        return 0.0                                   # tau -> 0+ : the floor is crossed at once
    if not (f > 0.0):
        return float("inf")                          # an exponential never reaches zero
    return t * math.log(1.0 / f)


__all__ = ["attenuate", "cool", "similarity", "cooled_integral", "settle_time"]
