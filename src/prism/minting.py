"""Minting — the residual of improved lives is the free energy that mints (P8).

[UNIVERSAL-ECONOMICS §13 · §12.1 conservation · §14 authority-weighted agreement. Follows
`demurrage` (the payout basis) and `settlement` (how earned energy moves).]

This is the one place energy enters the system, which is why it is the most carefully gated law here.
Everywhere else energy moves (settlement) or dissipates (demurrage). Minting is justified because
what it accounts for is real: when an act lifts many lives beyond what it cost the actor, that
surplus exists in the world and the ledger recognizes it. §13, exactly: a big need is a steep
gradient; people are operators; the response is a distributed discharge; the residual — the surplus
lift across many lives beyond the actor's cost — is the free energy that mints, and the beneficiaries
are the verifiers.

Four guardrails make recognition impossible to counterfeit. Each is a law rather than a policy:

1. **Only verified lift counts.** A claim of benefit is not benefit. Lift enters the residual through
   a beneficiary's own attestation, because the beneficiary is the verifier (§13). Unattested good
   intentions mint exactly zero.
2. **No self-attestation.** An actor's testimony about their own benefit carries no weight. This is
   [[developmental-learning-not-self-reinforcement]] applied to the economy: a system that mints on
   its own say-so diverges (§14 — self-reinforcement runs away; measurement converges).
3. **Authority-weighted rather than counted.** §14: agreement is the authority-weighted mean of
   accurate observers rather than a vote. A beneficiary's attestation carries their mass, so a
   thousand massless attestations weigh less than one grounded one, and the anti-sybil property falls
   out of the physics rather than being bolted on.
4. **Conservation of recognition.** The mint is bounded by the measured residual (verified lift −
   actor cost). No chosen ceiling appears anywhere in this file ([[no-arbitrary-caps]]): the bound is
   the measurement itself, and a non-positive residual mints nothing. Cost is subtracted first
   because the actor was already compensated for it.

Pure and stdlib-only, like `mass`, `demurrage`, and `settlement`, so every node computes the same
mint from the same evidence. Two nodes disagreeing about what was minted would fork the economy.

The live write — crediting the minted energy through the store — stays gated behind the data freeze,
exactly as `settlement`'s slash does. The law is here and exact; turning it on is a deployment act.
"""
from __future__ import annotations

import sys

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Attestation:
    """A beneficiary's own verified statement that an act lifted them, and by how much.

    `lift` is in the same energy units as `demurrage` — what the beneficiary says the act was worth
    to them. `mass` is the attester's belief mass (provenance-weighed), so recognition is
    authority-weighted (§14). `beneficiary` is the attesting origin, and is required: only a named
    attestation can be checked for self-dealing, which is what makes it usable for minting."""
    beneficiary: str
    lift: float
    mass: float = 1.0


@dataclass(frozen=True)
class Residual:
    """The measured surplus, with its full basis kept so any node can re-derive the same number.
    `minted == max(0, verified_lift - actor_cost)` — conservation of recognition, checkable."""
    verified_lift: float
    actor_cost: float
    minted: float
    attesters: int
    excluded_self: int
    basis: Dict[str, float] = field(default_factory=dict)


def _valid(attestations: Iterable[Attestation], actor: str):
    """Split attestations into (usable, self-excluded). Non-positive lift or non-positive mass
    contributes nothing: a massless or empty attestation carries no weight, which is a property of
    the weighting rather than a cap."""
    usable: List[Attestation] = []
    excluded = 0
    seen: set = set()
    for a in attestations or ():
        if not a.beneficiary:
            continue
        if a.beneficiary == actor:                 # guardrail 2 — no self-attestation
            excluded += 1
            continue
        if a.beneficiary in seen:                  # one voice per beneficiary; repetition is not lift
            continue
        if float(a.lift) <= 0.0 or float(a.mass) <= 0.0:
            continue
        seen.add(a.beneficiary)
        usable.append(a)
    return usable, excluded


def _weighted_lift(usable: List[Attestation]) -> float:
    """The law, single-sourced: recognition is `Σ(lift · mass)` over usable attestations.

    Guardrail 3 (authority-weighted rather than counted) is the anti-sybil property, and it lives at
    this one site so `verified_lift` and `residual` compute it identically. One site is also what
    makes it testable: a mutation to the expression moves every caller, so the sybil test sees it.
    """
    return float(sum(float(a.lift) * float(a.mass) for a in usable))


def verified_lift(attestations: Iterable[Attestation], *, actor: str) -> float:
    """The authority-weighted lift actually attested by beneficiaries (guardrails 1–3).

    Weighted mean times the attesting mass — equivalently `Σ(lift·mass)` — so an attester with twice
    the belief mass carries twice the recognition, and a swarm of ghosts (mass ≈ 0) carries ≈ 0."""
    usable, _ = _valid(attestations, actor)
    return _weighted_lift(usable)


