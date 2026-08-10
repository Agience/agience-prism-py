"""Demurrage — held value dissipates unless re-verified (UNIVERSAL-ECONOMICS §2nd-law).

    python -m pytest tests/test_demurrage.py

The invariant the design rests on: **demurrage acts on energy, and leaves belief alone.** If cooling
an artifact's economic value can change how it was obtained (`mass.provenance_of`), this file fails.

`rest_mass` is supplied by the caller, and every deposit below names the standing it is sized by.
Mass is counted — `prism.attestation` counts the independent origins attesting an artifact — so the
size of a deposit is a fact only the caller holding the ledger has. Naming it at each call site also
makes each scenario readable on its own.
"""
from __future__ import annotations

import math

import pytest

from prism import demurrage as dem
from prism import mass

# Deposit sizes, as counts of independent origins — what `prism.attestation` measures.
WELL_ATTESTED = 3.0     # three independent origins stand behind it
ONE_WITNESS = 1.0       # a single origin


def _w(artifact, now, *, rest_mass=WELL_ATTESTED, **kw):
    """`dem.witness` with the standing named. The default is arbitrary for the test — these exercise
    the decay law, which is scale-free — and the scenarios that care state their own."""
    return dem.witness(artifact, now=now, rest_mass=rest_mass, **kw)

# A tau chosen by this test for its own scenario: checking `exp(-1)` after one tau requires naming a
# tau. These tests exercise the decay mathematics. The clock's provenance is a separate question,
# covered by `test_there_is_NO_demurrage_constant_and_an_unmeasured_clock_does_not_cool`.
TAU = 40.0


@pytest.fixture(autouse=True)
def _measured_clock():
    """Stand in for the runner's boot wiring, which installs the node screen's measured slow rate
    (`ember.runtime.boot._wire_demurrage_clock`). With no source there is no clock and nothing cools,
    so the decay tests here need one installed to be measuring decay at all."""
    dem.set_slow_rate_source(lambda: TAU)
    yield
    dem.set_slow_rate_source(None)


# ── the load-bearing separation: energy never touches belief ──────────────────────────────────────
def test_demurrage_never_changes_belief():
    """A human-validated fact cooled to cold energy is still human-validated. Belief is conserved;
    only the economic 'worth of holding it now' dissipates."""
    ctx = {"provenance": mass.Provenance.HUMAN_VALIDATED.value}
    art = {"id": "x", "context": dict(ctx)}

    hot = _w(art, now=0)                             # do work → deposit
    cold_later = dem.energy(hot, now=10_000)         # let it dissipate for ages
    assert cold_later < 1e-6                         # economic energy gone

    # ...and how it was obtained is unmoved, on both the original and the witnessed copy.
    assert mass.provenance_of(art) is mass.Provenance.HUMAN_VALIDATED
    assert mass.provenance_of(hot) is mass.Provenance.HUMAN_VALIDATED
    assert mass.has_referent(mass.provenance_of(hot)), \
        "a fully-cooled artifact lost its grounding — energy leaked into belief"


def test_witness_copies_never_mutates():
    art = {"id": "x", "context": {"provenance": "observed"}}
    _ = _w(art, now=5)
    assert dem.HEAT_FIELD not in art["context"]       # input untouched (mass.stamp discipline)
    assert dem.FRAME_FIELD not in art["context"]


# ── the accumulator: deposit + 2nd-law cooling ────────────────────────────────────────────────────
def test_fresh_deposit_energy_equals_rest_mass():
    art = {"id": "x", "context": {"provenance": "human_validated"}}
    w = _w(art, now=0, rest_mass=ONE_WITNESS)
    assert abs(dem.energy(w, now=0) - ONE_WITNESS) < 1e-6   # a fresh deposit == its rest mass


