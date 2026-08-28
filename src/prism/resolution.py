"""Resolution — where a measurement stops being able to tell things apart.

One question recurs across the whole flow, wearing a different name each time:

    how many results are relevant?          (`content_search._knee`)
    how many probes does a query need?      (`anchors.routing.nprobe`)
    when are two documents the same thing?  (`minhash` / `near_duplicates` thresholds)
    how many senses of a word fire?         (`match` need width)
    how far does a signal travel?           (`spread`, `max_depth`)

They are all one question: where does this instrument stop resolving? The data carries the answer,
so nothing here is a chosen number.

Two forms, depending on whether the measurement has sampling error:

  * A sampled estimate has a standard error, and two readings closer together than that error are
    one reading. `estimator_limit` is that boundary — MinHash over `k` hashes estimates Jaccard as a
    binomial proportion, so `se = sqrt(J(1-J)/k)` and the point where a pair stops being
    distinguishable from identical is `1 - 1/(k+1)`. Widen the instrument and the boundary tightens.

  * An exact measurement has no sampling error, so its resolution is where the data separates. That
    is `signal_end`.

How `signal_end` decides

`signal_end` asks which split best separates the series into two groups, and answers with maximum
between-class variance — Otsu's criterion: non-parametric, no constant, no assumed distribution. For
every possible cut it computes how much of the total variance that cut explains, and takes the best.
This is a global statistic, so it is robust to a single noisy adjacent pair and it can decline to
cut at all.

The strength of a cut only means something compared against what no structure would give.
Between-class variance will bisect a featureless ramp and report η² ≈ 0.75, which is a property of
the statistic rather than evidence of structure. `_null_separability` obtains the baseline by
running the identical calculation on a uniform ramp of the same length, so changing the statistic
moves the baseline with it. Measured across the range:

    flat             eta2 0.0000  null 0.7576  ->  keep all
    uniform ramp     eta2 0.8000  null 0.8000  ->  keep all   (exactly the null: no structure)
    smooth decay 200 eta2 0.7500  null 0.7500  ->  keep all
    real cliff       eta2 0.9749  null 0.7500  ->  cut at 3
    one dominant     eta2 0.9997  null 0.8000  ->  cut at 1
    two clean groups eta2 1.0000  null 0.7505  ->  cut at 20

A smooth decay is the common case, which is why the null baseline matters. A real near-duplicate
score distribution typically decays smoothly across its candidate range with no valley in it, so
`signal_end` keeps all rather than reporting a boundary that is not there.

Pure and stdlib-only, with no numpy, so every component can hold the same answer — including the
ones that must stay self-contained. It is part of prism's dependency-free base install rather than
an extra, which `tests/test_contract_install_is_pure.py` pins by importing it in a subprocess with
the heavy packages unimportable.
"""
from __future__ import annotations

import math
import sys
from typing import List, Sequence, Tuple


def _read_member(member: str, *, at: str):
    """The named member of the injected `read` contract, or raise.

    The one door onto the instrument from this module and from `adaptive_cut`. It is a door rather
    than an import because the base install is dependency-free, so this package does not import
    the aperture. `instrument.require` is the same door `frames` and `reach` use, so an empty or
    partial slot raises `InstrumentRequired` — one exception type, one message, naming the contract,
    the member and the operation.

    Both call sites catch it, because both have a derived answer that needs no instrument at all
    (Otsu against its own computed null; the baseline cut), so "no instrument here" is a fact they
    act on. A module with no fallback lets it propagate."""
    from .instrument import get_default, require
    return require(get_default(), member, contract="read", at=at)


def _sorted_desc(scores: Sequence[float], descending: bool) -> List[float]:
    vals = [float(s) for s in scores]
    return vals if descending else sorted(vals, reverse=True)


def partition(scores: Sequence[float], *, descending: bool = True) -> Tuple[int, float]:
    """`(cut, separability)` — the split that best separates the series, and how much it explains.

    Maximum between-class variance over every split point (Otsu). `cut` is a count: `scores[:cut]`
    is the leading group. `separability` is the correlation ratio η² = between/total ∈ [0,1]:

        0.0   no split explains anything — the series is one population (uniform, or noise)
        →1.0  the two groups are cleanly apart

    Both are returned together deliberately. A cut without its separability is exactly the shape of
    every constant this module replaces: a confident answer with no way to tell whether it means
    anything."""
    vals = _sorted_desc(scores, descending)
    n = len(vals)
    if n <= 1:
        return n, 0.0
    total = sum(vals)
    mean = total / n
    var_total = sum((v - mean) ** 2 for v in vals)
    if var_total <= 0.0:
        return n, 0.0                      # every reading identical: nothing to separate
    best_between, best_cut = -1.0, n
    run = 0.0
    for i in range(1, n):                  # split after i readings
        run += vals[i - 1]
        m1 = run / i
        m2 = (total - run) / (n - i)
        # between-class variance: how far the two group means sit from the overall mean
        between = i * (m1 - mean) ** 2 + (n - i) * (m2 - mean) ** 2
        if between > best_between:
            best_between, best_cut = between, i
    return best_cut, max(0.0, min(1.0, best_between / var_total))


