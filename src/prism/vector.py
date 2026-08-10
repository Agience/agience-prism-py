"""Shared vector geometry — the L2 primitives the Agience repos use, defined in one place.

Zero is handled here, once: a zero vector normalises to zero — never a divide-by-zero, never a NaN.
A caller that wants to skip zero vectors tests `norm(...)` first rather than re-deriving the guard.
dtype is preserved (float32 in → float32 out).

"""
from __future__ import annotations

import numpy as np



def norm(v, *, axis=None):
    """L2 magnitude — the length, not the direction. `axis=None` (default) is the whole-array norm
    (Frobenius for a matrix, L2 for a vector), matching a bare `np.linalg.norm(v)`; pass `axis=1` for
    per-row lengths."""
    return np.linalg.norm(np.asarray(v), axis=axis)


def unit(v, *, axis=-1):
    """L2-normalise to the unit sphere along `axis`, zero-safe. A zero vector stays exactly zero —
    it has no direction, so none is invented; dtype is preserved. `axis=-1` (default) normalises
    each row of a stack / the whole of a 1-D vector; `axis=None` normalises the whole array by its
    Frobenius norm (for a matrix)."""
    a = np.asarray(v)
    if axis is None:
        n = float(np.linalg.norm(a))
        return a if n == 0.0 else a / n
    n = np.linalg.norm(a, axis=axis, keepdims=True)
    # Divide only where there is a direction; leave the zero rows exactly zero.
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