def test_deposit_sized_by_standing_cannot_mint_faster_than_attestation():
    """Deposit size is the ratio of independent origins, so energy tracks what was attested.

    A provenance label cannot mint energy on its own: two artifacts with the same label and
    different standing get deposits in proportion to the origins behind them."""
    hi = _w({"id": "a", "context": {"provenance": "observed"}}, now=0, rest_mass=WELL_ATTESTED)
    lo = _w({"id": "b", "context": {"provenance": "observed"}}, now=0, rest_mass=ONE_WITNESS)
    assert dem.energy(hi, now=0) > dem.energy(lo, now=0)
    assert abs(dem.energy(hi, now=0) / dem.energy(lo, now=0)
               - WELL_ATTESTED / ONE_WITNESS) < 1e-6, "the accumulator is linear in standing"


def test_energy_monotone_non_increasing_between_deposits():
    w = _w({"id": "x", "context": {"provenance": "observed"}}, now=0)
    prev = math.inf
    for now in range(0, 200, 7):
        e = dem.energy(w, now=now)
        assert e <= prev + 1e-9                        # a new deposit is the only thing that raises it
        prev = e


def test_cooling_follows_exp_tau():
    w = _w({"id": "x", "context": {"provenance": "human_validated"}}, now=0,
           rest_mass=ONE_WITNESS)                      # heat 1.0
    e_tau = dem.energy(w, now=int(TAU))
    assert abs(e_tau - math.exp(-1.0)) < 1e-3          # one tau → 1/e of the deposit


def test_backwards_clock_never_mints_energy():
    """Energy is money, so a clock that runs backwards leaves it where it was. dt is clamped at 0."""
    w = _w({"id": "x", "context": {"provenance": "human_validated"}}, now=100)
    at_deposit = dem.energy(w, now=100)
    earlier = dem.energy(w, now=50)                    # a read before the deposit frame
    assert earlier <= at_deposit + 1e-9                # time travel earns no heat


# ── consumption warms; frequency compounds (the PoUW meter) ────────────────────────────────────────
def test_re_witness_adds_heat():
    w = _w({"id": "x", "context": {"provenance": "observed"}}, now=0)
    e1 = dem.energy(w, now=10)
    w2 = _w(w, now=10)                        # consumed again
    assert dem.energy(w2, now=10) > e1                 # work warms it back up


def test_frequent_consumption_beats_single_consumption():
    """Two deposits within a tau accumulate above one — frequently-used value stays hot."""
    once = _w({"id": "a", "context": {"provenance": "observed"}}, now=0)
    twice = _w(_w({"id": "b", "context": {"provenance": "observed"}}, now=0),
                        now=5)
    assert dem.energy(twice, now=5) > dem.energy(once, now=5)


def test_never_consumed_artifact_has_zero_energy():
    """No passive wealth: economic energy comes from work done, whatever the provenance."""
    art = {"id": "x", "context": {"provenance": "human_validated"}}
    assert dem.energy(art, now=0) == 0.0
    assert dem.energy(art, now=1_000) == 0.0


def test_unattested_energy_stays_proportional_to_its_standing():
    """Per-event anti-laundering: low standing makes each deposit small, so under identical
    consumption a thinly-attested artifact stays far below a well-attested one.

    The proportion holds without a cap. Bounding energy under adversarial over-consumption belongs
    to the `work`-independence derivement (see `deposit`)."""
    thin = {"id": "g", "context": {"provenance": "assertion"}}
    real = {"id": "r", "context": {"provenance": "human_validated"}}
    for now in range(0, 50, 5):                                    # identical consumption pattern
        thin = _w(thin, now=now, rest_mass=ONE_WITNESS)
        real = _w(real, now=now, rest_mass=WELL_ATTESTED)
    ratio = ONE_WITNESS / WELL_ATTESTED
    assert abs(dem.energy(thin, now=50) - ratio * dem.energy(real, now=50)) < 1e-3


