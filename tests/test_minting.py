"""Minting — the four guardrails, asserted.

`prism/minting.py` describes itself as *"the ONE place energy ENTERS the system, and that is why it
is the most carefully gated law here"*, and names four guardrails that make recognition impossible
to counterfeit.

Every test below states the counterfeit it prevents. A guardrail whose failure mode is not named is
a comment.
"""


# ── GUARDRAIL 1 — only VERIFIED lift counts ──────────────────────────────────────────────────────
def test_unattested_lift_mints_exactly_zero():
    """The counterfeit: an actor claims benefit nobody testified to, and the ledger recognises it.

    A claim of benefit is not benefit. Lift enters only through a beneficiary's own attestation.
    """
    from prism.minting import mint

    m = mint([], actor="a", actor_cost=0.0)
    assert m.amount == 0.0
    assert m.residual.attesters == 0
    assert m.residual.verified_lift == 0.0


# ── GUARDRAIL 2 — no self-attestation ────────────────────────────────────────────────────────────
def test_an_actor_cannot_testify_to_its_own_benefit():
    """The counterfeit: the actor attests that it lifted itself, and mints on its own say-so.

    A system that mints on self-report diverges; one that mints on measurement converges.
    """
    from prism.minting import Attestation, mint

    m = mint([Attestation(beneficiary="a", lift=1000.0, mass=1.0)], actor="a", actor_cost=0.0)
    assert m.amount == 0.0, "an actor minted on its own attestation"
    assert m.residual.excluded_self == 1, "the exclusion must be REPORTED, not silent"


def test_a_real_beneficiary_beside_a_self_attestation_still_counts():
    """The negative control for guardrail 2. If self-exclusion also dropped legitimate attestations,
    the test above would pass for the wrong reason and minting would be dead rather than gated."""
    from prism.minting import Attestation, mint

    m = mint([Attestation(beneficiary="a", lift=1000.0, mass=1.0),
              Attestation(beneficiary="b", lift=5.0, mass=1.0)], actor="a", actor_cost=0.0)
    assert m.amount == 5.0
    assert m.residual.attesters == 1 and m.residual.excluded_self == 1


def test_one_beneficiary_cannot_attest_twice():
    """The counterfeit: repetition as lift. One voice per beneficiary; saying it louder is not
    evidence."""
    from prism.minting import Attestation, mint

    m = mint([Attestation(beneficiary="b", lift=5.0, mass=1.0)] * 4, actor="a", actor_cost=0.0)
    assert m.amount == 5.0, "repeated attestations multiplied the recognition"


# ── GUARDRAIL 3 — authority-weighted, never counted ──────────────────────────────────────────────
def test_a_swarm_of_massless_attesters_cannot_outweigh_one_grounded_one():
    """The counterfeit: sybil. A thousand fresh identities out-vote one attester with real standing.

    The anti-sybil property falls out of the physics rather than being bolted on: recognition is
    the authority-weighted sum, so mass ≈ 0 contributes ≈ 0 however many times it appears.
    """
    from prism.minting import Attestation, mint

    ghosts = [Attestation(beneficiary="g%d" % i, lift=100.0, mass=1e-9) for i in range(1000)]
    grounded = [Attestation(beneficiary="real", lift=10.0, mass=1.0)]

    swarm = mint(ghosts, actor="a", actor_cost=0.0).amount
    honest = mint(grounded, actor="a", actor_cost=0.0).amount
    assert swarm < honest, (
        "1000 massless attesters (%g) outweighed one grounded attester (%g)" % (swarm, honest))


def test_zero_mass_and_zero_lift_contribute_nothing_and_that_is_not_a_cap():
    """An empty or massless attestation has no weight to contribute. This is exclusion by absence of
    evidence, not a ceiling — there is no chosen bound anywhere in the module."""
    from prism.minting import Attestation, mint

    m = mint([Attestation(beneficiary="b", lift=0.0, mass=1.0),
              Attestation(beneficiary="c", lift=5.0, mass=0.0)], actor="a", actor_cost=0.0)
    assert m.amount == 0.0 and m.residual.attesters == 0


