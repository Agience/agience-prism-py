"""Shared vector geometry — the L2 primitives the Agience repos use, defined ONCE.

WHY THESE ARE IN BEAM AND NOT ENTROPTICS
----------------------------------------
entroptics measures the STRUCTURE of an ordered frame (resolved modes, coherence, decay); these are
elementwise arithmetic on a single coordinate — a length, a direction, an angle between two vectors.
That is not optics, so it does not belong in the instrument (which stays optics-focused). But it IS
foundational and shared: `unit` / `norm` / `cosine` / `distance` were hand-rolled in ~a dozen places
(`ember.geometry` / `embed` / `screen` / `cache`, `mantle.search.engine` / `reconciler`,
`mantle.search.anchors`), each a bare `np.linalg.norm` with its own zero-guard, dtype cast, and axis. That is
the duplication this module removes: a unit vector, a cosine, and a distance now mean the same thing
and are guarded the same way everywhere, in the Beam tier that sits between entroptics and Agience.

Zero is handled ONCE, here: a zero vector normalises to zero (never a divide-by-zero, never a NaN),
and a caller that wants to SKIP zero vectors tests `norm(...)` first rather than each re-deriving the
guard. dtype is preserved (float32 in → float32 out).

⚠ MOVED FROM `beam.vector` TO PRISM ON 2026-07-31. Unit vectors, cosine and distance are PRIMITIVES,
not measurements — beam measures signals, this normalises numbers. `agience-mantle`'s shard cache
needs `unit()` for its local cosine, and the declared layering says mantle may reach origin and
prism only; beam and mantle are siblings, so a primitive both use has to sit below both.

⚠ IT NEEDS numpy, SO IT IS NOT IN PRISM'S DEPENDENCY-FREE CONTRACT CORE. Install it with the
`vector` extra. That keeps the promise `prism/__init__.py` makes — a bare `pip install agience-prism`
stays zero-dependency — while giving the two consumers one implementation instead of two.
"""
from __future__ import annotations

import numpy as np

# ⛔ `_EPS = 1e-12` IS DELETED. It was the divisor substituted for a zero norm, so a zero vector's
# direction was `0 / 1e-12` — a number the guard produced, not the data. It also sat BELOW float32
# resolution while claiming to preserve dtype, so on a float32 stack it guarded nothing it was
# supposed to guard and the two dtypes behaved differently for the same input.
#
# ⭐ THE STATEMENT IS EXACT AND NEEDS NO LEVEL: A ZERO VECTOR HAS NO DIRECTION. So `unit` returns
# the zero vector unchanged where the norm is zero, and normalises where it is not — which is what
# every call site already believed it did ("a zero vector stays zero"). `cosine` then reads 0 for a
# zero vector, as before, because a zero direction couples to nothing. Nothing is clamped, nothing
# is divided by a substitute, and the behaviour no longer depends on a literal's size relative to
# the dtype's resolution.


def norm(v, *, axis=None):
    """L2 magnitude — the length, not the direction. `axis=None` (default) is the whole-array norm
    (Frobenius for a matrix, L2 for a vector), matching a bare `np.linalg.norm(v)`; pass `axis=1` for
    per-row lengths."""
    return np.linalg.norm(np.asarray(v), axis=axis)


def unit(v, *, axis=-1):
    """L2-normalise to the unit sphere along `axis`, zero-safe. A zero vector stays zero (EXACTLY —
    it has no direction, so none is invented); dtype is preserved. `axis=-1` (default) normalises
    each row of a stack / the whole of a 1-D vector; `axis=None` normalises the whole array by its
    Frobenius norm (for a matrix)."""
    a = np.asarray(v)
    if axis is None:
        n = float(np.linalg.norm(a))
        return a if n == 0.0 else a / n
    n = np.linalg.norm(a, axis=axis, keepdims=True)
    # Divide only where there IS a direction; leave the zero rows exactly zero.
    return np.divide(a, n, out=np.zeros_like(a, dtype=a.dtype), where=(n > 0.0))


def cosine(a, b, *, axis=-1):
    """Cosine similarity — the coupling between two directions, `unit(a) · unit(b)` in [-1, 1].
    Zero-safe (a zero vector has no direction, so it couples to nothing → exactly 0)."""
    ua = unit(a, axis=axis)
    ub = unit(b, axis=axis)
    return np.sum(ua * ub, axis=axis)


def distance(a, b, *, axis=None):
    """Euclidean distance `‖a − b‖` (Frobenius for matrices, with `axis=None`)."""
    return np.linalg.norm(np.asarray(a) - np.asarray(b), axis=axis)


__all__ = ["norm", "unit", "cosine", "distance"]
