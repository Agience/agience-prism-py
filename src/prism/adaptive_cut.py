"""Adaptive relevance cut — how many results to keep, derived from the relevance signal itself.

No models, no embeddings, no trained anything. The input is the 1-D sequence of retrieval relevances
(e.g. BM25 magnitudes) the caller already has; the output is where that sequence stops being signal.
Two model-free reads, each doing what it is good at:

  * The aperture gates whether there is coherent signal. `resolvable` on the relevance column derives
    a noise floor (Marchenko–Pastur, parameter-free) and reports `K_signal`: 0 = the values are
    indistinguishable from noise (nothing separates, so keep the whole set), 1 = there is structure
    above the floor. This reads the relevances themselves — no vector space, no embedding.
  * The scale-invariant largest relative gap says where the break is — the split that best separates
    the series. No threshold, no constant: it is an argmax over a ratio, so it is invariant to the
    query's overall score scale.

Measured: this composition matches the hand-rolled `_knee` on cluster/dominant/smooth shapes and
fixes the cases each gets wrong alone — the noise floor alone keeps all of `[50,2,2,2,2,2]` (a lone
extreme value drags the absolute floor down); a gap rule with a fixed `2.0` guard is crude on gentle
decays. Composed, the pair needs no constant at all.

Gated by `EMBER_ADAPTIVE_MODE` (`off` | `on` | `shadow`), default `off` — the serve path uses its
baseline (`content_search._knee`) byte-for-byte until the switch is flipped. `shadow` serves the
baseline unchanged and records the adaptive pick alongside it (label-free A/B on real queries, sink
`EMBER_ADAPTIVE_SHADOW_LOG`). Falls back to the baseline when the instrument is unavailable or the
pool is too small to carry structure. Never raises.

This module is part of prism's dependency-free base, beside `resolution`. `mode()` reads an env var,
`record_shadow()` appends a JSON line, and `cut()` defers (returns `None`) whenever the instrument is
absent. Every heavy import is function-local, so the module imports on stdlib alone and
`is_available()` reports False there. The behaviour is identical across embodiments, which is what
makes it code rather than a protocol member.

`resolvable` is a declared member of the `read` contract (`instrument.READ_MEMBERS`), so the three
reaches for it resolve the injected slot; prism is the published, dependency-free SDK and the private
numpy-and-entroptics package stays behind that slot. A full node registers the optics module as the
process default, so a caller that passes nothing gets an answer; an empty slot lands where an
unreadable frame lands, on `None` and then the baseline.
"""
from __future__ import annotations

import os
from typing import Optional, Sequence


def mode() -> str:
    m = (os.getenv("EMBER_ADAPTIVE_MODE") or "off").strip().lower()
    return m if m in ("off", "on", "shadow") else "off"


def _resolvable():
    """The injected `read` contract's `resolvable`, or `None` if this host has no instrument.

    `None` here is an observation. Every caller below has a documented answer for "the aperture had
    no reading to give" — defer to the baseline — and an empty slot is that same fact arriving one
    step earlier. A module with nothing to defer to lets `InstrumentRequired` propagate instead (see
    `resolution._read_member`)."""
    from .instrument import get_default, require
    slot = get_default()
    if slot is None:
        return None
    try:
        return require(slot, "resolvable", contract="read", at="adaptive_cut")
    except Exception:
        return None


def is_available() -> bool:
    """Can this host take the read at all? It needs an instrument that fills `resolvable`, and numpy
    — the array the read is handed is built here, so numpy is as necessary as the aperture."""
    try:
        import numpy  # noqa: F401
    except Exception:
        return False
    return _resolvable() is not None


