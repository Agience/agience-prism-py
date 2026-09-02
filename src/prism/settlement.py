"""Settlement — how earned energy is paid out, and what refutation does to a stake (P7).

[UNIVERSAL-ECONOMICS §"The rest falls out" · §9c adoption. Follows `demurrage` (the payout basis)
and `mass` (the inertia around a revision).]

Two laws, both pure and both conservation-respecting: this module moves energy and creates or
destroys none. Like `mass` and `demurrage` it is stdlib-only and lives in `core`, so the server and
the leaf settle identically. A disagreement about who gets paid would fork the economy.

1. The facilitation split — the Origin's cut is flat rather than a percentage
-----------------------------------------------------------------------------
Adoption turns on keeping more, without a 20-30% cut. When an artifact's `demurrage.earned` value
settles, the governing Origin takes a flat facilitation fee and the rest goes to the producer or
observer whose work earned it. Flat rather than `fee·value` is the anti-rent design: a percentage is
economic rent (Piketty's `r>g` for the platform), while a flat fee is a service charge that shrinks
as a fraction of value as value grows. The one bound on the fee is conservation — the Origin takes at
most what was earned (`min(fee, earned)`), which is the first law rather than a chosen ceiling
([[no-arbitrary-caps]]).

2. Refutation as matter/antimatter annihilation — the stake transfers to the refuter
------------------------------------------------------------------------------------
A claim may carry a stake: energy its asserter put at risk. A refutation is antimatter to that
claim's matter — when they meet, the claim is annihilated and its staked energy is released to the
refuter. Conservation holds exactly: what the claim loses, the refuter gains, and nothing evaporates.

Landing is decided by the caller's own measurement. `annihilate(..., resolved=)` moves energy only
when a measurement is supplied; with none, nothing moves. A count of independent origins is not
available as a gate here — it would make attestation decide who takes money, so a well-repeated claim
would become unrefutable and a correct refutation with one witness could never collect. Nor is such a
count separable in the first place: `prism.resolution` gives no reading on two counts, since at n=2
the computed null is exactly 1.0000. Moving no money without a measurement is the safe direction and
the honest one — a caller that can measure decides, and one that cannot leaves the stake where it is.

This is the wire that reads `staked_claim`, which UNIVERSAL-ECONOMICS flags as "a stub, never read —
the one true gap." The law is here and pure; the live slash, writing the annihilated stake back
through the store, stays gated behind the data freeze.
"""
from __future__ import annotations

from typing import Optional

from dataclasses import dataclass

from . import mass as _mass   # a sibling module: the revision type this settlement reports


@dataclass(frozen=True)
class Split:
    """A settled payout. `to_producer + to_origin == earned` exactly — conservation, checkable."""
    to_producer: float
    to_origin: float
    earned: float


def facilitation_split(earned: float, *, fee: float) -> Split:
    """Divide a settled `earned` value into the producer's share and the Origin's flat facilitation
    fee. The Origin takes `min(fee, earned)` — flat, and bounded by what exists (conservation rather
    than a cap). `fee` is the Origin's governed constant
    (`origin.DEFAULT_CONSTANTS["facilitation_fee"]`)."""
    e = max(0.0, float(earned))
    to_origin = min(max(0.0, float(fee)), e)
    return Split(to_producer=round(e - to_origin, 6), to_origin=round(to_origin, 6), earned=round(e, 6))


@dataclass(frozen=True)
class Annihilation:
    """The outcome of a refutation meeting a staked claim."""
    landed: bool                 # did the caller's measurement land the refutation?
    to_refuter: float            # staked energy released to the refuter (0.0 when it did not land)
    revision: "_mass.Revision"   # the revision this settlement implies; left `None` by `annihilate`


def annihilate(claim, refuter, staked: float, *, resolved: Optional[bool] = None) -> Annihilation:
    """Refutation as annihilation. Fails closed: energy moves only on a measurement.

    On landing, the claim's `staked` energy is released to the refuter — conservation, since the
    claim's loss is the refuter's gain. Whether it lands is `resolved`, which the caller supplies
    from its own measurement. `resolved=None` moves nothing and reports `landed=False`.

    The decision belongs to the caller because attestation cannot make it. Landing a refutation on a
    count of independent origins would let a well-repeated claim stand unrefutable while a correct
    refutation with one witness never collects, and independent origins measure repetition rather
    than validity. Two such counts are also inseparable: `prism.resolution` has no reading to give at
    n=2, where the computed null is exactly 1.0000. Provenance is not a comparable measure either:
    `prism.mass.Provenance` is an unranked partition — grounded or not — rather than a scored ladder,
    so there is no number there to land a refutation on either.

    Failing closed is the safe direction: without it, any refutation could seize any stake. A caller
    that can measure decides; one that cannot leaves the stake in place.

    `revision` is reported as `None`, because no revision gate runs on this path.
    """
    if resolved is not True:
        return Annihilation(landed=False, to_refuter=0.0, revision=None)
    return Annihilation(landed=True, to_refuter=round(max(0.0, float(staked)), 6), revision=None)


__all__ = ["Split", "facilitation_split", "Annihilation", "annihilate"]