def residual(attestations: Iterable[Attestation], *, actor: str, actor_cost: float) -> Residual:
    """The §13 residual: verified lift minus the actor's cost. This is what may mint.

    Cost is subtracted because the actor was already compensated for it through ordinary settlement,
    so minting recognizes the surplus beyond it. A non-positive residual mints nothing (guardrail 4):
    an act that cost more than it verifiably lifted has created no free energy, and recognizing one
    would be counterfeiting."""
    usable, excluded = _valid(attestations, actor)
    lift = _weighted_lift(usable)
    cost = max(0.0, float(actor_cost))
    minted = lift - cost
    if minted < 0.0:
        minted = 0.0                               # no surplus exists to recognize
    return Residual(
        verified_lift=lift, actor_cost=cost, minted=minted,
        attesters=len(usable), excluded_self=excluded,
        basis={"weighted_lift": lift, "cost": cost,
               "attesting_mass": float(sum(float(a.mass) for a in usable))},
    )


@dataclass(frozen=True)
class Mint:
    """A minting event: energy recognized into existence, credited to an origin, with its basis.
    `amount == residual.minted`; the basis is retained so the mint stays auditable (§12.1 —
    conservation is the audit, and a mint is a mint exactly when its basis re-derives)."""
    to_origin: str
    amount: float
    residual: Residual


def mint(attestations: Iterable[Attestation], *, actor: str, actor_cost: float,
         to_origin: Optional[str] = None) -> Mint:
    """Recognize the residual as free energy, credited to the actor's origin (or `to_origin` when the
    work grounds elsewhere — e.g. a foundation-grounded operator credits the foundation, see
    OPERATOR-ARCHITECTURE.md's grounding layers §13.11.7).

    Returns a Mint with `amount == 0.0` when nothing may be minted — an honest zero rather than an
    error, since "no verified surplus" is a legitimate, common and correct outcome."""
    r = residual(attestations, actor=actor, actor_cost=actor_cost)
    return Mint(to_origin=(to_origin or actor), amount=r.minted, residual=r)


def conservation_tolerance(r: Residual) -> float:
    """The float64 rounding this identity can accumulate — derived from the arithmetic that produced
    it rather than chosen.

    Derivation: the standard forward error bound for the computation in `residual`. `verified_lift`
    is a naive sum of `attesters` products, followed by one subtraction of `actor_cost`. Naive
    summation of `n` terms accumulates at most `n · eps · Σ|terms|`; the subtraction and the final
    comparison add two more roundings. So the bound is `eps · (n + 2) · scale`, where `scale` is the
    largest magnitude involved — the quantity float64 spaces its representable numbers by.

    Deriving it per residual is what makes it right across magnitudes. A single typed-in constant
    such as `1e-9` would be tighter than float64 can represent on a lift of 1e12 (so correct
    arithmetic would read as a conservation violation) and loose enough on a lift of 1e-6 to pass a
    real 0.1% discrepancy. The residual's own magnitude decides which regime the caller is in.

    The bound models two error sources, which is why it is stated here rather than taken from
    `prism.rounding.accumulated_rounding`. `(n + 2)` counts accumulation — the naive sum. `scale`
    covers cancellation: `verified_lift − actor_cost` subtracts two quantities that are routinely
    nearly equal (an actor whose costs almost exhaust the lift it verified is the ordinary case), and
    the error of such a subtraction is set by the granularity of the inputs rather than of the small
    result. So `scale` is `max(|verified_lift|, |actor_cost|, |minted|)`; taking the residual's own
    size instead systematically understates the bound whenever lift and cost nearly cancel, since
    the residual can be far smaller than either operand while the rounding error is set by their
    magnitude. `prism.rounding` bounds a sum of
    non-negative terms and says so, and this arithmetic contains a subtraction, so that bound would
    be too small here by however many orders of magnitude the cancellation costs. The discriminator
    between the two is whether a partial sum can be smaller than the one before it, and here it can.

    The `1.0` floor on `scale` is the unit at which absolute and relative error coincide, so an
    all-zero residual still admits one ulp rather than demanding exactness from arithmetic that
    cannot deliver it.
    """
    eps = sys.float_info.epsilon
    n = max(1, int(r.attesters))
    scale = max(abs(r.verified_lift), abs(r.actor_cost), abs(r.minted), 1.0)
    return eps * (n + 2) * scale


def conserves(m: Mint) -> bool:
    """The checkable identity every node agrees on: the minted amount is exactly the measured
    residual, and is bounded by the verified lift. Any node can run this on the retained basis.

    The tolerance is derived per residual (see `conservation_tolerance`), so two nodes holding the
    same basis agree both on the identity and on how much rounding it is allowed, across every
    magnitude of lift.
    """
    r = m.residual
    tol = conservation_tolerance(r)
    return (abs(m.amount - r.minted) <= tol
            and r.minted <= r.verified_lift + tol
            and r.minted >= 0.0)


__all__ = ["Attestation", "Residual", "Mint",
           "verified_lift", "residual", "mint", "conserves"]
