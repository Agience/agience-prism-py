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

Gated by `EMBER_ADAPTIVE_MODE` (`off` | `on` | `shadow`). The default is `on` — see `_DEFAULT_MODE`
and the measurement above it. `off` makes the serve path use its baseline
(`content_search._knee`) byte-for-byte. `shadow` serves the
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
numpy-and-aperture package stays behind that slot. A full node registers the optics module as the
process default, so a caller that passes nothing gets an answer; an empty slot lands where an
unreadable frame lands, on `None` and then the baseline.
"""
from __future__ import annotations

import os
from typing import Optional, Sequence


#: The default is `on`: the instrument reads the cut, and a host without one falls back on its own.
#:
#: It was `off` while the baseline was the only measured path. Measured against it on the live
#: 676,225-synset corpus, over the reach-ranked answer sets `sage.content_search` produces:
#:
#:     question                                 _knee   instrument
#:     what is a black hole                       213           15
#:     what is machine learning                   227           11
#:     difference between weather and climate     204            8
#:     what is a glacier                           48           11
#:     what are the planets                        72            8
#:     what is photosynthesis                       3           11
#:
#: `_knee` is a proportional-drop rule over a score column, and on a reach-ranked series it has no
#: split to find three times in nine — returning the WHOLE set, which is the same as no cut at all.
#: The instrument reads the candidates' own coordinates instead of their scores, so it answers how
#: many distinguishable things were reached; across those queries it lands between 7 and 15 rather
#: than between 3 and 227.
#:
#: Turning it on costs nothing where there is no instrument: `cut` returns `None` — its word for
#: "defer" — and the caller keeps `_knee`. That is the same path a reduced install already takes,
#: so the default changes what a full node does and leaves an embedded one exactly as it was.
_DEFAULT_MODE = "on"


def mode() -> str:
    m = (os.getenv("EMBER_ADAPTIVE_MODE") or _DEFAULT_MODE).strip().lower()
    return m if m in ("off", "on", "shadow") else _DEFAULT_MODE


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

    The read goes through the injected `read` contract rather than calling the aperture directly
    directly. The optics wrapper exists because `read()`/`Screen()` enter past the streaming front
    door and apply the entropy fold guard the library documents as destroying a sparse carrier —
    measured at 256 feature channels folded to F_eff = 1 and reported as `K_signal = 1`, which at the
    call site looks the same as "there is one real mode". Ontology coordinates are sparse, so every
    aperture read goes through the wrapper.

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
    and the number of spots on a line is a different question, and a synthesised frame would be a
    reading nobody took.

    A real frame is supplied by `sage/content_search.py`, which stacks each reached candidate's
    dense Jiang-Conrath coordinate in reach order and passes it through `_relevance_cut`. Measured
    through that path, "photosynthesis" reads 1 and "cats and dogs" reads 2. What gates the read is
    `EMBER_ADAPTIVE_MODE`, which defaults to `on` — see `_DEFAULT_MODE`.

    That frame is built from coordinates the geometry can place, so a ranking of ordinary documents
    — which have no synset names — still yields none, and the cut falls to its baseline there.
    `mantle.search.beacon.cut.screen_frame` is the other half: the query-relative
    multi-head screen `W[item, head]`, each candidate's per-head cosine to the query, built from
    embeddings and needing no names at all. It is reachable and deliberately not wired to a live
    caller, because it costs an embeddings lookup per candidate and whether that is worth paying is
    a measurement on a corpus rather than an argument.

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
            # warrants; returning `n` would report "keep everything" as a derived decision. This
            # branch is reached when `frame` was None or unreadable — a 1-D score column is a line,
            # not a frame, and the number of spots on a line is a different question. It is NOT the
            # normal path: `content_search` hands this read the reached candidates' own JC
            # coordinates, and that frame resolves above.
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
