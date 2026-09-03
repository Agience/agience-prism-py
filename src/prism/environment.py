"""The prism and its capabilities — the environment an ember is grounded on, and the light it shines.

An organon (a real-world/observer interface) thrives only with the right light and the right substrate:
the substrate is the lattice it grounds on; the **light is the prism's capabilities** — the affordances
the *environment* provides so the organon can touch the world. Wrong prism → no light → the organon goes
honestly dark (dormant), never crashes.

A **capability** is a named, prism-provided affordance (`net.get`, `store.write`, `sensor.capture`, … from
`prism.capabilities.CAPABILITY_KINDS`): a probe (is it present *here*?) + a handle (how to do it). It is
measured and peer-local — a prism advertises it when the probe passes on this environment, so the
advertised set is an observation rather than a declared config. The organon codes against the abstract
name (`net.get`); the prism binds the concrete handle (httpx on a cloud box, a cellular modem on a Pi,
absent on an air-gap box) — same light, different lamp.

A **prism** is the environment: a peer-local bag of measured capabilities that advertises what it can do
here and provides the handle. Everything is an artifact — `artifact()` publishes the advertised set (like
peers-are-artifacts), content-addressed, seedable/loadable. The advertised set is re-measured on demand
(self-balancing on the continuum) rather than frozen: a capability that stops working drops off; one that
appears is picked up.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Dict, Iterable, Optional, Set

from .errors import CapabilityNotFound
from .canonical import canonical_string as _jcs_string

PRISM_CONTENT_TYPE = "application/vnd.agience.prism+json"


class Capability:
    """A named environmental affordance: a probe (present here?) + a handle (how). Measured, peer-local."""

    __slots__ = ("name", "handle", "_probe")

    def __init__(self, name: str, *, handle: Callable, probe: Optional[Callable[[], bool]] = None) -> None:
        self.name = name
        self.handle = handle
        self._probe = probe

    def present(self) -> Optional[bool]:
        """Is this capability measurably present right now? **True / False / None**, where None means
        unverified: nothing was measured, so there is no reading to give either way.

        The consequence: a capability with no probe is not advertised. A host asserting a structural
        fact supplies a trivially-true probe — which is what ember does
        (`ember.runtime.capability._probe_cpu` returns `True` unconditionally, and is still a probe).
        prism ships mechanism; the probes belong to the host.
        """
        if self._probe is None:
            return None
        try:
            return bool(self._probe())
        except Exception:  # noqa: BLE001 — a probe that errors is inconclusive, not a denial
            return None


class Prism:
    """The environment an ember is grounded on — a peer-local, measured bag of capabilities.

    `advertises()` is measured (it runs the probes) so it re-balances with the environment;
    `capability()` hands out the concrete affordance; `artifact()` publishes the prism as a
    content-addressed artifact.
    """

    def __init__(self, capabilities: Iterable[Capability] = (), *, node_id: str = "local") -> None:
        self._caps: Dict[str, Capability] = {c.name: c for c in capabilities}
        self.node_id = node_id

    def add(self, capability: Capability) -> "Prism":
        self._caps[capability.name] = capability
        return self

    def advertises(self) -> Set[str]:
        """The names this environment measurably provides right now — the probe ran and said yes.

        Unverified capabilities (no probe, or a probe that raised) stay out. This is the fail-closed
        direction: the discharge gate consumes this set as fact, so every name in it is one the host
        measured. Peer-local and self-balancing — re-measured every call rather than declared once.
        See `unverified()` for what was asked but not answered.
        """
        return {n for n, c in self._caps.items() if c.present() is True}

    def unverified(self) -> Set[str]:
        """Names that are declared but unmeasured — no probe, or a probe that raised.

        Kept distinct from absence, mirroring `ember.runtime.capability.unknown()`. A host that
        advertises nothing because it measured nothing is a different operational state from one that
        measured and found nothing; keeping them apart is what keeps "the GPU is missing" and "nobody
        looked for the GPU" separate reports. Nothing gates on this set — it exists so a report can say
        *"unverified"* instead of *"absent"*, which is the difference between "supply a probe" and "buy
        hardware".
        """
        return {n for n, c in self._caps.items() if c.present() is None}

    def capability(self, name: str) -> Callable:
        """The concrete handle for a capability. Raises if this prism does not (measurably) advertise it —
        which the discharge gate prevents upstream, so a raise here means someone skipped the gate."""
        if name not in self.advertises():
            raise CapabilityNotFound("prism %r does not advertise capability %r" % (self.node_id, name))
        return self._caps[name].handle

    def artifact(self) -> Dict[str, Any]:
        """Publish the prism as a content-addressed artifact — the advertised (measured) capability set.
        Everything is an artifact: this is how a peer announces its light (seedable/loadable).

        Body: `{id, content_type, node_id, capabilities, unverified, sha256}`, where `sha256` is
        taken over the canonical JSON of the other five fields."""
        body: Dict[str, Any] = {
            "id": "prism.%s" % self.node_id,
            "content_type": PRISM_CONTENT_TYPE,
            "node_id": self.node_id,
            "capabilities": sorted(self.advertises()),
            # Declared-but-unmeasured names, published so a reader can tell "this host has no GPU"
            # from "nobody probed for a GPU". A separate key rather than state folded into the
            # `capabilities` entries: changing that list's element type from `str` to an object is a
            # wire shape change and would have to land in prism-py, prism-js and prism-c together,
            # whereas an extra key is ignored by every existing reader.
            # `capabilities` therefore means exactly "measured yes".
            "unverified": sorted(self.unverified()),
        }
        body["sha256"] = hashlib.sha256(
            _jcs_string(body).encode("utf-8")
        ).hexdigest()
        return body


__all__ = ["Capability", "Prism", "PRISM_CONTENT_TYPE"]