def _null_separability(n: int) -> float:
    """What `partition` reports for a series with no structure — a uniform ramp of `n` readings.

    The number that makes "whether" answerable, computed rather than chosen. Between-class variance
    bisects a featureless ramp and reports a high explained fraction (~0.75 for large n), which is a
    property of the statistic rather than evidence of structure. Comparing against this baseline —
    the identical calculation on the null series of the same length — is what gives the reading
    meaning. Change the calculation and the baseline follows it automatically."""
    if n <= 1:
        return 0.0
    ramp = [float(n - i) for i in range(n)]
    return partition(ramp)[1]


def separated(scores: Sequence[float], *, descending: bool = True) -> bool:
    """Does this series separate into two groups at all, beyond what featureless data would show?

    The `whether` that precedes the `where`. A series that does not separate is not cut, because a
    cut there would return a confident number computed from nothing."""
    vals = _sorted_desc(scores, descending)
    if len(vals) <= 1:
        return False
    return partition(vals)[1] > _null_separability(len(vals)) + _tie_break(vals)


def _tie_break(vals: Sequence[float]) -> float:
    """How far apart two eta^2 readings must be before the difference is a measurement.

    The error here is cancellation rather than accumulation, so the bound is derived from the
    conditioning of the sum rather than from a term count. `partition` sums `(v - mean)**2`. On a
    series like `[1.0, 0.999, 0.998]` the values and the mean are all near 1.0 while their
    differences are near 1e-3, so each deviation is a subtraction of nearly-equal quantities: its
    absolute error is set by the granularity of the inputs, `eps * max|v|`, independent of how small
    the deviation itself is. The null series (`[n, n-1, ..., 1]`) is perfectly conditioned by
    comparison, so the two eta^2 do not carry the same error and it does not cancel between them.

    (The accumulation case is `prism.rounding`, whose `n * eps` bound is valid because every term it
    sums is non-negative. The discriminator is one question: can a partial sum be smaller than the
    one before it? Here it can.)

    Propagating that granularity, with `delta = n * eps * max|v|` covering both the inputs' own
    representation and the mean's summation error:

        d(v - mean)  <=  2 * delta
        dV           <=  sum 2|v - mean| * 2 * delta  =  4 * delta * S1,   S1 = sum |v - mean|
        d(B/V)       <=  (dB + eta^2 * dV) / V  <=  (1 + eta^2) * 4 * delta * S1 / V
                     <=  8 * delta * S1 / V

    plus `n * eps` for the ratio's own summation. Every factor is a term count, a machine epsilon,
    or a quantity read off the series.

    The result is scale-invariant. `S1 * max|v| / V` is large exactly when the spread is minuscule
    beside the magnitude — the regime where doubles cannot express the difference being asked about,
    so the series is not called structured. Verified across the range: a real cliff clears this by
    ~2.2e-1 against a ~2.3e-14 floor, and `[1e-18*k]` and `[1e18*k]` read identically."""
    n = len(vals)
    mean = sum(vals) / n
    var_total = sum((v - mean) ** 2 for v in vals)
    if var_total <= 0.0:
        return 0.0
    eps = sys.float_info.epsilon
    delta = n * eps * max(abs(v) for v in vals)
    return n * eps + 8.0 * delta * sum(abs(v - mean) for v in vals) / var_total