def test_nothing_attested_has_no_temperature_scale():
    """`rest_mass is None` means nothing attests the artifact, so there is no scale to be warm
    against.

    Unmeasured and fully-dissipated are different claims, and `warmth` distinguishes them: `None`
    when there is no scale, `0.0` when the scale exists and the energy has gone
    ([[absence-is-not-an-observation-of-zero]])."""
    art = {"id": "g", "context": {"provenance": "assertion"}}
    assert dem.temperature(art, now=0, rest_mass=None) == "cold"
    assert dem.warmth(art, now=0, rest_mass=None) is None

    dissipated = _w({"id": "r", "context": {"provenance": "observed"}}, now=0,
                    rest_mass=ONE_WITNESS)
    assert dem.warmth(dissipated, now=100_000, rest_mass=ONE_WITNESS) == 0.0


def test_repeated_self_consumption_bound_is_the_work_seam():
    """The derivement seam: an independent consumer (work=1) deposits, a repeat echo (work→0) adds
    nothing. States the contract an independence derivation has to satisfy, leaving its curve open."""
    art = {"id": "x", "context": {"provenance": "observed"}}
    fresh = _w(art, now=0)                                  # first, independent use
    e_after_fresh = dem.energy(fresh, now=0)
    echo = _w(fresh, now=0, work=0.0)                       # same consumer again → an echo
    assert dem.energy(echo, now=0) == e_after_fresh                 # the echo leaves the energy where it was


# ── temperature triage ────────────────────────────────────────────────────────────────────────────
def test_temperature_bands():
    w = _w({"id": "x", "context": {"provenance": "human_validated"}}, now=0,
           rest_mass=ONE_WITNESS)
    assert dem.temperature(w, now=0, rest_mass=ONE_WITNESS) == "hot"     # fresh deposit
    # cool past the 5%-of-rest-mass 'warm' floor → cold
    cold_frame = int(TAU * math.log(1 / 0.01))
    assert dem.temperature(w, now=cold_frame, rest_mass=ONE_WITNESS) == "cold"


def test_temperature_of_unconsumed_is_cold():
    assert dem.temperature({"id": "x", "context": {"provenance": "observed"}}, now=0,
                           rest_mass=ONE_WITNESS) == "cold"


# ── Origin-governed tau ───────────────────────────────────────────────────────────────────────────
def test_larger_tau_dissipates_slower():
    art = {"id": "x", "context": {"provenance": "human_validated"}}
    slow = _w(art, now=0, tau=200.0)
    fast = _w(art, now=0, tau=10.0)
    assert dem.energy(slow, now=40, tau=200.0) > dem.energy(fast, now=40, tau=10.0)


def test_there_is_NO_demurrage_constant_and_an_unmeasured_clock_does_not_cool():
    """There is no demurrage constant, and an unmeasured clock leaves heat where it is.

    A slow rate is a measurement, so with no source installed `tau_now()` reports `unmeasured` and
    `cool` carries heat forward unchanged — dissipating it would destroy value on the authority of a
    literal. `earned` holds steady over the same interval: growing it would mint on an unmeasured
    basis, and resetting it would discard realized value.

    Fails if a fallback number reappears anywhere on that path."""
    assert not hasattr(dem, "DEMURRAGE_TAU")

    dem.set_slow_rate_source(None)
    assert dem.tau_now() == (None, "unmeasured")
    assert dem.cool(100.0, 0, 50) == 100.0            # carried forward, not decayed
    assert dem.accrue(100.0, 0, 50, earned=7.0) == 7.0

    try:
        dem.set_slow_rate_source(lambda: 13.02)       # a rate measured off a live conversation
        assert dem.tau_now() == (13.02, "measured")
        assert dem.cool(100.0, 0, 50) < 100.0         # control: it really does cool once measured
        assert dem.accrue(100.0, 0, 50, earned=7.0) > 7.0
    finally:
        dem.set_slow_rate_source(None)


def _retired_test_the_demurrage_clock_is_a_CHOSEN_constant_standing_alone():
    """A screen's slow timescale is measured per screen, so there is no fixed constant to pin here;
    `test_there_is_NO_demurrage_constant_and_an_unmeasured_clock_does_not_cool` covers that ground
    against the measured clock instead. Prefixed `_retired_` so pytest does not collect it."""


