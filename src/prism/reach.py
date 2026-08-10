"""Signal-native reach — one activation propagates from where it enters to where it resolves, and the
evidence returns through the ground plane. The comm plane carries propagation rather than MCP-style
request/response, and the return path is a ground connection plus provenance rather than a
point-to-point return address — the way a circuit completes.

The circuit. A signal carries no return wire (`reply_to`); lightning and current complete the circuit
through the shared ground plane. The requester and the provider are both connected to that plane — the
shared substrate (the comm plane / lattice / mesh: a common collection on the light-cone surface). A
requester places a need; it propagates to wherever it resolves (lightning — live if a provider is up,
the durable store-and-forward floor otherwise); the provider absorbs it, condenses evidence, and
discharges the evidence onto the ground plane; the requester, connected to the same ground, picks it
up. The ground plane is the return path.

Correlation is provenance. Every propagation is an artifact with provenance (the lattice puts
provenance on every artifact). The need is an artifact — its provenance origin is the requester, and
its id is the reach handle. The evidence is an artifact whose provenance references the need
(`in_reply_to = <need id>`, `root = <originating need id>`). Each residual hop is a tracked artifact
(`derived_from = <parent need id>`, same `root`). The requester finds its answer by following
provenance on the ground — collecting evidence whose `root` is its handle. The need artifact's own id
is the one correlation handle.

Envelope / payload. The envelope is MCP-like and its routing fields are provenance (cleartext:
`to`/`origin`/`hlc`/`id`/`root`/`in_reply_to`/`derived_from`/`path`); the payload is signal-native and
AES-256-GCM-sealed. Isolation is the plane's, cryptographic: a need is sealed with the capability's
group key, so a provider whose light-cone reaches the capability opens the question; evidence is sealed
with the ground collection's key, so whoever is connected to that ground — reaches it in their
light-cone — reads the answer, and provenance says whose answer it is. The provenance is bound inside
the sealed body too, so a forged cleartext link is caught on open (AEAD-authenticated).

The handler is injected (a plain `need -> evidence` callable), so this module imports no ember / lumen /
sage. Degrades to store-and-forward when nothing is live. See `agience-pharos/genesis/SIGNAL-PROTOCOL.md` and the reach
row of `agience-pharos/genesis/TEST-ARCHITECTURE.md`.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Dict, List, Optional

from .plane import HLC, Keyring, Lightcone, open_sealed, seal
from . import instrument as _instrument
from .canonical import canonical_string as _jcs_string   # one canonicaliser for the whole workspace

# ── MCP-like envelope content types — a need signal and the evidence that answers it ──────────────────
NEED_CT = "application/vnd.agience.need+json"
EVIDENCE_CT = "application/vnd.agience.evidence+json"

# The default ground plane — the shared return surface. A well-known collection both requester and provider
# connect to (reach in their light-cones). Real deployments ground on the mesh/lattice; a session may
# ground on a private collection. It is a connection property, held outside the signal itself.
GROUND = "ground"

# ── the false-alarm level is a property of the null, so the router takes a null ───────────────────────
# Entroptics' `null_providers` header states it: the cutoff is one decision, so the provider owns both
# the threshold and the alpha it is drawn at, and a provider that pins its own level uses that level
# for any `far` passed beside it.
#
# `Provider(..., null=...)` is the surface. An observer on a noisier substrate hands this router a null
# that holds its opinion (`correlated_null(far=…)` / `derived_null(far=…)` from the optics package),
# and the level travels with the cutoff it sets. `null=None` runs on entroptics' own derived default —
# the library's number, left in the library.


# ── the membrane seam: absorb the coupled band, propagate the residual ────────────────────────────────
class Absorption:
    """A tekton's response at one hop of the membrane. A signal stays intact along its whole path; each
    tekton it reaches absorbs the band that couples to it (condensed → `evidence`, discharged to the ground
    plane) and transmits the `residual` it did not couple to onward to the next coupling capability (`to`).
    Conservation: incident = absorbed ⊕ residual.

      - Fully absorbed  → `residual=None`: the signal terminates here (single-hop is this case).
      - Partial couple  → `residual` (+ a next `to`): the remainder keeps propagating (multi-hop), each hop
                          shrinking it, until fully absorbed or it reaches a capability with no provider.
      - Pass-through    → `evidence=None`: this tekton coupled nothing; only the residual moves on.

    A handler may return a plain value instead of an `Absorption` — the fully-absorbed shorthand
    (`evidence=value, residual=None`). The seam is: measure coupling → absorb → transmit the residual.
    Coupling selects the next hop, so the address is a measurement rather than a table lookup."""

    __slots__ = ("evidence", "residual", "to")

    def __init__(self, evidence: Any = None, *, residual: Any = None, to: Optional[str] = None) -> None:
        self.evidence = evidence
        self.residual = residual
        self.to = to


def _split(result: Any):
    """Normalize a handler result to (absorbed, residual, next_to). A bare value = fully absorbed."""
    if isinstance(result, Absorption):
        return result.evidence, result.residual, result.to
    return result, None, None


# ── artifact ids + envelopes (every propagation is a tracked artifact) ─────────────────────────────────
def _artifact_id(origin: str, to: str, hlc: str, kind: str, sealed: str) -> str:
    """Content-addressed artifact id → idempotent on the ground (a replayed artifact is deduped) and the
    reach handle (the need's provenance id)."""
    body = _jcs_string({"origin": origin, "to": to, "hlc": hlc, "kind": kind, "sealed": sealed})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _need_artifact(*, to: str, origin: str, hlc: str, need: Any, root: Optional[str],
                   derived_from: Optional[str], path: List[str], keyring: Keyring) -> Dict[str, Any]:
    """A need artifact placed on the plane, addressed to capability `to`, sealed with `to`'s key (the
    question is scoped to who can answer). Provenance: `id` (its own hash), `origin` (who placed it),
    `root` (the originating need — its own id for a fresh reach), `derived_from` (the parent need for a
    residual hop), `path` (capabilities already coupled — a derived termination, since coupling is
    idempotent and a revisit would absorb nothing)."""
    bound = {"derived_from": derived_from, "cap": to, "need": need}   # sealed → authenticates the envelope
    sealed = seal(bound, keyring.group_key(to), aad=to)
    aid = _artifact_id(origin, to, hlc, "need", sealed)
    return {"content_type": NEED_CT, "to": to, "origin": origin, "hlc": hlc, "id": aid,
            "root": root or aid, "derived_from": derived_from, "cap": to,
            "path": list(path or [to]), "sealed": sealed}


def _evidence_artifact(*, ground: str, origin: str, hlc: str, evidence: Any, in_reply_to: str, root: str,
                       cap: str, keyring: Keyring) -> Dict[str, Any]:
    """An evidence artifact discharged onto the ground plane, sealed with the ground collection's key
    (whoever is connected to that ground reads it). Provenance references the need: `in_reply_to` (the need
    it answers), `root` (the originating need = the requester's handle), `cap` (who answered)."""
    bound = {"in_reply_to": in_reply_to, "root": root, "evidence": evidence}
    sealed = seal(bound, keyring.group_key(ground), aad=ground)
    aid = _artifact_id(origin, ground, hlc, "evidence", sealed)
    return {"content_type": EVIDENCE_CT, "to": ground, "origin": origin, "hlc": hlc, "id": aid,
            "in_reply_to": in_reply_to, "root": root, "cap": cap, "sealed": sealed}


def _stamp(hlc: Any) -> str:
    return hlc.tick() if hasattr(hlc, "tick") else str(hlc)


def _propagate(transport: Any, to: str, leaf: Dict[str, Any], fallback: Any = None) -> str:
    """Lightning — the least-cost path. Over a live fabric, deliver live if a receiver is up (the fast
    path); else degrade to a durable carrier (the store-and-forward floor). A bare carrier is the floor.
    The plane behaves the same whichever path carried the artifact."""
    if hasattr(transport, "deliver_live"):
        if transport.deliver_live(to, leaf):
            return "live"
        fb = fallback if fallback is not None else getattr(transport, "fallback", None)
        if fb is not None:
            fb.put(leaf)
            return "degraded"
        return "dropped"
    transport.put(leaf)                                  # a carrier — store-and-forward
    return "stored"


# ── the primitive: place a need, it propagates to where it resolves ───────────────────────────────────
def reach(transport: Any, need: Any, *, to: str, keyring: Keyring, node: str, hlc: Any,
          fallback: Any = None) -> str:
    """Place a need signal addressed to capability/persona `to`; it propagates to wherever it resolves.
    Returns the reach handle — the need artifact's provenance id. The evidence comes back through the
    ground plane: a provider absorbs the need and discharges evidence whose provenance references this
    handle (`root`), and the requester, connected to the same ground, picks it up by following
    provenance (`Requester`/`Reactor.evidence(handle)`).

    This places the signal and returns, rather than blocking like an RPC. The need is sealed with `to`'s
    group key, so a provider whose light-cone reaches `to` opens the question — isolation is the plane's,
    cryptographic."""
    leaf = _need_artifact(to=to, origin=node, hlc=_stamp(hlc), need=need, root=None,
                          derived_from=None, path=[to], keyring=keyring)
    _propagate(transport, to, leaf, fallback=fallback)
    return leaf["id"]                                    # the handle = the need artifact's own provenance id


# ── the provider side: absorb a need, discharge evidence onto the ground ───────────────────────────────
class Provider:
    """A capability's receiver. On a need addressed to its capability it opens the question (key-gated by
    the light-cone), invokes the injected `handler(need) -> evidence`, and discharges the evidence onto the
    ground plane (sealed with the ground key) with provenance referencing the need. Idempotent: a
    re-delivered need is handled once (dedup by artifact id). A receiver whose principal is outside the
    light-cone runs and opens nothing."""

    def __init__(self, capability: str, handler: Callable[[Any], Any], *, keyring: Keyring,
                 lightcone: Lightcone, principal: str, node: str, hlc: Any, ground: str = GROUND,
                 outbound: Any = None, fallback: Any = None, bases: Optional[Dict[str, Any]] = None,
                 null: Any = None, embodiment: Any = None) -> None:
        self.capability = capability
        self._handler = handler
        self._null = null                      # the caller's noise provider — see the note above
        self._embodiment = embodiment          # the instrument — see `_route_next`; None = the host's
        self._bases = dict(bases or {})        # {capability: (F,k) coupling basis} — see `_route_next`
        self._keyring = keyring
        self._reach = lightcone.reaches(principal)             # what this provider is entitled to open
        self._keys = keyring.principal_keys(principal, lightcone)
        self._node = node
        self._hlc = hlc
        self._ground = ground                                  # this provider's connection to ground
        self._outbound = outbound
        self._fallback = fallback
        self._seen: set = set()                                # need ids handled → idempotent
        self.handled: Dict[str, Any] = {}                      # need id -> absorbed band (audit)

    def on_leaf(self, leaf: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if leaf.get("content_type") != NEED_CT:
            return None
        if leaf.get("to") != self.capability:
            return None
        if leaf.get("to") not in self._reach:                  # isolation: outside the light-cone
            return None
        if leaf.get("id") in self._seen:                       # idempotent: re-delivery → no dup
            return None
        opened = open_sealed(leaf["sealed"], self._keys, aad=leaf.get("to", ""))
        if opened is None:                                     # isolation: the key opens nothing here
            return None
        if opened.get("cap") != leaf.get("cap") or opened.get("derived_from") != leaf.get("derived_from"):
            return None                                        # adversarial: forged provenance
        self._seen.add(leaf["id"])
        need_id = leaf["id"]
        root = leaf.get("root", need_id)                       # the originating need = the handle
        path = list(leaf.get("path", [self.capability]))

        # The membrane hop: measure coupling → absorb the coupled band → transmit the residual onward.
        absorbed, residual, next_to = _split(self._handler(opened.get("need")))
        self.handled[need_id] = absorbed

        ev = None
        if absorbed is not None:                               # absorb: condense → discharge onto the ground
            ev = _evidence_artifact(ground=self._ground, origin=self._node, hlc=_stamp(self._hlc),
                                    evidence=absorbed, in_reply_to=need_id, root=root,
                                    cap=self.capability, keyring=self._keyring)
            if self._outbound is not None:
                _propagate(self._outbound, self._ground, ev, fallback=self._fallback)

        # Coupling selects the next hop, and it does so when the handler left `to` open and
        # this provider was given coupling bases. A provider with no bases stays handler-directed.
        if next_to is None and self._bases:
            next_to, residual = self._route_next(absorbed, residual, path)

        # Transmit: the residual keeps propagating to the next coupling capability, carrying the same root
        # (provenance lineage) and `derived_from` this need, as long as it has not already coupled there.
        # The path guard is a derived bound — coupling is idempotent, so a revisit would absorb nothing.
        if residual is not None and next_to is not None and next_to not in path:
            nleaf = _need_artifact(to=next_to, origin=self._node, hlc=_stamp(self._hlc), need=residual,
                                   root=root, derived_from=need_id, path=path + [next_to],
                                   keyring=self._keyring)
            if self._outbound is not None:
                _propagate(self._outbound, next_to, nleaf, fallback=self._fallback)

        return ev                                              # the evidence artifact discharged (or None)

    def _route_next(self, absorbed: Any, residual: Any, path: List[str]):
        """Pick the next hop by measured coupling. Returns `(next_to, residual)`.

        This is what makes `Absorption`'s "coupling selects the next hop" literal: the
        address is an argmax over coupling readings rather than a name the handler supplied
        ([[capability-is-an-artifact-matched-by-propagation]]).

        **It forwards the current residual, and `next_by_coupling`'s `transmitted` stays a preview.**
        `transmitted` is what would remain *after* the chosen tekton absorbs, computed here to rank
        candidates. The receiving provider runs its own `absorb_need` on whatever arrives, so forwarding
        `transmitted` would absorb the same band twice and attenuate the signal at every hop, breaking the
        conservation the membrane model rests on. The measurement supplies the address; the signal travels
        intact.

        `path` is the plane's Cascade guard, carried in need provenance because processes share no memory.
        A tekton fires at most once, which is a derived termination — coupling is idempotent, so a revisit
        would absorb nothing ([[no-arbitrary-caps]]).

        Two residual shapes are accepted, because both exist in the tree:
          * an `Absorption.residual` — a raw frame handed back by a handler that split explicitly;
          * a frame-native handler's response dict carrying an encoded residual under `FRAME_KEY`
            (`frames.absorb_need`'s shape) — which is how `sage.op.retrieve` / `lumen.op.respond` merge
            the remainder into their evidence.

        With no readable frame, or nothing coupling above the floor, the result is `(None, residual)` and
        the signal terminates here — an address is produced only where one was measured.
        """
        # Lazy import: `frames` pulls in numpy, and the transport layer stays importable without it.
        # Only a provider that was given bases pays for the routing dependency.
        from .frames import FRAME_KEY, decode_frame

        # The one measurement in this module, and the reason `reach` straddles the wire/aperture split.
        # The instrument arrives through the injected slot: the `embodiment=` this provider was built
        # with, else the process default the host registered.
        #
        # Resolved outside the `try` below, deliberately. That `except Exception` treats an unreadable
        # frame as "no hop"; an absent instrument is a different fact and stays outside it, so a host
        # with no reading to give names the missing measurement instead of reporting every signal as
        # terminating here.
        #
        # `next_by_coupling` is a member of `prism.embodiment.Embodiment`. It sits on the instrument
        # rather than beside it because it is an argmax over `absorb_transmit` reads: two embodiments
        # that legitimately differ on a read differ on the address, so the choice is domain-bearing
        # (the divergence argument is in `instrument.py`'s header).
        next_by_coupling = _instrument.resolve(
            self._embodiment, "next_by_coupling", at="Provider._route_next")

        frame = None
        if isinstance(residual, dict) and residual.get(FRAME_KEY):
            frame = decode_frame(residual.get(FRAME_KEY))
        elif isinstance(residual, dict):
            frame = None                                        # a dict with no frame carries no signal
        elif residual is not None:
            frame = residual                                    # a raw frame from an explicit split
        elif isinstance(absorbed, dict) and absorbed.get(FRAME_KEY):
            frame = decode_frame(absorbed.get(FRAME_KEY))
            residual = {FRAME_KEY: absorbed.get(FRAME_KEY)}     # forward the remainder, intact
        if frame is None:
            return None, residual                               # nothing readable to route

        try:
            # The caller's noise provider travels with the read. The cutoff and the alpha it is drawn
            # at are one decision and the provider owns both (see the note at the head of this
            # module); `None` runs on entroptics' own derived default. A provider is the surface on
            # which a noisier substrate states something true about itself, being the one that sees
            # the data.
            hop = next_by_coupling(frame, self._bases, fired=path, null=self._null)
        except Exception:
            return None, residual                               # an unreadable frame yields no address
        if hop is None:
            return None, residual                               # nothing couples → the signal ends here
        return hop["tekton"], residual                          # the address is measured; signal intact

    def pump(self, carrier: Any, out: Any = None) -> int:
        """Store-and-forward provider: drain a carrier of needs to this capability, handle each, and
        discharge the evidence onto `out` (default: the same carrier — one ground substrate). The offline /
        degraded path, where a reach resolves with no live provider. Idempotent (dedup by artifact id)."""
        out = out if out is not None else carrier
        saved = self._outbound
        self._outbound = out
        try:
            n = 0
            for leaf in carrier.poll():
                if self.on_leaf(leaf) is not None:
                    n += 1
            return n
        finally:
            self._outbound = saved


def serve(fabric: Any, capability: str, handler: Callable[[Any], Any], *, keyring: Keyring,
          lightcone: Lightcone, node: str, principal: Optional[str] = None, hlc: Any = None,
          ground: str = GROUND, fallback: Any = None,
          bases: Optional[Dict[str, Any]] = None, embodiment: Any = None) -> Provider:
    """Register `handler` (a plain `need -> evidence` callable) as the provider of `capability`. Inbound
    needs addressed to the capability invoke the handler and discharge the evidence onto the `ground` plane
    (provenance-referencing the need); a requester connected to the same ground picks it up. The handler is
    injected — this module imports no ember/lumen/sage; the capability is provided rather than contained."""
    principal = principal or node
    hlc = hlc or HLC(node)
    prov = Provider(capability, handler, keyring=keyring, lightcone=lightcone, principal=principal,
                    node=node, hlc=hlc, ground=ground, outbound=fabric, fallback=fallback, bases=bases,
                    embodiment=embodiment)
    fabric.subscribe(capability, prov.on_leaf)
    return prov


# ── the requester side: pick up evidence from the ground, correlate by provenance ─────────────────────
class Requester:
    """The requester's connection to the ground plane — it picks up evidence discharged onto the ground and
    correlates it by provenance (`root` = the reach handle). Key-gated (it opens when `principal`'s
    light-cone reaches the ground collection, which is its connection to ground), idempotent (dedup by
    artifact id), and provenance-authenticated (the sealed body's `in_reply_to`/`root` must equal the
    envelope's). A principal whose light-cone stops short of the ground opens nothing."""

    def __init__(self, principal: str, lightcone: Lightcone, keyring: Keyring) -> None:
        self._reach = lightcone.reaches(principal)
        self._keys = keyring.principal_keys(principal, lightcone)
        self._seen: set = set()
        self._bands: Dict[str, List] = {}                      # root -> [(hlc, absorbed band), …] (multi-hop)
        self._prov: Dict[str, List] = {}                       # root -> [provenance record, …]

    def on_leaf(self, leaf: Dict[str, Any]) -> None:
        if leaf.get("content_type") != EVIDENCE_CT:
            return
        if leaf.get("to") not in self._reach:                  # isolation: connection to this ground
            return
        if leaf.get("id") in self._seen:                       # idempotent
            return
        opened = open_sealed(leaf["sealed"], self._keys, aad=leaf.get("to", ""))
        if opened is None:                                     # isolation: the key belongs to this ground
            return
        if opened.get("in_reply_to") != leaf.get("in_reply_to") or opened.get("root") != leaf.get("root"):
            return                                             # adversarial: forged provenance
        self._seen.add(leaf["id"])
        root = leaf.get("root")
        self._bands.setdefault(root, []).append((leaf.get("hlc", ""), opened.get("evidence")))
        self._prov.setdefault(root, []).append(                # the provenance chain, followed on the ground
            {"hlc": leaf.get("hlc", ""), "evidence_id": leaf["id"], "in_reply_to": leaf.get("in_reply_to"),
             "root": root, "origin": leaf.get("origin"), "cap": leaf.get("cap")})

    def bands(self, handle: str) -> List[Any]:
        """Every band absorbed along the path for `handle`, HLC-ordered — the full membrane trace,
        collected off the ground by provenance (`root == handle`)."""
        return [ev for _h, ev in sorted(self._bands.get(handle, []), key=lambda x: x[0])]

    def first(self, handle: str) -> Any:
        """The primary (first-coupled) band for `handle` — the answer in the single-hop case; None if
        silent (nothing on the ground references this need)."""
        b = self.bands(handle)
        return b[0] if b else None

    def provenance(self, handle: str) -> List[Dict[str, Any]]:
        """The provenance records of the evidence that returned for `handle` — each referencing the need it
        answers (`in_reply_to`) and the originating need (`root`), HLC-ordered."""
        return [dict(r) for r in sorted(self._prov.get(handle, []), key=lambda r: r.get("hlc", ""))]

    def absorb(self, carrier: Any) -> "Requester":
        """Store-and-forward pickup — poll the ground carrier for evidence this principal can open
        (idempotent across re-polls)."""
        for leaf in carrier.poll():
            self.on_leaf(leaf)
        return self


# ── the persona endpoint: serve capabilities and issue reaches, grounded on one plane ─────────────────
class Reactor:
    """One persona's reach endpoint. It serves capabilities (provider side) and issues reaches (requester
    side), connected to a ground plane through which evidence returns. The single object a persona holds.
    Over a live fabric the round-trip is synchronous propagation (place need → provider fires → discharges
    evidence onto the ground → this reactor's ground connection picks it up); with no fabric it rides a
    carrier and `pump` drives the store-and-forward round-trip."""

    def __init__(self, principal: str, *, keyring: Keyring, lightcone: Lightcone, fabric: Any = None,
                 hlc: Any = None, ground: str = GROUND, fallback: Any = None) -> None:
        self.principal = principal
        self._keyring = keyring
        self._lightcone = lightcone
        self._fabric = fabric
        self._hlc = hlc or HLC(principal)
        self._ground = ground
        self._fallback = fallback
        # Connect to the ground plane: grounding a persona is reaching the ground collection in its
        # light-cone, and that connection is the right to the ground key that reads discharged evidence.
        lightcone.join(principal, ground)
        self._inbox = Requester(principal, lightcone, keyring)  # computes reach/keys after grounding
        if fabric is not None:
            fabric.subscribe(ground, self._inbox.on_leaf)      # observe the return surface
        self._providers: List[Provider] = []

    def serve(self, capability: str, handler: Callable[[Any], Any], *,
              bases: Optional[Dict[str, Any]] = None, embodiment: Any = None) -> Provider:
        """`bases` is `{capability: (F,k) coupling basis}` — supply it and this provider selects the next hop
        for a residual by measured coupling (`Provider._route_next`). Omit it and the plane
        stays handler-directed, taking the next capability from the handler's `to`."""
        if self._fabric is not None:                           # live: subscribe on the fabric
            prov = serve(self._fabric, capability, handler, keyring=self._keyring,
                         lightcone=self._lightcone, node=self.principal, principal=self.principal,
                         hlc=self._hlc, ground=self._ground, fallback=self._fallback, bases=bases,
                         embodiment=embodiment)
        else:                                                  # carrier-only: register a pump-driven provider
            prov = Provider(capability, handler, keyring=self._keyring, lightcone=self._lightcone,
                            principal=self.principal, node=self.principal, hlc=self._hlc,
                            ground=self._ground, outbound=None, fallback=self._fallback, bases=bases,
                            embodiment=embodiment)
        self._providers.append(prov)
        return prov

    def reach(self, need: Any, *, to: str) -> str:
        transport = self._fabric if self._fabric is not None else self._fallback
        return reach(transport, need, to=to, keyring=self._keyring, node=self.principal,
                     hlc=self._hlc, fallback=self._fallback)

    def evidence(self, handle: str) -> Any:
        """The primary band that returned through the ground for `handle` — the answer in the single-hop
        case (None until it arrives; silence stays silence). Use `bands(handle)` for the full multi-hop
        trace, `provenance(handle)` for the chain."""
        return self._inbox.first(handle)

    def bands(self, handle: str) -> List[Any]:
        """Every band absorbed along the signal's path for `handle`, HLC-ordered — the membrane trace when a
        reach couples at more than one tekton (residual propagated hop to hop, same `root`)."""
        return self._inbox.bands(handle)

    def provenance(self, handle: str) -> List[Dict[str, Any]]:
        """The provenance chain of the evidence that returned for `handle` (each record references the need
        it answers) — how the requester finds its answer on the ground."""
        return self._inbox.provenance(handle)

    def pump(self, carrier: Any) -> None:
        """Drive the store-and-forward round-trip on a ground carrier: providers handle needs (discharging
        evidence back onto the ground), then this reactor's ground connection picks the evidence up."""
        for prov in self._providers:
            prov.pump(carrier)
        self._inbox.absorb(carrier)


__all__ = ["reach", "serve", "Provider", "Requester", "Reactor", "Absorption",
           "NEED_CT", "EVIDENCE_CT", "GROUND"]
