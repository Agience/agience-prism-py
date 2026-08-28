"""The error threshold: you cannot mine faster than you can verify.

The critical value is a conservation boundary (exactly 1.0), not a tuned constant. These pin
that the meter alarms when — and only when — the unvalidated pool is growing.
"""
from __future__ import annotations

from prism.error_threshold import (
    CRITICAL_RATIO, STRAIN_RATIO, FlowWindow, Health, assess, is_supercritical,
)


def test_clearing_keeps_pace_is_stable() -> None:
    """Mint 100 dark, clear 200 (promote 120 + evict 80) = ratio 2.0. Comfortable margin, so
    STABLE. A high mutation fraction is fine when gates clear it well faster than it arrives."""
    w = FlowWindow(minted_dark=100, promoted=120, evicted=80, total_writes=140)
    assert w.validation_ratio >= STRAIN_RATIO
    assert w.health is Health.STABLE
    assert w.mutation_fraction > 0.7       # lots of dark minted...
    assert not is_supercritical(w)         # ...but cleared far faster than minted


def test_minting_faster_than_clearing_is_catastrophe() -> None:
    """The failure this exists to make visible: mint 100, clear 40. The unvalidated pool grows
    by 60 this window and will keep growing — the validated fraction falls monotonically."""
    w = FlowWindow(minted_dark=100, promoted=25, evicted=15, total_writes=200)
    assert w.validation_ratio < CRITICAL_RATIO
    assert w.health is Health.CATASTROPHE
    assert is_supercritical(w)


def test_the_threshold_is_exactly_one_a_conservation_boundary() -> None:
    """clear == mint holds the pool steady — subcritical. clear == mint - 1 grows it. The
    boundary is 1.0 with nothing to tune; only the *strain warning* is a chosen number."""
    steady = FlowWindow(minted_dark=50, promoted=30, evicted=20)   # cleared 50 == minted 50
    assert steady.validation_ratio == 1.0
    assert steady.health is not Health.CATASTROPHE

    losing = FlowWindow(minted_dark=50, promoted=30, evicted=19)   # cleared 49 < 50
    assert losing.health is Health.CATASTROPHE


def test_strain_is_a_leading_warning_before_catastrophe() -> None:
    """The point of the advisory band: 'approaching' must be visible BEFORE 'over'. A ratio just
    above 1.0 is keeping pace but with no margin — report it, so mining can slow before the
    corpus rots rather than after."""
    w = FlowWindow(minted_dark=100, promoted=60, evicted=50)       # ratio 1.10, in [1.0, 1.25)
    assert CRITICAL_RATIO <= w.validation_ratio < STRAIN_RATIO
    assert w.health is Health.STRAINED
    assert not is_supercritical(w)         # a warning, not yet the alarm


def test_no_minting_is_idle_not_stable() -> None:
    """Nothing minted => nothing to balance => vacuously fine, but distinctly so: IDLE, not a
    misleading 'STABLE' that implies gates were tested. An idle corpus proved nothing."""
    w = FlowWindow(minted_dark=0, promoted=0, evicted=0, total_writes=10)
    assert w.validation_ratio == float("inf")
    assert w.health is Health.IDLE
    assert not is_supercritical(w)


def test_max_sustainable_mint_is_the_verify_rate() -> None:
    """'Mine no faster than you verify', literally: the ceiling equals what was cleared. Mint at
    or below it and you stay subcritical; above it and you cross the threshold."""
    w = FlowWindow(minted_dark=80, promoted=40, evicted=40)
    assert w.max_sustainable_mint == 80                            # cleared 40+40
    # minting exactly the ceiling is the boundary (subcritical); one more tips it.
    assert FlowWindow(minted_dark=80, promoted=40, evicted=40).health is not Health.CATASTROPHE
    assert FlowWindow(minted_dark=81, promoted=40, evicted=40).health is Health.CATASTROPHE


def test_assess_sums_flows_it_does_not_average_ratios() -> None:
    """A trend over windows is the honest read, and it must POOL the flows. Averaging ratios
    would let one quiet window (ratio inf) mask a catastrophic one — the exact way a lagging
    metric hides a rotting corpus."""
    quiet = FlowWindow(minted_dark=0, promoted=0, evicted=0)        # ratio inf
    rotting = FlowWindow(minted_dark=100, promoted=10, evicted=10)  # ratio 0.2
    # Pooled: minted 100, cleared 20 -> 0.2 -> catastrophe. Averaging ratios would say "fine".
    assert assess(quiet, rotting) is Health.CATASTROPHE


def test_a_recovering_trend_reads_stable_when_pooled() -> None:
    """Two windows: one bad, two good, pooled net-positive clearing => not catastrophe. The meter
    tracks the balance, not the worst moment."""
    bad = FlowWindow(minted_dark=50, promoted=10, evicted=10)       # -30
    good1 = FlowWindow(minted_dark=20, promoted=40, evicted=40)     # +60
    good2 = FlowWindow(minted_dark=20, promoted=30, evicted=30)     # +40
    assert assess(bad, good1, good2) is not Health.CATASTROPHE      # net cleared 90 vs minted 90
