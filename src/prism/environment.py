"""The PRISM and its CAPABILITIES — the environment an ember is grounded on, and the light it shines.

An organon (a real-world/observer interface) thrives only with the right LIGHT and the right SUBSTRATE:
the substrate is the lattice it grounds on; the **light is the prism's capabilities** — the affordances
the *environment* provides so the organon can touch the world. Wrong prism → no light → the organon goes
honestly dark (dormant), never crashes.

A **capability** is a named, prism-provided AFFORDANCE (`net.get`, `store.write`, `sensor.capture`, … from
`prism.capabilities.CAPABILITY_KINDS`): a PROBE (is it present *here*?) + a HANDLE (how to do it). It is
MEASURED and PEER-LOCAL — a prism advertises it only if the probe passes on this environment, never as a
declared config. The organon codes against the abstract NAME (`net.get`); the prism binds the concrete
HANDLE (httpx on a cloud box, a cellular modem on a Pi, absent on an air-gap box) — same light, different
lamp.

A **prism** is the environment: a peer-local bag of measured capabilities that ADVERTISES what it can do
here and PROVIDES the handle. Everything is an artifact — `artifact()` publishes the advertised set (like
peers-are-artifacts), content-addressed, seedable/loadable. The advertised set is RE-MEASURED on demand
(self-balancing on the continuum), never frozen: a capability that stops working drops off; one that
appears is picked up. See `_scratch/PRISM-AND-CAPABILITIES.md`.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, Iterable, Optional, Set

from .errors import CapabilityNotFound
from .canonical import canonical_string as _jcs_string

PRISM_CONTENT_TYPE = "application/vnd.agience.prism+json"


class Capability:
    """A named environmental affordance: a PROBE (present here?) + a HANDLE (how). Measured, peer-local."""

    __slots__ = ("name", "handle", "_probe")

    def __init__(self, name: str, *, handle: Callable, probe: Optional[Callable[[], bool]] = None) -> None:
        self.name = name
        self.handle = handle
        self._probe = probe

    def present(self) -> Optional[bool]:
        """Is this capability MEASURABLY present right now? **True / False / None**, and None means
        UNVERIFIED — not present, not absent, NOT MEASURED.

        🔴 THIS USED TO RETURN `True` WHEN NO PROBE WAS SUPPLIED, and that was the dangerous polarity
        (fixed 2026-07-29, Contract Builder). `ember/capability.py` names its own signature defect as
        *"presenting an unmeasured host as a definitively-EMPTY one"*; prism did the exact mirror image
        and presented an unmeasured host as a definitively-**FULL** one. The mirror is worse, because
        emptiness closes gates and fullness OPENS them: with no probe registry anywhere in this repo,
        every capability on every real host was an unmeasured assertion that rendered as measured, and
        `Crystal.discharge`'s hardware gate consumed it as fact.

        ⚠ A RAISING PROBE IS NOW `None`, NOT `False`. It previously counted as definite absence, so an
        identical failed probe meant "not here" in prism and "not measured" in ember — two SDKs
        disagreeing about the same host. A probe that errors has told you nothing; `False` claims it told
        you something. `False` is reserved for a probe that ran and said no.

        The consequence, and it is deliberate: **a capability with no probe is not advertised.** A host
        that wants to assert a structural fact must supply a trivially-true probe — which is exactly what
        ember does (`_probe_cpu` returns `True` unconditionally, and is still a probe). prism ships
        MECHANISM only; it must not invent probes on a host's behalf.
        """
        if self._probe is None:
            return None
        try:
            return bool(self._probe())
        except Exception:  # noqa: BLE001 — a probe that errors is INCONCLUSIVE, not a denial
            return None


class Prism:
    """The environment an ember is grounded on — a peer-local, measured bag of capabilities.

    `advertises()` is MEASURED (runs the probes) so it re-balances with the environment; `capability()`
    hands out the concrete affordance; `artifact()` publishes the prism as a content-addressed artifact.
    """

    def __init__(self, capabilities: Iterable[Capability] = (), *, node_id: str = "local") -> None:
        self._caps: Dict[str, Capability] = {c.name: c for c in capabilities}
        self.node_id = node_id

    def add(self, capability: Capability) -> "Prism":
        self._caps[capability.name] = capability
        return self

    def advertises(self) -> Set[str]:
        """The names this environment MEASURABLY provides right now — probe ran and said YES.

        Now excludes UNVERIFIED capabilities (probe absent, or probe raised). This is the fail-closed
        direction: the discharge gate consumes this set as fact, so an unmeasured name in here is an
        unearned authorization. Peer-local and self-balancing — re-measured every call, never a frozen
        declaration. See `unverified()` for what was asked but not answered, and `Capability.present()`
        for why the polarity changed.
        """
        return {n for n, c in self._caps.items() if c.present() is True}

    def unverified(self) -> Set[str]:
        """Names that are DECLARED but NOT MEASURED — no probe, or a probe that raised.

        Kept distinct from absence on purpose, mirroring `ember.capability.unknown()`. A host that
        advertises nothing because it measured nothing is a completely different operational state from
        one that measured and found nothing, and collapsing them is how "the GPU is missing" and "nobody
        looked for the GPU" become the same report. Nothing gates on this set — it exists so a refusal
        can say *"unverified"* instead of *"absent"*, which is the difference between "supply a probe"
        and "buy hardware".
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
        Everything is an artifact: this is how a peer announces its light (seedable/loadable)."""
        body: Dict[str, Any] = {
            "id": "prism.%s" % self.node_id,
            "content_type": PRISM_CONTENT_TYPE,
            "node_id": self.node_id,
            "capabilities": sorted(self.advertises()),
            # ADDITIVE (2026-07-29, Contract Builder): declared-but-unmeasured names, published so a
            # reader can tell "this host has no GPU" from "nobody probed for a GPU". Kept as a separate
            # key rather than folding state into `capabilities` entries, deliberately: changing that
            # list's element type from `str` to an object is a WIRE shape change and must land in
            # prism-py, prism-js and prism-c together (NEXT.md §5.2), whereas an extra key is ignored by
            # every existing reader. `capabilities` therefore still means exactly "measured YES".
            "unverified": sorted(self.unverified()),
        }
        body["sha256"] = hashlib.sha256(
            _jcs_string(body).encode("utf-8")
        ).hexdigest()
        return body


__all__ = ["Capability", "Prism", "PRISM_CONTENT_TYPE"]
