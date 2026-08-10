"""Rounding — the band a float sum can be wrong by, from the arithmetic that was actually performed.

One law, single-sourced. This is arithmetic with no domain, so it lives in one place and every caller
reads it from here: two copies of one arithmetic required to agree exactly are two chances to
disagree tomorrow. It is validated against direct summation across dtypes (float16/32/64/longdouble/
int/complex), a range of frame shapes, magnitudes and split counts, and negative/NaN/inf energies.

It sits in the dependency-free base, and the placement is load-bearing. `prism.conservation` sits
behind `[wire]` because it needs numpy; `mantle`'s beacon runs on numpy alone and carries no heavy
edge. A component that must install prism behind an optional extra still needs this law, so the law
itself carries no such extra: it is stdlib-only, beside `prism.resolution`; reading a dtype's epsilon
is numpy vocabulary and stays with the caller that has a dtype.

═══════════════════════════════════════════════════════════════════════════════════════════════
Which error this models: accumulation
═══════════════════════════════════════════════════════════════════════════════════════════════

**This bound is valid when the terms summed are non-negative.** Recursively summing `n` non-negative
terms carries a forward error of at most `(n−1)·ε·Σ`; the partial sums increase monotonically, so
catastrophic cancellation cannot arise and the accumulated `Σ` is the right scale. Its callers sum
`‖·‖²` — squared magnitudes — which is what earns them the model.

A derivation can be exactly as wrong as a constant if it models the wrong error. Counting terms alone
does not distinguish accumulation from cancellation: a tie-break that scales with `n` terms is correct
for a sum of non-negative magnitudes and wrong for a sum that subtracts nearly-equal quantities, since
the two have different error scales.

Hand this function a sum with a subtraction in it and it returns a number too small by however many
orders of magnitude the cancellation cost. The discriminator, in one question: *can any partial sum
be smaller than the one before it?* If yes, the scale is the granularity of the inputs
(`ε·max|term|`) rather than of the total — see `prism.resolution.separability`, which derives that
case, and `prism.minting.conservation_tolerance`, which needs both because it sums and then
subtracts.

The band tracks its inputs: more operations → wider; larger total → wider; float32 → wider than
float64. Asserted in `tests/test_rounding.py`, which is what makes "derived" a measurement rather
than a claim.
"""
from __future__ import annotations

__all__ = ["accumulated_rounding", "split_walk_operations", "split_walk_rounding"]


def accumulated_rounding(n_operations: int, total: float, eps: float) -> float:
    """The law: `ε · Σ · n` — the band a sum of `n_operations` non-negative terms totalling `total`
    can be wrong by at machine epsilon `eps`.

    `eps` is the caller's to supply because it belongs to the caller's dtype — a float32 frame earns
    a wider band than a float64 one, and this module has no dtype to read. It is stdlib, and the
    dependency-free base install carries no numpy.

    A negative `total` clamps to zero. Every caller's `total` is an energy — a sum of squares,
    non-negative by construction — so a negative one means the caller measured a different quantity
    from the one this bound describes. A zero band admits no difference as noise, so the caller's
    check fails at that point rather than receiving slack derived from an impossible input. `nan`
    propagates for the same reason: a band is a finite width."""
    return float(eps) * max(float(total), 0.0) * float(int(n_operations))


def split_walk_operations(n_elements: int, *, splits: int = 1) -> int:
    """How many float operations a splitting walk performs — the `n` for `accumulated_rounding`.

    A walk takes an incident frame of `n_elements` elements and splits it `splits` times; each split
    produces an absorbed and a transmitted frame of the same size, and the verdict sums the energies
    of all of them. So the count is two parts, both counted rather than estimated:

        additions   `1 + 3·splits`                  the incident energy, then per split: absorbed +
                                                    transmitted + the running total
        products    `n_elements · (1 + 2·splits)`   every multiply each `‖·‖²` performed — the
                                                    incident frame once, then two frames per split

    `splits` floors at 1: a walk that split nothing still summed one frame's energy, and a zero
    operation count would claim the arithmetic was exact. Its own count is exact, not bounded — the
    caller knows how many hops it took."""
    n = max(1, int(splits))
    return (1 + 3 * n) + int(n_elements) * (1 + 2 * n)


def split_walk_rounding(n_elements: int, energy: float, eps: float, *, splits: int = 1) -> float:
    """The band for a splitting walk: `accumulated_rounding` over `split_walk_operations`.

    `ember.optics._float_noise` and `mantle/search/beacon/instrument.py::_float_noise` both call this
    and supply the one line it has no vocabulary for — reading `eps` off the frame's own dtype, which
    is numpy."""
    return accumulated_rounding(split_walk_operations(n_elements, splits=splits), energy, eps)
