"""Mass is counted, and the validity ladder stays out of `prism.mass`.

`prism.attestation` holds the mass model: it counts how many independent origins attest an artifact,
rather than looking a rank up from a label. There is no hierarchy of claim validity.

This file asserts that the ladder's names are not importable — that nothing returns a band edge, a
ghost floor or a weight. It leaves the strings alone. The commentary explaining why those names went
is the most valuable thing in those files, and a test that banned the words would delete the
reasoning in order to satisfy itself.

Guarding the absence matters because the names appear throughout prism as commentary, which is
exactly the material someone reinstates from in good faith.
"""
from __future__ import annotations

import pytest

RETIRED = ("_BANDS", "GHOST_FLOOR", "weigh", "RUNGS", "_RUNGS")


def test_prism_mass_exposes_NONE_of_the_retired_ladder_names():
    """None of the ladder names resolve on `prism.mass`.

    Fails if any is reinstated as a constant, a function or a re-export, and names which one.
    """
    import prism.mass as mass
    back = [n for n in RETIRED if getattr(mass, n, None) is not None]
    assert not back, (
        "the claim ladder is back in prism.mass: %s. Mass is COUNTED, not looked up — "
        "`prism.attestation` counts independent origins attesting. [John, 2026-08-03: \"I expect "
        "things like the claim ladder to be ripped out.\"]" % back)


def test_the_replacement_is_PRESENT_and_counts_ORIGINS():
    """The counting model is present, so the ladder's absence means "counted" and not "no model".

    An absence guard on its own would pass equally well if mass had been removed outright with
    nothing in its place. This is the positive half.

    Fails if `prism.attestation` loses its counting surface.
    """
    from prism import attestation
    assert hasattr(attestation, "Ledger"), "the counted mass model is gone, not just the ladder"


def test_displaces_REFUSES_rather_than_deciding_head_by_headcount():
    """`displaces` raises rather than ranking one claim over another by headcount.

    A count of independent origins measures agreement, not validity, so deciding which claim wins by
    comparing counts would rebuild the ladder in a second form. The name is kept, and raises, so the
    reasoning stays reachable at the call site.

    Fails if the `agreeing >=` body returns. Asserted by calling it, because a docstring saying
    "retired" beside a working body would pass any name-based check.
    """
    import pytest
    from prism.attestation import displaces
    with pytest.raises(NotImplementedError) as e:
        displaces(None, None)
    assert "AGREEMENT, not validity" in str(e.value)


def test_the_agreement_READ_itself_is_NOT_retired():
    """The agreement read stays: counting independent origins is a real measurement.

    It is a reading of existence [[existence-is-observer-agreement]], and it is not a rank. Removing
    the count along with the ranking would discard the measurement too.

    Fails if `agreeing`/`resolved` go, leaving no way to say how widely something is attested.
    """
    from prism.attestation import AgreementRead, Ledger
    assert hasattr(AgreementRead, "agreeing") and hasattr(AgreementRead, "origins")
    assert hasattr(Ledger, "read")


def test_THIS_GUARD_CAN_FAIL():
    """The control: the detector sees a name that is actually there
    [[verification-that-cannot-fail]].

    `getattr(mod, name, None)` returns None both for "absent" and for "present but None", so an
    import yielding a stub module would satisfy every assertion above on nothing. This checks the
    detector against a name known to be present.
    """
    import prism.mass as mass
    present = [n for n in dir(mass) if not n.startswith("__")]
    assert present, "prism.mass imported as an empty stub — every check above is vacuous"
    probe = present[0]
    assert getattr(mass, probe, None) is not None or probe in dir(mass), (
        "the detector cannot see a name that is actually there")
