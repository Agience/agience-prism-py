"""What a source is — the contract a corpus observer satisfies.

A source is a coalgebra: it unfolds a corpus rather than returning one. `poll()` yields the
observations that changed since it was last asked, so an open-ended world (a folder being edited, a
feed, a dataset being streamed) is consumed as a sequence of deltas rather than a snapshot.

Contracts are prism's, and this one is dependency-free: a dataclass and a Protocol. That is what lets
astra's fetchers and ember's disk watcher agree about what they produce without either importing the
other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Protocol, runtime_checkable

#: The provenance an observation carries by default: `Provenance.OBSERVED`, falling back to the
#: equivalent plain string on an install that does not carry `prism.mass`.
try:
    from prism.mass import Provenance
    _OBSERVED = Provenance.OBSERVED
except Exception:                                  # pragma: no cover - partial install
    _OBSERVED = "observed"

#: The artifact a source registers itself as.
SOURCE_CONTENT_TYPE = "application/vnd.agience.source+json"

__all__ = ["Observation", "Source", "SOURCE_CONTENT_TYPE"]


@dataclass
class Observation:
    """A single unit a source emits. Enters the store as dark matter (stored, undescribed)
    until a describe-operator illuminates it. Provenance is OBSERVED — Ember saw it.

    `to_doc()` renders it as the store document: id, content_type, state="committed", context,
    content, created_by="ember-source", provenance, plus any `meta` keys that do not collide."""
    id: str
    content: str
    content_type: str
    context: str = ""                       # offer, only if the source can describe; else dark
    provenance: str = _OBSERVED
    meta: Dict = field(default_factory=dict)

    def to_doc(self) -> dict:
        d = {"id": self.id, "content_type": self.content_type, "state": "committed",
             "context": self.context, "content": self.content, "created_by": "ember-source",
             "provenance": self.provenance}
        d.update({k: v for k, v in self.meta.items() if k not in d})
        return d

@runtime_checkable
class Source(Protocol):
    """A pluggable world-observer. `poll()` returns the observations that are new since the
    last poll (the coalgebra step). Stateful: it remembers what it has already seen."""
    name: str
    kind: str

    def poll(self) -> Iterable[Observation]: ...
