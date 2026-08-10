"""Settlement — the facilitation split and refutation-as-annihilation (P7, UNIVERSAL-ECONOMICS).

    python -m pytest tests/test_settlement.py

The invariant under every test: settlement moves energy, never creates or destroys it.
"""
from __future__ import annotations

from prism import settlement as s
from prism import mass
from prism.attestation import Attestation, Ledger


def _standing(item: str, *origins: str):
    """An `AgreementRead` for a version attested by these independent origins — the standing that
    `annihilate` is handed for each side."""
    led = Ledger()
    for o in origins:
        led.record(Attestation(item_id=item, content_hash="h-" + item, authority=o, origin=o))
    return led.read(item)


# ── facilitation split: flat fee, conservation ────────────────────────────────────────────────────
def test_split_conserves_energy():
    sp = s.facilitation_split(10.0, fee=0.10)
    assert abs((sp.to_producer + sp.to_origin) - sp.earned) < 1e-9   # nothing evaporates
    assert sp.earned == 10.0


def test_fee_is_flat_not_a_percentage():
    """The anti-rent property: the fee is the same absolute amount whether value is small or large,
    so it shrinks as a fraction of value as value grows."""
    small = s.facilitation_split(1.0, fee=0.10)
    large = s.facilitation_split(1000.0, fee=0.10)
    assert small.to_origin == large.to_origin == 0.10               # flat, identical
    assert large.to_origin / large.earned < small.to_origin / small.earned  # rent share falls


def test_fee_bounded_by_conservation_not_a_cap():
    """The Origin cannot take energy that was never earned — the 1st law, not an arbitrary ceiling."""
    sp = s.facilitation_split(0.05, fee=0.10)                       # fee exceeds the whole payout
    assert sp.to_origin == 0.05                                     # takes all there is, no more
    assert sp.to_producer == 0.0
    assert sp.to_producer + sp.to_origin == sp.earned


def test_zero_earned_pays_nothing():
    sp = s.facilitation_split(0.0, fee=0.10)
    assert sp.to_producer == 0.0 and sp.to_origin == 0.0


def test_negative_earned_clamped_to_zero():
    sp = s.facilitation_split(-5.0, fee=0.10)
    assert sp.earned == 0.0 and sp.to_producer == 0.0 and sp.to_origin == 0.0


# ── refutation = annihilation: stake transfers, gated by inertia ──────────────────────────────────
def test_annihilation_FAILS_CLOSED_without_a_measurement():
    """A refutation moves a stake only when a caller supplies a measurement, and this is a money
    decision.

    A count of independent origins is not a measure of how valid something is: gating on the count
    makes a well-repeated claim unrefutable and leaves a correct refutation with one witness unable
    to collect. With no gate at all, any refutation seizes any stake. So `annihilate` fails closed
    and moves nothing until `resolved` says a measurement was made.

    Fails if `resolved` defaults to True, or if a count is used as a fallback. Either moves money on
    a measurement nobody made.
    """
    a = s.annihilate(_standing("claim", "alice"),
                     _standing("refuter", "bob", "carol", "dave"), staked=3.0)
    assert a.landed is False
    assert a.to_refuter == 0.0, "money moved with no measurement behind it"


def test_a_HEADCOUNT_no_longer_decides_who_takes_the_stake():
    """The same call, with the counts inverted both ways, gives the same answer, so the count does
    not decide who takes the stake.

    Asserted by symmetry, which catches an `agreeing >=` comparison in either direction.
    """
    many_vs_one = s.annihilate(_standing("claim", "alice", "bob", "carol"),
                               _standing("refuter", "dave"), staked=5.0)
    one_vs_many = s.annihilate(_standing("claim", "alice"),
                               _standing("refuter", "bob", "carol", "dave"), staked=5.0)
    assert many_vs_one == one_vs_many, "the attestation counts still change the settlement"


def test_a_RESOLVED_refutation_lands_and_takes_the_full_stake():
    """The positive half — a caller that has a measurement decides, and conservation still holds.

    Fails if the path fails closed unconditionally, which would make it dead rather than gated; no
    test above would notice that on its own.
    """
    a = s.annihilate(_standing("claim", "alice"),
                     _standing("refuter", "bob"), staked=3.0, resolved=True)
    assert a.landed is True
    assert a.to_refuter == 3.0                                       # full stake transfers


def test_annihilation_conserves_energy():
    """The claim's loss is exactly the refuter's gain — nothing is minted, nothing evaporates."""
    staked = 4.0
    a = s.annihilate(_standing("claim", "alice"),
                     _standing("refuter", "bob", "carol"), staked=staked, resolved=True)
    assert a.to_refuter == staked

    nothing = s.annihilate(_standing("claim", "alice"), _standing("refuter", "bob"), staked=staked)
    assert nothing.to_refuter == 0.0                                 # unresolved: nothing moves


def test_negative_stake_clamped():
    a = s.annihilate(_standing("claim", "alice"),
                     _standing("refuter", "bob"), staked=-5.0, resolved=True)
    assert a.to_refuter == 0.0


def test_split_over_a_demurrage_earned_value():
    """Conservation across a real demurrage payout.

    The scenario clock is stated explicitly, as the runner states it in production, and every
    assertion is relative to the payout the split actually receives, so this test pins conservation
    rather than the economy's clock."""
    from prism import demurrage as dem
    TAU = 40.0                    # this test's own scenario clock, named rather than inherited
    dem.set_slow_rate_source(lambda: TAU)
    try:
        w = dem.witness({"id": "x", "context": {"provenance": "human_validated"}}, now=0,
                        rest_mass=1.0)
        payout = dem.earned(w, now=100_000)          # t->inf, so ~= rest_mass * tau
        assert payout > 0.0                          # control: without a clock this is 0 and the
        #                                              conservation below would hold vacuously
        sp = s.facilitation_split(payout, fee=0.10)
        assert abs(sp.to_producer + sp.to_origin - payout) < 1e-6    # nothing created or destroyed
        assert sp.to_origin == 0.10                                  # flat fee off a real payout
        assert abs(sp.to_producer - (payout - 0.10)) < 1e-6          # producer keeps the remainder
    finally:
        dem.set_slow_rate_source(None)


def test_a_split_over_an_UNMEASURED_clock_pays_nothing_rather_than_a_guess():
    """The negative control for the test above: with no measured clock `earned` accrues nothing, so
    settlement pays nothing. A payout computed on a constant nobody measured is value invented at
    settlement time, and the failure mode is silent money.

    Fails if a fallback tau returns anywhere under `earned`."""
    from prism import demurrage as dem
    dem.set_slow_rate_source(None)
    w = dem.witness({"id": "x", "context": {"provenance": "human_validated"}}, now=0,
                    rest_mass=1.0)
    assert dem.earned(w, now=100_000) == 0.0
    sp = s.facilitation_split(dem.earned(w, now=100_000), fee=0.10)
    assert sp.to_producer == 0.0
