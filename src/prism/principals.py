"""What kind of principal a subject names — one question, one home, no dependencies.

`created_by` is a vertex reference to a who. Some of those whos are people and some are programs,
and more than one component tells them apart:

  * `mantle/person.py` mints a person artifact for one and a foundation entity for the other, and
    `person_id` dispatches on it, so a wrong answer writes
    `application/vnd.agience.person+json` for an ingest program — a false claim about a human.
  * `crystal/evolution.py` reads it for `preserve_fitness`'s creator-clobber guard: a
    re-registration by a process author leaves a resolved human creator in place.

One home, because two copies of a list drift as soon as a name is added to one of them.
`crystal ↔ mantle` is 0 in both directions, ratcheted by `test_process_authors_single_home.py`'s
AST scan, so neither imports the other; both depend on prism, and prism's base install has no
dependencies at all. This module is that shared leaf and holds nothing else.

It sits here rather than in `prism/grounding.py`, whose `__all__` is fenced by
`agience-ember/tests/test_grounding_is_not_the_law.py`. Grounding is the runner's small surface —
the provenance rungs, the triple type, the transducer op-id, the clock — and what kind of principal
a subject names is a separate question.

Seam: the membership is typed in, and the answer it gives is a recall rather than a measurement.
Every name below is a string a human added, so a program that starts writing rows is classified a
person until the set is edited. What separates the two is observable: a person's subject arrives
with an issuer assertion behind it (a token, an `iss` claim), while a process author arrives as a
default string in code with nothing asserting it. Deriving the test — "was this subject asserted by
an issuer" — is a real change rather than a rename, because `mantle/lattice_mint._author_ref`
receives only the bare string and the assertion is known further up, at the caller.

Absence from this set reads as unmeasured, rather than as evidence that a subject is a person.
([[absence-is-not-an-affirmative-claim]])
"""
from __future__ import annotations

#: Author subjects that name programs. Each one authored rows on the live shard. Dropping a name
#: raises nowhere; it re-mints that author as a person on the next write, which is both a false
#: claim and a second, colliding identity for the same program.
#:
#:   ember-source, ember-local   the ingest and the local runner
#:   sage-canon                  `sage/canon.py`'s default author — the canon ingest, carried as a
#:                               bare subject with no artifact behind it, so `created_by resolves`
#:                               fails on it.
#:   probe@local                 the write-lock probe (`probe.writelock.test`).
PROCESS_AUTHORS = frozenset({"ember-source", "ember-local", "sage-canon", "probe@local"})


def is_process_author(sub: str) -> bool:
    """True for an author subject that names a program rather than a person.

    A membership test: it states what the subject is, and leaves what may be done with it to the
    caller. Minting a foundation entity instead of a person, and the fitness creator-clobber guard,
    are two different consequences drawn by two different callers from this one fact.
    """
    return (sub or "").strip() in PROCESS_AUTHORS


__all__ = ["PROCESS_AUTHORS", "is_process_author"]