def _k_signal(rel) -> int:
    """The resolved-mode count above the aperture's own noise floor. 0 = indistinguishable from
    noise; >=1 = coherent structure; `None` when the aperture has no reading for this frame.

    The read goes through the injected `read` contract rather than calling `entroptics.read()`
    directly. The optics wrapper exists because `read()`/`Screen()` enter past the streaming front
    door and apply the entropy fold guard the library documents as destroying a sparse carrier —
    measured at 256 feature channels folded to F_eff = 1 and reported as `K_signal = 1`, which at the
    call site looks the same as "there is one real mode". Ontology coordinates are sparse, so every
    entroptics read goes through the wrapper.

    A 1-D column is not a frame. `rel.reshape(-1, 1)` asks the aperture about a line, and the wrapper
    has no reading below F = 2, so `None` comes back and the caller keeps its baseline."""
    resolvable = _resolvable()
    n = len(list(rel))
    if n <= 1:
        return 1 if n == 1 else 0
    import numpy as np
    k = resolvable(np.asarray(rel, float).reshape(-1, 1))
    return int(k) if k is not None else None


def _largest_relative_gap(rel: Sequence[float]) -> int:
    """Where the relevance breaks — the split that best separates the series. The name is this
    module's documented composition point.

    `prism.resolution.partition` is the one implementation: maximum between-class variance,
    non-parametric, no constant. It is a global statistic, so a single noisy adjacent pair does not
    move it, and it returns the explained-variance fraction alongside the cut, which makes "there was
    nothing to separate" expressible. The composition: the aperture answers whether via `K_signal`;
    this answers where."""
    from .resolution import signal_end
    return signal_end(rel)


def cut(scores: Sequence[float], *, frame=None) -> Optional[int]:
    """The derived span count. Returns `None` to mean "defer to the caller's baseline".

    `scores` are raw retrieval scores (BM25: negative, most-negative = best, best-first).

    `frame` is the ordered (T, F) evidence behind those scores — the candidates' own features, in
    score order. It is what the aperture reads, and with it this becomes the instrument's `k_signal`
    rather than an approximation of it. Without it the read defers, because a score column is a line
    and the number of spots on a line is a different question. No caller here supplies a real frame
    yet; a synthesised one would be a reading nobody took.

    Never raises."""
    rel = [-float(x) for x in scores]     # BM25 is negative; relevance is higher = better
    n = len(rel)
    if n <= 1:
        return n                          # nothing to cut: a set of one has no split, at any width
    if not is_available():
        return None                       # no instrument present — defer, never guess a cut
    try:
        if frame is not None:
            resolvable = _resolvable()
            k_f = resolvable(frame)
            if k_f is not None:
                return max(1, min(int(k_f), n)) if k_f > 0 else n
        k = _k_signal(rel)
        if k is None:
            # The aperture had no reading for this frame, so there is nothing to cut on. `None` is
            # this module's word for "defer to the baseline", and deferring is what an unread frame
            # warrants; returning `n` would report "keep everything" as a derived decision. The frame
            # is unread because a 1-D score column is a line, not a frame — the number of spots on a
            # line is a different question. This read has no caller that hands it a real (T, F) frame,
            # the candidates' own features in score order.
            return None
        if k == 0:                        # read, and indistinguishable from noise → keep all
            return n
        return _largest_relative_gap(rel)
    except Exception:
        return None


def record_shadow(query: Optional[str], scores: Sequence[float], baseline: int, adaptive: Optional[int]) -> None:
    """Append one label-free A/B record (baseline vs adaptive) to `EMBER_ADAPTIVE_SHADOW_LOG`, if set.
    Best-effort and silent — shadow measurement must never affect the serve path."""
    path = os.getenv("EMBER_ADAPTIVE_SHADOW_LOG")
    if not path:
        return
    import json
    import time
    rec = {
        "ts": time.time(),
        "component": "content-cut",
        "query": query,
        "n": len(list(scores)),
        "baseline_knee": baseline,
        "adaptive": adaptive,
        "agree": baseline == adaptive,
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


__all__ = ["mode", "is_available", "cut", "record_shadow"]