# ── GUARDRAIL 4 — conservation of recognition ────────────────────────────────────────────────────
def test_the_mint_can_never_exceed_the_measured_residual():
    """The counterfeit: minting more than was verifiably lifted — energy from nothing."""
    from prism.minting import Attestation, conserves, mint

    m = mint([Attestation(beneficiary="b%d" % i, lift=3.0, mass=1.0) for i in range(4)],
             actor="a", actor_cost=5.0)
    assert m.amount == 7.0                       # 12 lifted - 5 cost
    assert m.amount <= m.residual.verified_lift
    assert conserves(m)


def test_an_act_that_cost_more_than_it_lifted_mints_nothing():
    """An honest zero, never a negative and never an error. No surplus exists to recognise."""
    from prism.minting import Attestation, conserves, mint

    m = mint([Attestation(beneficiary="b", lift=1.0, mass=1.0)], actor="a", actor_cost=100.0)
    assert m.amount == 0.0 and conserves(m)


def test_conserves_rejects_a_tampered_mint():
    """The check that makes the other conservation tests mean something: `conserves` must be able
    to FAIL. If it returned True unconditionally, every assertion above would still pass."""
    from dataclasses import replace

    from prism.minting import Attestation, conserves, mint

    m = mint([Attestation(beneficiary="b", lift=10.0, mass=1.0)], actor="a", actor_cost=0.0)
    assert conserves(m)
    assert not conserves(replace(m, amount=m.amount + 1.0)), (
        "a mint claiming more than its residual passed conservation")
    assert not conserves(replace(m, amount=-1.0)), "a negative mint passed conservation"



# ── the tolerance is derived, not chosen ─────────────────────────────────────────────────────────
def test_the_conservation_tolerance_tracks_its_inputs():
    """A derivation that returns the same number regardless of its inputs is the old constant
    wearing a function. This is the check that tells the two apart.

    `conservation_tolerance` is the forward error bound for `residual`'s arithmetic — a naive sum of
    `attesters` products, then one subtraction — so it MUST grow with both the term count and the
    magnitude. If either of these assertions can be removed and the suite still passes, the value is
    not derived.
    """
    from prism.minting import Residual, conservation_tolerance

    def R(lift, n):
        return Residual(verified_lift=lift, actor_cost=0.0, minted=lift, attesters=n,
                        excluded_self=0)

    assert conservation_tolerance(R(10.0, 300)) > conservation_tolerance(R(10.0, 3)), (
        "more summed terms accumulate more rounding; the tolerance did not move with the count")
    assert conservation_tolerance(R(1e12, 3)) > conservation_tolerance(R(1e1, 3)), (
        "float64 spaces its numbers by magnitude; the tolerance did not move with the scale")


def test_the_old_constant_was_wrong_at_both_ends():
    """Why a fixed tolerance cannot work here, asserted rather than argued.

    A single `1e-9` compared against a measurement at every scale cannot be right at more than one
    scale: at a large lift it demands precision float64 does not have, so CORRECT arithmetic reads
    as a conservation violation; at a small lift it is looser than the arithmetic needs, so a real
    discrepancy passes.
    """
    from prism.minting import Residual, conservation_tolerance

    big = Residual(verified_lift=1e12, actor_cost=0.0, minted=1e12, attesters=3, excluded_self=0)
    tiny = Residual(verified_lift=1e-6, actor_cost=0.0, minted=1e-6, attesters=3, excluded_self=0)

    assert conservation_tolerance(big) > 1e-9, (
        "at a lift of 1e12 the old constant was TIGHTER than float64 can represent — correct "
        "arithmetic would have been reported as a conservation failure")
    assert conservation_tolerance(tiny) < 1e-9, (
        "at a lift of 1e-6 the old constant was looser than the arithmetic needs, so a real "
        "discrepancy passed as conserved")


def test_conservation_holds_across_twelve_orders_of_magnitude():
    """The property the derived tolerance buys: the identity is checkable at any scale, on the same
    code, without anyone re-tuning a number."""
    from prism.minting import Attestation, conserves, mint

    for scale in (1e-6, 1.0, 1e6, 1e12):
        m = mint([Attestation(beneficiary="b%d" % i, lift=scale, mass=1.0) for i in range(5)],
                 actor="a", actor_cost=scale)
        assert conserves(m), "conservation failed at scale %g" % scale
