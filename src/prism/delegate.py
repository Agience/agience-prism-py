"""The delegate contract — what one agent's cognition looks like from outside.

A delegate is an agent's own screen, its own tick, its own memory. This module says what that is; it
does not say how a host builds one. That split is the point: a persona, a runner and a bare host all
need to agree about the shape, and none of them should have to import another to know it.

The invariants an implementation holds, one line each:
  * One screen per agent — a residual carries its witness, so pooled traces turn first-hand memory
    into hearsay while keeping the trust label.
  * One tick per agent — the tick is the observer's proper time, not a clock. Shared, a busy
    neighbour ages a quiet agent's memory out of existence without that agent doing anything.
  * Rates are fitted per agent — pooling two delegates' streams makes both inherit a decay neither
    earned, which is measurement contamination.
"""
from __future__ import annotations

from typing import Any, Dict, Protocol, runtime_checkable

#: The person a delegate belongs to when a host has no identity of its own yet.
LOCAL_PERSON = "local"
#: The issuer that stands for "this machine", before an Authority is joined.
LOCAL_ORIGIN = "urn:agience:issuer:local"
#: The screen a delegate persists between processes.
SCREEN_TYPE = "application/vnd.agience.screen+json"

__all__ = ["Delegate", "LOCAL_PERSON", "LOCAL_ORIGIN", "SCREEN_TYPE"]


@runtime_checkable
class Delegate(Protocol):
    """One agent's cognition — its screen, its tick, its memory, shared with no one.

    The surface a caller may rely on. An implementation carries far more (persistence, a registry, an
    observation store); what is declared here is what it means to be a delegate rather than to hold
    one particular class."""

    #: Whose cognition this is. Distinct delegates of one person are still distinct cognition.
    person: str

    @property
    def screen(self) -> Any:
        """The agent's own screen — the traces it has observed, and their residuals."""
        ...

    def next_tick(self) -> int:
        """Advance and return this agent's proper time: one tick is one observation step, never a
        clock reading. It is monotonic per agent and unrelated to any other agent's."""
        ...

    def observe(self, concept: Any) -> None:
        """Record that this agent observed `concept` — the witness is the point, not the count."""
        ...

    def provenance(self) -> Dict[str, str]:
        """Who this cognition speaks for: person / origin / host. What a claim is stamped with."""
        ...


def is_delegate(target: Any) -> bool:
    """Whether `target` is cognition rather than, say, a store.

    Prefer this to attribute-sniffing at call sites. It is a function rather than an `isinstance`
    repeated at each call site so that when the protocol grows a member, the question every caller
    is really asking ("did someone hand me cognition?") keeps one answer."""
    return isinstance(target, Delegate)
