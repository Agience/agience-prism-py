"""Attestation — what one observer actually saw, and what agreement is made of.

**Existence is observer agreement.** This module is that sentence made computable.

What an attestation is
──────────────────────
What one authority, from its own position, actually observed:

    (item_id, content_hash, authority, origin, channel)

Three of those already ride on the wire — the manifest is signed by an `authority`, and every
`ShardItem` carries its `id` and content `hash`. The two that make agreement measurable are who
originated it, and how this observer got it.

`origin` is the load-bearing field, and the reason is the echo problem. Agreement counts **distinct
origins rather than distinct holders**, so N replicas of one origin are one observation. Counting
origins carries the anti-laundering property arithmetically: a replica is not a witness.

That covers the replicated case. Two genuinely distinct origins that read the same upstream source
are still one observation, and a count cannot see it — that takes the spectral read (`resolvable`
over the attestation frame: correlated rows do not add a mode). This module is the channel that read
consumes.

No constants, and none are needed
─────────────────────────────────
The quantity here is an integer: how many independent origins attest the modal hash. Integers need
no tie-break, so this file holds no epsilon and no band edge. The three readings are:

  * **nothing attests it** → `read()` is `None`. That is the ghost, derived from the ledger.
  * **the observers tie** → `resolved` is False. A plurality that is not strict is not agreement,
    and `max > second` is a comparison.
  * **otherwise** → `agreeing` is the count of independent origins behind the agreed hash.

`None` is distinct from zero. An item nobody has attested and an item measured to have no support
are different claims, and the second is outside what this module can express — an absence of
observers is not something an observer records. Absence stays absence.

Legacy: held, but unattributed
──────────────────────────────
Artifacts written before this existed carry no `origin` — the field did not exist. They are
recorded as **held but unattributed**: counted as holders, reported separately by
`AgreementRead.unattributed`, and left out of the agreeing origins.

Attributing each one to its holder would be the echo problem by another door — every replica of one
legacy item would count as its own independent origin, so the corpus with the least provenance would
read as the most corroborated. A corpus that never recorded origin says so, and the remedy is
migration: record an origin and it is re-read.

Dependency-free (stdlib only), and in `prism` for the same reason `mass` is: the server and the
leaf compute agreement identically, so belief stays single-valued at the edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set

from .mass import Revision

# The `origin` an authority records for content it authored itself. A literal, resolved against the
# attesting authority's own id at record time, so what travels is always a concrete authority id.
SELF_ORIGIN = "self"


@dataclass(frozen=True)
class Attestation:
    """One observer's statement about one item. Frozen and hashable — a set of these IS the
    evidence, and an authority re-publishing the same row is not a new observation.

    ``origin`` empty means *unattributed*: this observer holds the bytes and cannot say who
    originated them. That is a real and common state — every artifact written before this module —
    and it is a different statement from originating them.
    """

    item_id: str
    content_hash: str
    authority: str
    origin: str = ""
    channel: str = ""

    @property
    def attributed(self) -> bool:
        return bool(self.origin)


@dataclass(frozen=True)
class AgreementRead:
    """What the ledger currently resolves about one item.

    Every field is a count or a set of ids, so a read compares with another read of the same kind.
    """

    item_id: str
    holders: FrozenSet[str] = frozenset()          # authorities holding it, attributed or not
    unattributed: FrozenSet[str] = frozenset()     # holders that could not name an origin
    by_hash: Dict[str, FrozenSet[str]] = field(default_factory=dict)   # hash -> attributed origins

    # ---------------------------------------------------------------- the counts
    @property
    def origins(self) -> int:
        """Distinct attributed origins across every hash. Replicas of one origin count once —
        that is the point of counting origins rather than holders."""
        seen: Set[str] = set()
        for o in self.by_hash.values():
            seen |= set(o)
        return len(seen)

    @property
    def contested(self) -> bool:
        """More than one distinct content hash is attested — genuine disagreement about what the
        item is."""
        return len(self.by_hash) > 1

    # ---------------------------------------------------------------- the whether
    @property
    def _ranked(self) -> List[tuple]:
        """(hash, origin_count) for hashes with at least one attributed origin, strongest first."""
        ranked = [(h, len(o)) for h, o in self.by_hash.items() if o]
        ranked.sort(key=lambda t: t[1], reverse=True)
        return ranked

    @property
    def resolved(self) -> bool:
        """Do the observers agree on which bytes this item is?

        A strict plurality, and strict is the whole content of the property: two hashes on equal
        origin counts is disagreement, and a reported winner would be one this ledger invented.
        `max > second` is a comparison."""
        ranked = self._ranked
        if not ranked:
            return False                    # held by someone, attributed by no-one
        return len(ranked) == 1 or ranked[0][1] > ranked[1][1]

    @property
    def agreed_hash(self) -> Optional[str]:
        """The content hash the independent origins agree on, or None when unresolved."""
        return self._ranked[0][0] if self.resolved else None

    @property
    def agreeing(self) -> Optional[int]:
        """**Existence in degrees**: how many independent origins attest the agreed bytes.

        `None` when nothing is attributed or the observers tie — unresolved, which is a different
        reading from zero. This is what the mesh path reads for existence: a count of witnesses
        rather than a lookup from a label."""
        return self._ranked[0][1] if self.resolved else None


class Ledger:
    """Attestations, indexed by item. A node folds every manifest it has verified into one of
    these, and reads agreement out of it.

    Verified, rather than merely received. Verification happens upstream, in
    `mesh.node.import_shard`, where a shard's signature, item hashes and content_root are
    established; this class stores the results. Folding an unverified manifest in here would let an
    unauthenticated peer manufacture origins, which is the laundering the origin count exists to
    prevent.
    """

    def __init__(self) -> None:
        self._by_item: Dict[str, Set[Attestation]] = {}

    # ---------------------------------------------------------------- write
    def record(self, att: Attestation) -> None:
        """Fold in one observation. Idempotent by construction: the same authority stating the
        same thing twice is one observation, and a `set` of frozen rows says so without a check."""
        self._by_item.setdefault(att.item_id, set()).add(att)

    def observe(self, authority: str, items: Iterable[dict]) -> None:
        """Fold every `ShardItem` of one verified manifest in, as that manifest's authority.

        Takes the raw item dicts rather than a `ShardManifest` so this module keeps no dependency
        on `mantle` — `prism` is below it, and the leaf and the server must share this code.

        An item whose recorded origin is `SELF_ORIGIN` is resolved to the attesting authority's own
        id here, at the boundary. "self" is meaningful relative to who said it, so it is resolved
        before anything stores or compares it.
        """
        for si in items:
            try:
                item_id = str(si["id"])
                content_hash = str(si["hash"])
            except (KeyError, TypeError):
                continue                     # a malformed row is not an observation
            origin = str(si.get("origin") or "")
            if origin == SELF_ORIGIN:
                origin = authority
            self.record(Attestation(item_id=item_id, content_hash=content_hash,
                                    authority=authority, origin=origin,
                                    channel=str(si.get("channel") or "")))

    # ---------------------------------------------------------------- read
    def read(self, item_id: str) -> Optional[AgreementRead]:
        """What is agreed about this item, or `None` when nothing attests it.

        `None` is the ghost — coordinates with no observer behind them — and it is derived from
        the ledger rather than set as a floor."""
        rows = self._by_item.get(item_id)
        if not rows:
            return None
        by_hash: Dict[str, Set[str]] = {}
        holders: Set[str] = set()
        unattributed: Set[str] = set()
        for a in rows:
            holders.add(a.authority)
            if a.attributed:
                by_hash.setdefault(a.content_hash, set()).add(a.origin)
            else:
                unattributed.add(a.authority)
                by_hash.setdefault(a.content_hash, set())
        return AgreementRead(item_id=item_id, holders=frozenset(holders),
                             unattributed=frozenset(unattributed),
                             by_hash={h: frozenset(o) for h, o in by_hash.items()})

    def items(self) -> List[str]:
        return sorted(self._by_item)

    def __len__(self) -> int:
        return len(self._by_item)


def displaces(current: Optional[AgreementRead], incoming: Optional[AgreementRead]) -> "Revision":
    """Retired: calling this always raises. Kept in `__all__` so a caller reaching for it by name
    finds the reasoning here rather than an `ImportError`.

    A count of independent origins measures agreement, and agreement is a different quantity from
    validity, so no count can decide which version answers a query. `prism.resolution.separated`
    makes that precise: at n=2 the computed null is exactly 1.0000, so no pair of counts is ever
    separable, and a `>=` comparison between two counts would be a confident answer computed from
    nothing.

    Every revision commits and stands (`mantle.shard.cache.revise` returns `Landed`); which one
    answers a query is resolved at read time by the reader's own measurement, injected as a seam
    since the aperture lives in the optics package below both prism and mantle.

    `agreeing` itself stands as a reading of agreement, which is a reading of existence
    [[existence-is-observer-agreement]] — a count, used as one.
    """
    raise NotImplementedError(
        "displaces() is retired: head was decided by attestation count, and a count of independent "
        "origins measures AGREEMENT, not validity. prism.resolution.separated() refuses the "
        "comparison outright (at n=2 the computed null is 1.0000, so no pair of counts is "
        "separable). Every revision now stands; resolve which one answers AT READ TIME with the "
        "reader's own measurement — see mantle.shard.cache._answering.")


__all__ = ["Attestation", "AgreementRead", "Ledger", "displaces", "SELF_ORIGIN"]
