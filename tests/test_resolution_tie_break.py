"""`separated` keeps a series that has nothing in it.

The tie-break has to cover cancellation error, not accumulation error, or it misclassifies a
featureless ramp as structured. Three cases where a term-count-only bound gets this wrong:

    [1.0, 0.999, 0.998]              eta^2 - null = +2.776e-13    n*eps = 6.7e-16   ->  cut at 2
    [1.0, 0.999, 0.998, 0.997]       eta^2 - null = +1.775e-13    n*eps = 8.9e-16   ->  cut at 4->2
    [1.0 - 0.001i], n = 100          eta^2 - null = +2.542e-14    n*eps = 2.2e-14   ->  cut at 50

The error the tie-break has to cover is cancellation, not accumulation. A bound of `len(vals) * eps`
describes accumulation: both eta^2 are ratios of sums over `n` terms and lie in [0,1], so the
arithmetic's own error is bounded by `n * eps`. But `partition` sums `(v - mean)**2`, and on
`[1.0, 0.999, 0.998]` the values and the mean are all near 1.0 while their differences are near 1e-3,
so each deviation's absolute error is set by `eps * max|v|` and is unrelated to how small the
deviation is. The null series (`[n, ..., 1]`) is well conditioned, so the two eta^2 carry different
errors and nothing cancels between them.

A constant does not answer this either way. A typed `1e-12` happens to be wide enough here and is
invented; `n * eps` is derived and two to three orders of magnitude too tight. `_tie_break`
propagates the input's own representation granularity through the ratio, so every factor is a term
count, a machine epsilon, or a quantity read off the series.

Conditioning is the variable that decides the answer, so this file parameterises it rather than
pinning one example. A single case shaped like the ramp `[5.1, 5.0, 4.8, 4.8]` lands on the passing
side by luck: the residual's sign is not systematic, and at n=200 and n=1661 it comes out negative.
"""
from __future__ import annotations

import sys

import pytest

from prism.resolution import _null_separability, _tie_break, partition, separated, signal_end

EPS = sys.float_info.epsilon


#: offset / spacing. A uniform ramp is featureless at every value of this, so every row must read
#: "keep all" — the ratio only changes how badly conditioned the arithmetic is.
CONDITIONING = [0.0, 1.0, 5.0, 50.0, 1e3, 1e6, 1e9]


@pytest.mark.parametrize("offset", CONDITIONING)
@pytest.mark.parametrize("n", [3, 4, 5, 12, 50, 100, 200])
def test_a_uniform_ramp_is_never_structure_however_badly_it_is_conditioned(offset, n):
    """The gate. A uniform ramp is this module's canonical "nothing to find" case: its eta^2 is its
    own null, exactly, in real arithmetic. Adding a large constant to every element
    changes nothing about the series and everything about the float error, so an implementation that
    answers differently at `offset = 1000` is reading its own rounding as evidence."""
    vals = [offset + float(n - i) for i in range(n)]
    assert not separated(vals), (
        "a uniform ramp of %d readings offset by %g read as SEPARATED. eta^2 - null = %+.3e, "
        "tie-break = %.3e. The series has no structure at any offset; the difference is float "
        "cancellation in `(v - mean)`."
        % (n, offset, partition(vals)[1] - _null_separability(n), _tie_break(vals)))
    assert signal_end(vals) == n, "the ramp was cut"


@pytest.mark.parametrize("n", [3, 4, 5, 12, 50, 100, 200])
def test_the_exact_series_that_found_it(n):
    """The literal inputs from the sweep, kept as themselves. `1.0 - 0.001*i` is not exactly a
    uniform ramp in binary doubles, which is the point — the tie-break has to cover the input's own
    representation granularity, not merely the arithmetic done afterwards."""
    vals = [1.0 - i * 0.001 for i in range(n)]
    assert signal_end(vals) == n, (
        "`signal_end([1.0 - 0.001i], n=%d)` cut at %d. eta^2 - null = %+.3e against a tie-break of "
        "%.3e (n*eps would be %.3e)."
        % (n, signal_end(vals), partition(vals)[1] - _null_separability(n), _tie_break(vals),
           n * EPS))


def test_the_old_bound_would_fail_this_file():
    """The control. Every assertion above passes trivially if the tie-break is simply enormous, and
    a regression test that cannot distinguish a derived bound from a blanket tolerance says nothing.

    This reconstructs `n * eps` and asserts it is too tight for the series above. If this ever stops
    failing, the defect is no longer reachable and the rest of this file has stopped testing
    anything."""
    caught = [(n, partition([1.0 - i * 0.001 for i in range(n)])[1] - _null_separability(n))
              for n in (3, 4, 5, 12, 100)]
    would_cut = [(n, d) for n, d in caught if d > n * EPS]
    assert would_cut, (
        "the `n * eps` bound would now pass every case this file exists for — the arithmetic in "
        "`partition` must have changed, and this regression needs re-deriving rather than deleting")


def test_the_tie_break_does_not_swallow_real_structure():
    """The other direction, and the one a wider tolerance fails. A tie-break big enough to hide a
    ramp is also big enough to hide a cliff; the bound is only correct if the margin between them
    stays astronomical."""
    for label, vals, cut in (("a real cliff", [10.0, 9.0, 8.0, 1.0, 0.9], 3),
                             ("one dominant", [100.0] + [1.0] * 9, 1),
                             ("two clean groups", [9.0] * 20 + [0.5] * 20, 20)):
        margin = partition(vals)[1] - _null_separability(len(vals))
        assert separated(vals), "%s did not separate" % label
        assert signal_end(vals) == cut, "%s cut at %d, not %d" % (label, signal_end(vals), cut)
        assert margin > 1e6 * _tie_break(vals), (
            "%s clears the tie-break by only %.3e / %.3e — the floor is approaching the signal"
            % (label, margin, _tie_break(vals)))


@pytest.mark.parametrize("scale", [1e-18, 1e-6, 1.0, 1e6, 1e18])
def test_the_reading_is_scale_invariant(scale):
    """eta^2 is a ratio of variances, so multiplying every reading by a positive constant leaves
    every answer unchanged. A tie-break with an absolute magnitude in it would break exactly here."""
    assert not separated([scale * (4 - i) for i in range(4)])
    assert signal_end([scale * v for v in (10.0, 9.0, 8.0, 1.0, 0.9)]) == 3