def signal_end(scores: Sequence[float], *, descending: bool = True,
               frame=None) -> int:
    """How many leading readings are signal.

    When a frame is available, the instrument answers. `frame` is the ordered (T, F) evidence behind
    these scores — the candidates' actual features, in score order. Given one, the count is the
    `read` contract's `resolvable` (`k_signal`, the modes above the aperture's own noise floor),
    which is the measurement the Otsu split approximates.

    This is the one place this module reaches the instrument, and it does so through the injected
    slot rather than by importing the aperture — the same way `frames.absorb_at_tekton` reaches
    `absorb_transmit`. `resolvable` is a declared member of the `read` contract
    (`instrument.READ_MEMBERS`), and a full node registers `ember.optics` as the process default, so
    a caller that passes nothing still gets the instrument's read.

    The statistics below answer for a caller with no frame — a bare ranked list of numbers. They are
    not a second opinion: when a frame exists the instrument's read wins, because a score column is
    not a frame. An empty slot lands in the same place as an instrument with no reading to give: the
    derived Otsu statistics, which need no frame, no instrument and no constant."""
    vals = _sorted_desc(scores, descending)
    if frame is not None:
        try:
            resolvable = _read_member("resolvable", at="signal_end")
            # Only when the instrument certifies the count (§13.33); otherwise fall through to the
            # derived Otsu statistics, which need no frame and no constant.
            k = resolvable(frame, require_certain=True)
            if k is not None and 0 < k <= len(vals):
                return k
        except Exception:
            pass
    if not separated(vals):
        return len(vals)
    return partition(vals)[0]


def separability(scores: Sequence[float], *, descending: bool = True) -> float:
    """η² for the best split — the fraction of variance that split explains. 0.0 means the series
    is one population and there is nothing to cut."""
    return partition(scores, descending=descending)[1]


def estimator_limit(k: int) -> float:
    """The value at which a `k`-sample proportion estimate stops being distinguishable from 1.0.

    Solves `j + sqrt(j(1-j)/k) = 1` — the largest `j` whose one-sigma band still touches certainty.
    With `d = 1 - j`: `d² = (1-d)d/k` → `d = 1/(k+1)`, so the limit is `1 - 1/(k+1)`.

    This is the merge boundary for any sampled similarity: below it the instrument can still tell
    the pair apart, so calling them one thing is a claim the measurement does not support."""
    k = max(1, int(k))
    return 1.0 - 1.0 / (k + 1.0)


def standard_error(p: float, k: int) -> float:
    """Standard error of a proportion `p` estimated from `k` independent samples.

    The instrument's resolution at that reading: a difference smaller than this is not a difference
    it can see, whatever the decimal places suggest."""
    p = min(1.0, max(0.0, float(p)))
    return math.sqrt(p * (1.0 - p) / max(1, int(k)))


def exact_limit(union_size: int) -> float:
    """The overlap fraction at which two exact sets differ by less than one element.

    An exact measure has no sampling error; its resolution is granularity. The smallest expressible
    difference is one element out of the union, so `1 - 1/|union|` is where "similar" and
    "identical" become the same reading. Derived per pair, from the pair."""
    return 1.0 - 1.0 / max(1.0, float(union_size))


def horizon(xi: float, gap: float, *, weight: float = 1.0) -> float:
    """How far a signal of this weight propagates before it stops clearing the gap.

    A screened contribution is `weight · exp(-d/ξ)`. Setting that equal to the mass gap and solving:

        d_max = ξ · ln(weight / gap)

    That is the whole bound. Beyond it the signal is absent rather than weak, because a gap is a
    discontinuity and nothing below it propagates at all.

    This supplies every limit on a propagation, in place of a step count. A hop count measures the
    walk rather than the signal, so two hops through dense ontology and two hops through sparse
    ontology would read as the same reach. Distance is the quantity the propagator is written in.

    Both `xi` and `gap` are themselves measured off the corpus, so the horizon moves as the corpus
    does — there is no fixed number to quote here, only the two readings this function is handed.

    Returns 0.0 when the weight is already below the gap: such a signal never propagates at all."""
    xi = float(xi)
    gap = float(gap)
    weight = abs(float(weight))
    if xi <= 0.0 or gap <= 0.0 or weight < gap:
        return 0.0
    return xi * math.log(weight / gap)


def reach_limit(weight: float, gap: float) -> bool:
    """Can this contribution ever clear the gap? A screened contribution is `weight · exp(-d/ξ)`
    and `exp(-d/ξ) ≤ 1`, so a weight already below the gap cannot clear it at any distance —
    including zero. Skipping it changes no result.

    An exact statement about the propagator, in place of a budget on how many senses may fire: a
    cap discards whichever senses are ambiguous — their weight split across many meanings — while
    keeping unambiguous ones, which is a bias rather than a trim."""
    return abs(float(weight)) >= float(gap)


__all__ = ["partition", "signal_end", "separability", "separated", "estimator_limit",
           "standard_error", "exact_limit", "horizon", "reach_limit"]
