"""Extraction policy — what channel a model-produced claim earns (MANTLE-MASS.md §3).

This is the gate between "a model said something" and "the corpus believes something". Get it
wrong and every hallucination acquires provenance, which is worse than having no provenance at
all: it is durable, citable, and teaches everything downstream.

Multi-model consensus raises the floor
----------------------------------------------------------
Running several open models and requiring them to corroborate is worth doing, but not for the
reason it first appears. The value is **asymmetric**:

* models **disagree** → a strong signal. Route it to a human.
* models **agree** → a weak signal. Suggestive, and short of proof.

Because LLMs are **not independent witnesses**. They share training corpora, so agreement is
correlated error as often as convergent evidence — three frontier models concurring is nearer
1.2 witnesses than 3. Any policy that treats N-model agreement as N-fold evidence is counting
the same source repeatedly and calling it corroboration.

So consensus decides whether an extraction is an `ASSERTION` (one model's quirk) or a
`HYPOTHESIS` (a prior that is at least *distributed*). It stops short of `SPAN_CITED`, because a
referent comes from a citation; where one exists the citation is what does the work.

The conservative bias — the part that fights the mission
--------------------------------------------------------
Consensus systematically favours what is *common in training data*. For a system whose purpose
is to capture novel and expert knowledge, naive consensus filtering would suppress exactly the
valuable material: a rare truth looks identical to a disagreement. A knowledge base built by
majority vote among language models converges on the median of the internet — which is the
opposite of the goal.

So disagreement is a reason to **escalate to a human** rather than to discard
(`needs_review`), which is the one input that can actually settle it — and which the economics
already price (`verifier`, in the contribution roles). The weakness becomes the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .mass import Provenance

# The panel rule is exact integer arithmetic: a panel agrees when a strict majority agrees,
# `n_agreeing * 2 > n_models`. No fraction, no rounding, no level.
#
# This module weighs multi-model consensus, and [[no-trained-weights]] is standing policy: all
# models out, including BYOK. Its own test is the only caller in the workspace ([[no-arcade-no-arango]]).

# Consensus is only meaningful across genuinely distinct models. Asking one model twice is an
# echo, not a panel — sampling the same weights again measures temperature, not truth.
MIN_PANEL = 2


def _majority(n_agreeing: int, n_models: int) -> bool:
    """A strict majority, in integers. Agreement starts above half the panel."""
    return int(n_agreeing) * 2 > int(n_models)


@dataclass(frozen=True)
class Extraction:
    """What a panel of models produced for one candidate claim, and how it was obtained."""

    n_models: int                      # distinct models consulted (not samples!)
    n_agreeing: int                    # how many concurred
    has_span_citation: bool = False    # a real span in a real source supports it
    human_reviewed: bool = False       # a person looked and kept it
    distinct_families: int = 1         # how many *unrelated* model families — see below

    @property
    def agreement(self) -> float:
        return (self.n_agreeing / self.n_models) if self.n_models else 0.0

    @property
    def contested(self) -> bool:
        """The models are split — no strict majority agrees. The most useful thing a panel can
        tell you, and an exact integer statement."""
        return self.n_models >= MIN_PANEL and not _majority(self.n_agreeing, self.n_models)

    @property
    def needs_review(self) -> bool:
        """Escalate to a human: contested, or asserted with nothing behind it."""
        if self.human_reviewed:
            return False
        return self.contested or (not self.has_span_citation and self.n_models < MIN_PANEL)


def rung_for_extraction(e: Extraction) -> Provenance:
    """The provenance an extraction has earned. Deliberately hard to climb.

    Order matters, and it encodes the whole thesis:

    1. a person kept it            -> HUMAN_VALIDATED  (what settles novelty)
    2. a span in a source backs it -> SPAN_CITED       (the citation does the work)
    3. a real panel concurs        -> HYPOTHESIS       (distributed prior, no referent yet)
    4. anything else               -> ASSERTION        (a ghost; marked as one)

    (2) beats (3): one model reading a document beats five models agreeing from memory, because the
    first has a referent and the second has a consensus.
    """
    if e.human_reviewed:
        return Provenance.HUMAN_VALIDATED
    if e.has_span_citation:
        return Provenance.SPAN_CITED
    if (e.n_models >= MIN_PANEL
            and _majority(e.n_agreeing, e.n_models)
            and e.distinct_families >= MIN_PANEL):
        # A panel of genuinely different families converged. Worth more than one model's word;
        # worth less than a single citation. `distinct_families` is required because three
        # checkpoints of one lineage are one witness wearing three hats.
        return Provenance.HYPOTHESIS
    return Provenance.ASSERTION


def independent_families(e: Extraction) -> int:
    """How many independent witnesses this panel actually represents.

    Agreement among correlated models is not N-fold evidence: five checkpoints of one lineage are
    one witness wearing five hats. So the count is distinct families, bounded by how many actually
    agreed, and a contested panel represents none.

    A plain count of independent witnesses — the same shape `prism.attestation` counts — so the
    first witness counts as one.
    """
    if e.contested:
        return 0
    return max(0, min(e.distinct_families, e.n_agreeing))


def describe(e: Extraction) -> dict:
    """The audit record: what was asked, what came back, and what it earned.

    Written alongside the artifact so a future reader can re-judge the decision rather than
    inherit it. The panel's composition is part of the provenance, not a runtime detail.
    """
    rung = rung_for_extraction(e)
    return {
        "provenance": rung.value,
        "n_models": e.n_models,
        "n_agreeing": e.n_agreeing,
        "distinct_families": e.distinct_families,
        "agreement": round(e.agreement, 3),
        "contested": e.contested,
        "needs_review": e.needs_review,
        "has_span_citation": e.has_span_citation,
        "independent_families": independent_families(e),
    }


__all__ = [
    "Extraction", "rung_for_extraction", "independent_families", "describe", "MIN_PANEL",
]
