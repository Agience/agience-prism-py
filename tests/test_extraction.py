"""Extraction policy: consensus raises the floor, never the ceiling.

The invariant these pin: no panel of models, however large or unanimous, can manufacture a
referent. If that ever breaks, every hallucination gets provenance and the corpus is worthless.

The invariant is stated where it lives: `mass.REFERENT` is a partition, and no amount of agreement
moves a channel across it. `has_referent` is the whole test, and it has no edge for a large enough
panel to creep over.
"""
from __future__ import annotations

from prism.extraction import (
    MIN_PANEL, Extraction, describe, independent_families, rung_for_extraction,
)
from prism.mass import Provenance, has_referent


def test_one_model_is_an_assertion() -> None:
    """One model's word is unbacked, no matter how confident it sounded."""
    e = Extraction(n_models=1, n_agreeing=1)
    assert rung_for_extraction(e) is Provenance.ASSERTION
    assert not has_referent(rung_for_extraction(e))


def test_a_real_panel_earns_hypothesis_and_no_more() -> None:
    """Distributed prior: better than one model's quirk, still no referent."""
    e = Extraction(n_models=3, n_agreeing=3, distinct_families=3)
    assert rung_for_extraction(e) is Provenance.HYPOTHESIS


def test_consensus_can_never_reach_a_citation() -> None:
    """The invariant, and a failure mode that is expressible.

    A unanimous panel of a hundred unrelated families still has no referent; one model reading a
    document does. Stated over the partition, the check fails the moment `rung_for_extraction`
    returns anything in `REFERENT` for a panel — which is exactly the laundering it guards."""
    unanimous = Extraction(n_models=100, n_agreeing=100, distinct_families=100)
    assert rung_for_extraction(unanimous) is Provenance.HYPOTHESIS
    assert not has_referent(rung_for_extraction(unanimous)), \
        "a panel manufactured a referent — agreement laundered into evidence"
    # ...and scale changes nothing, because there is no edge to creep over.
    for n in (2, 10, 1000, 10_000):
        panel = Extraction(n_models=n, n_agreeing=n, distinct_families=n)
        assert not has_referent(rung_for_extraction(panel))


def test_one_model_with_a_citation_beats_five_agreeing_from_memory() -> None:
    """The inversion of the usual instinct, and the point: a referent beats a consensus."""
    cited = Extraction(n_models=1, n_agreeing=1, has_span_citation=True)
    panel = Extraction(n_models=5, n_agreeing=5, distinct_families=5)
    assert rung_for_extraction(cited) is Provenance.SPAN_CITED
    assert has_referent(rung_for_extraction(cited))
    assert not has_referent(rung_for_extraction(panel))


def test_same_family_repeated_is_one_witness_wearing_hats() -> None:
    """Three checkpoints of one lineage is not a panel. Sampling one model repeatedly measures
    temperature, not truth."""
    echo = Extraction(n_models=3, n_agreeing=3, distinct_families=1)
    assert rung_for_extraction(echo) is Provenance.ASSERTION
    assert independent_families(echo) == 1, "one lineage is one witness — not zero, and not three"


def test_correlated_agreement_is_discounted() -> None:
    """LLMs share training corpora, so agreement is correlated error as often as convergent
    evidence. Count distinct families, not raw headcount."""
    assert independent_families(Extraction(n_models=5, n_agreeing=5, distinct_families=1)) == 1
    assert independent_families(Extraction(n_models=5, n_agreeing=5, distinct_families=3)) == 3


def test_disagreement_escalates_rather_than_discards() -> None:
    """The conservative-bias guard. A rare truth looks exactly like a disagreement, so a system
    that discards on dissent converges on the median of the internet — the opposite of the goal.
    Contested claims go to a human (whose role the economics already price)."""
    split = Extraction(n_models=3, n_agreeing=1, distinct_families=3)
    assert split.contested
    assert split.needs_review, "dissent must escalate to a person, not vanish"
    assert independent_families(split) == 0, "a split panel represents no agreed witness"
    # ...and it is not silently discarded: it still has a channel, just an ungrounded one.
    assert rung_for_extraction(split) is Provenance.ASSERTION


def test_a_human_settles_it() -> None:
    """The irreducible input. Novel claims with no source can only be settled by reality —
    a person, an instrument, an experiment."""
    e = Extraction(n_models=3, n_agreeing=1, distinct_families=3, human_reviewed=True)
    assert rung_for_extraction(e) is Provenance.HUMAN_VALIDATED
    assert not e.needs_review
    assert has_referent(rung_for_extraction(e))


def test_split_is_a_strict_majority_in_integers() -> None:
    """A 2-of-3 panel is the smallest real majority there is, and this pins that the contested
    check computes it in integers rather than a float threshold: a fraction like 2/3 has no exact
    binary float representation, so a threshold compared against one can misclassify the boundary
    case it exists to catch."""
    assert not Extraction(n_models=3, n_agreeing=2).contested, \
        "2 of 3 is a strict majority; the old float threshold called it split"
    assert Extraction(n_models=4, n_agreeing=2).contested, "an even split is not a majority"
    assert not Extraction(n_models=4, n_agreeing=3).contested


def test_describe_is_a_re_judgeable_record() -> None:
    """Provenance must record what was asked and what came back, so a future reader can
    re-judge the decision instead of inheriting it."""
    d = describe(Extraction(n_models=3, n_agreeing=2, distinct_families=2))
    assert d["provenance"] and "agreement" in d and "distinct_families" in d
    assert d["needs_review"] is False         # 2 of 3 is a strict majority — see the test above
    assert set(d) >= {"n_models", "n_agreeing", "contested", "has_span_citation",
                      "independent_families"}


def test_min_panel_is_enforced() -> None:
    assert MIN_PANEL >= 2
    assert rung_for_extraction(Extraction(n_models=1, n_agreeing=1, distinct_families=1)) \
        is Provenance.ASSERTION