# ── robustness: string context, missing/garbage fields ────────────────────────────────────────────
def test_energy_reads_json_string_context():
    import json
    art = {"id": "x", "context": json.dumps({"provenance": "observed"})}
    w = _w(art, now=0)
    # witness returns a dict context; energy must read it back correctly
    assert dem.energy(w, now=0) > 0.0


def test_energy_zero_on_garbage_fields():
    art = {"id": "x", "context": {"provenance": "observed",
                                  dem.HEAT_FIELD: "nan", dem.FRAME_FIELD: None}}
    assert dem.energy(art, now=0) == 0.0                      # non-numeric fields read as no energy


# ── the settlement integral: ∫energy·dt — the P7 payout ───────────────────────────────────────────
def test_earned_is_zero_at_the_instant_of_deposit():
    """Value is realized over time; at the deposit frame no area has been swept yet."""
    w = _w({"id": "x", "context": {"provenance": "human_validated"}}, now=0)
    assert dem.earned(w, now=0) == 0.0


def test_earned_monotone_non_decreasing():
    w = _w({"id": "x", "context": {"provenance": "observed"}}, now=0)
    prev = -1.0
    for now in range(0, 300, 11):
        e = dem.earned(w, now=now)
        assert e >= prev - 1e-9                               # realized value stays realized
        prev = e


def test_single_deposit_lifetime_payout_converges_to_rest_mass_times_tau():
    """A single deposit's total lifetime value is finite: rest_mass·τ. Value is conserved, so one
    deposit pays a bounded amount however long it is held."""
    w = _w({"id": "x", "context": {"provenance": "human_validated"}}, now=0,
           rest_mass=ONE_WITNESS)
    lifetime = dem.earned(w, now=100_000)                     # effectively t→∞
    assert abs(lifetime - ONE_WITNESS * TAU) < 1e-2


def test_frequency_is_rewarded_and_unbounded_in_genuine_work():
    """N independent deposits earn ≈ N × a single deposit's lifetime payout. The ceiling on this
    quantity is real independent consumption, and nothing else."""
    single = _w({"id": "a", "context": {"provenance": "human_validated"}}, now=0)
    many = {"id": "b", "context": {"provenance": "human_validated"}}
    N = 5
    for k in range(N):                                        # N independent uses, spaced out
        many = _w(many, now=k * 500)
    long_after = N * 500 + 100_000
    assert dem.earned(many, now=long_after) > 4.5 * dem.earned(single, now=long_after)


def test_echo_consumption_earns_nothing_extra():
    """The anti-spam property, at the payout: a repeat by the same consumer (work→0) deposits 0 heat,
    so it adds 0 area. The independence seam bounds this, so there is no cap to tune."""
    art = {"id": "x", "context": {"provenance": "observed"}}
    once = _w(art, now=0)
    spam = once
    for k in range(1, 20):                                    # hammered 19 more times, all echoes
        spam = _w(spam, now=k, work=0.0)
    horizon = 100_000
    assert abs(dem.earned(spam, now=horizon) - dem.earned(once, now=horizon)) < 1e-2


def test_earned_never_changes_belief():
    art = {"id": "x", "context": {"provenance": "human_validated"}}
    w = _w(art, now=0)
    _ = dem.earned(w, now=1_000)
    assert mass.provenance_of(w) is mass.Provenance.HUMAN_VALIDATED
    assert mass.has_referent(mass.provenance_of(w))


def test_earned_of_never_consumed_is_zero():
    assert dem.earned({"id": "x", "context": {"provenance": "human_validated"}}, now=5_000) == 0.0


def test_earned_survives_across_witnesses_as_a_running_total():
    """Booked value persists in EARNED_FIELD as a running total, carried forward across witnesses."""
    w = _w({"id": "x", "context": {"provenance": "observed"}}, now=0)
    booked = dem.earned(w, now=50)
    w2 = _w(w, now=50)                               # settles [0,50] into the field, then deposits
    assert w2["context"][dem.EARNED_FIELD] >= booked - 1e-9
    # and reading further out only grows it
    assert dem.earned(w2, now=200) >= w2["context"][dem.EARNED_FIELD] - 1e-9
