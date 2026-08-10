"""Live stream channels — the second transport mode of the comm-plane (frames, not leaves).

A stream carries `(T, F)` beam frames live (a call, a live reach, a sensor/RF feed). It uses the same
addressing (`to=<artifact>`) and the same isolation (each frame sealed with the group key) as the message
plane — only the pacing differs: frames flow, HLC-ordered, and a receiving tekton absorbs each band as it
arrives. When the live path cannot hold (no live receiver, peer offline, RF drop), a frame degrades to a
store-and-forward leaf on a fallback `Carrier` — live is the fast path, the letter is the floor.

`LoopbackFabric` is the test transport; a real WebRTC / QUIC / RF fabric replaces the fabric, never the
semantics (sealed + HLC-ordered frames + degrade-to-message) pinned here. See
`agience-pharos/genesis/DATA-COMMS-CHANNELS.md`, `SIGNAL-PROTOCOL.md`.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from .plane import HLC, Keyring, Lightcone, _leaf_id, open_sealed, seal

FRAME_CT = "application/vnd.agience.frame+json"


class LoopbackFabric:
    """A test streaming fabric: in-memory live delivery keyed by target artifact, plus a durable fallback
    `Carrier` for the degrade path. Real fabrics (WebRTC/QUIC/RF) present the same two operations."""

    def __init__(self, fallback=None) -> None:
        self._subs: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        self.fallback = fallback

    def subscribe(self, to: str, handler: Callable[[Dict[str, Any]], None]) -> None:
        self._subs.setdefault(to, []).append(handler)

    def deliver_live(self, to: str, leaf: Dict[str, Any]) -> bool:
        handlers = list(self._subs.get(to, []))
        for h in handlers:
            h(leaf)
        return bool(handlers)


class Stream:
    """A live channel to an artifact. `send_frame` seals a beam frame with the target's group key,
    HLC-stamps it, and delivers it live; if no one is live on the other end, it degrades onto the fallback
    carrier (store-and-forward). Closing a stream stops it; frames already sent are unaffected."""

    def __init__(self, fabric: LoopbackFabric, to: str, *, keyring: Keyring, node: str, hlc: HLC) -> None:
        self._fabric, self._to, self._keyring, self._node, self._hlc = fabric, to, keyring, node, hlc
        self.open = True

    def send_frame(self, frame: Any) -> Dict[str, Any]:
        if not self.open:
            raise RuntimeError("stream to %r is closed" % self._to)
        hlc = self._hlc.tick()
        leaf = {"id": _leaf_id(self._node, self._to, hlc, frame), "content_type": FRAME_CT,
                "to": self._to, "frm": self._node, "hlc": hlc,
                "sealed": seal(frame, self._keyring.group_key(self._to), aad=self._to)}
        if not self._fabric.deliver_live(self._to, leaf) and self._fabric.fallback is not None:
            self._fabric.fallback.put(leaf)          # degrade: no live receiver, store-and-forward
        return leaf

    def close(self) -> None:
        self.open = False


def open_stream(fabric: LoopbackFabric, to: str, *, keyring: Keyring, node: str, hlc: HLC) -> Stream:
    return Stream(fabric, to, keyring=keyring, node=node, hlc=hlc)


class StreamReceiver:
    """The live receive side — mirrors `plane.receive` for frames: subscribe to the fabric, open each
    frame the principal is entitled to (its keys, gated by the light-cone), and keep them HLC-ordered.
    A non-member's handler runs but opens nothing (isolation is cryptographic, identical to messages)."""

    def __init__(self, principal: str, lightcone: Lightcone, keyring: Keyring) -> None:
        self._reach = lightcone.reaches(principal)
        self._keys = keyring.principal_keys(principal, lightcone)
        self.frames: List[Dict[str, Any]] = []

    def on_leaf(self, leaf: Dict[str, Any]) -> None:
        if leaf.get("to") not in self._reach:
            return
        opened = open_sealed(leaf["sealed"], self._keys, aad=leaf.get("to", ""))
        if opened is None:
            return
        self.frames.append({"hlc": leaf["hlc"], "frame": opened})
        self.frames.sort(key=lambda f: f["hlc"])     # HLC-ordered, arrival-independent


__all__ = ["LoopbackFabric", "Stream", "StreamReceiver", "open_stream", "FRAME_CT"]
