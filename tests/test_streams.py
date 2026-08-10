"""`prism/streams.py` — the live transport mode.

The invariants below are the module's own documented claims, each paired with the control that makes it
falsifiable:

  Live        — a sealed frame reaches a live receiver and opens to exactly the frame that was sent.
  Isolation   — a non-member's handler runs and opens nothing. The control carries the weight here:
                "opened nothing" means little unless the handler demonstrably fired, otherwise the test
                passes for a stream that delivered to nobody at all.
  Degrade     — with no live receiver the frame lands on the fallback carrier. Controlled by the converse:
                with a live receiver the fallback stays empty, so degrade is a fallback rather than an
                unconditional second write, and the live path stays a fast path.
  HLC order   — frames are ordered by HLC, independently of arrival. Controlled by delivering out of order
                and asserting the sort, since in-order delivery would pass with no ordering logic at all.
  Closed      — a closed stream raises rather than silently dropping (a dropped frame on a live channel is
                the wrong-answer-not-empty-answer shape).
"""
from __future__ import annotations

import pytest

from prism.carriers import InMemoryCarrier
from prism.plane import HLC, Keyring, Lightcone
from prism.streams import FRAME_CT, LoopbackFabric, Stream, StreamReceiver, open_stream

CAP = "op.respond"
ROOT = b"fleet-root-secret"
FRAME = {"T": 4, "F": 2, "rows": [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5], [0.25, 0.75]]}


def _wiring(*, member="lumen", outsider="stranger"):
    """One keyring, one light-cone: `member` reaches CAP, `outsider` reaches nothing."""
    lc = Lightcone().join(member, CAP)
    lc.join(outsider, "somewhere-else")
    return Keyring(ROOT), lc


def _stream(fabric, *, node="ember-runner"):
    kr = Keyring(ROOT)
    return open_stream(fabric, CAP, keyring=kr, node=node, hlc=HLC(node))


# ── Live ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_frame_round_trips_live_to_an_entitled_receiver():
    """A sealed frame reaches an entitled live receiver and opens to the frame that was sent.

    Fails if the frame arrives but cannot be opened (wrong key derivation), which leaves a live channel
    carrying nothing openable — indistinguishable at the call site from an idle channel."""
    kr, lc = _wiring()
    fabric = LoopbackFabric()
    rx = StreamReceiver("lumen", lc, kr)
    fabric.subscribe(CAP, rx.on_leaf)

    leaf = _stream(fabric).send_frame(FRAME)

    assert leaf["content_type"] == FRAME_CT
    assert leaf["to"] == CAP and leaf["frm"] == "ember-runner"
    assert "sealed" in leaf and FRAME != leaf["sealed"], "the frame must travel SEALED, not in clear"
    assert len(rx.frames) == 1, "an entitled live receiver got nothing"
    assert rx.frames[0]["frame"] == FRAME, "the opened frame is not the frame that was sent"


# ── Isolation, with the control that makes it mean something ───────────────────────────────────────
def test_a_non_member_handler_RUNS_and_still_opens_nothing():
    """Isolation here is cryptographic, exactly as on the message plane: a non-member's handler receives
    the leaf and opens nothing from it.

    The control carries the weight. If the outsider's handler never fired, `frames == []` would say
    nothing about the crypto, so this asserts the handler did run."""
    kr, lc = _wiring()
    fabric = LoopbackFabric()
    seen = []
    outsider = StreamReceiver("stranger", lc, kr)

    def watch(leaf):
        seen.append(leaf)          # proves the handler is on the wire
        outsider.on_leaf(leaf)

    fabric.subscribe(CAP, watch)
    _stream(fabric).send_frame(FRAME)

    assert len(seen) == 1, "the outsider's handler never ran — this test would pass vacuously"
    assert outsider.frames == [], "a non-member OPENED a frame it must not be able to decrypt"


def test_a_different_fleet_root_opens_nothing():
    """A group key derived from a different fleet root opens nothing.

    The receiver is entitled by light-cone here, so only the key differs, which isolates the crypto from
    the entitlement check. Fails if a salt/info bug makes derivation root-independent, which would make
    every fleet mutually readable."""
    _, lc = _wiring()
    fabric = LoopbackFabric()
    rx = StreamReceiver("lumen", lc, Keyring(b"a-DIFFERENT-fleet-root"))
    fabric.subscribe(CAP, rx.on_leaf)

    _stream(fabric).send_frame(FRAME)

    assert rx.frames == [], "a reactor keyed off a different fleet root opened the frame"


# ── Degrade, both directions ───────────────────────────────────────────────────────────────────────
def test_with_no_live_receiver_the_frame_DEGRADES_onto_the_fallback():
    """With nobody live, the frame lands on the fallback carrier. `streams.py` promises "live is the fast
    path, the letter is the floor", and a dropped frame would turn that delivery guarantee into a coin
    flip."""
    carrier = InMemoryCarrier()
    fabric = LoopbackFabric(fallback=carrier)          # nobody subscribed

    leaf = _stream(fabric).send_frame(FRAME)

    parked = carrier.poll()
    assert len(parked) == 1, "no live receiver and no fallback write — the frame was DROPPED"
    assert parked[0]["id"] == leaf["id"] and parked[0]["to"] == CAP


def test_with_a_live_receiver_the_fallback_stays_EMPTY():
    """The control for the test above: degrade is conditional on nobody being live. If a live delivery
    also wrote to the carrier, every live frame would be persisted too — the fast path would cost a store
    write and the store-and-forward floor would double-deliver."""
    kr, lc = _wiring()
    carrier = InMemoryCarrier()
    fabric = LoopbackFabric(fallback=carrier)
    rx = StreamReceiver("lumen", lc, kr)
    fabric.subscribe(CAP, rx.on_leaf)

    _stream(fabric).send_frame(FRAME)

    assert len(rx.frames) == 1, "the live receiver did not get the frame"
    assert carrier.poll() == [], "a LIVE delivery also wrote to the fallback — degrade is unconditional"


def test_no_live_receiver_and_no_fallback_does_not_raise():
    """A node with no fabric fallback configured is a first-class state (`fallback=None`): `send_frame`
    returns the leaf and says nothing else, so a dark plane leaves the sender running."""
    leaf = _stream(LoopbackFabric(fallback=None)).send_frame(FRAME)
    assert leaf["to"] == CAP, "send_frame must still produce the leaf with no receiver and no fallback"


# ── HLC order ─────────────────────────────────────────────────────────────────────────────────────
def test_frames_are_HLC_ordered_independently_of_arrival_order():
    """Frames are ordered by HLC rather than by arrival. Over a real fabric frames reorder, and a receiver
    that appends blindly hands the tekton a scrambled (T,F) sequence, which reads as real data. Delivery
    here is reversed on purpose: in-order delivery would pass with no ordering logic at all."""
    kr, lc = _wiring()
    fabric = LoopbackFabric()
    sender = _stream(fabric)                     # not subscribed: collect the leaves, then replay
    leaves = [sender.send_frame({"n": i}) for i in range(4)]
    assert [l["hlc"] for l in leaves] == sorted(l["hlc"] for l in leaves), \
        "the sender's own HLC did not increase monotonically"

    rx = StreamReceiver("lumen", lc, kr)
    for leaf in reversed(leaves):                # arrival order reversed
        rx.on_leaf(leaf)

    assert [f["frame"]["n"] for f in rx.frames] == [0, 1, 2, 3], \
        "frames were kept in arrival order, not HLC order"


# ── Closed ────────────────────────────────────────────────────────────────────────────────────────
def test_a_closed_stream_raises_rather_than_dropping():
    """A closed stream raises on send. A silently swallowed send would leave the caller believing it is
    streaming while the receiver gets nothing and nothing reports it."""
    fabric = LoopbackFabric()
    s = _stream(fabric)
    s.send_frame(FRAME)                          # open: fine
    s.close()
    with pytest.raises(RuntimeError, match="closed"):
        s.send_frame(FRAME)


def test_closing_one_stream_does_not_affect_frames_already_sent():
    """A live channel is not a transaction: the module states that "frames already sent are unaffected",
    so close() leaves delivered frames intact."""
    kr, lc = _wiring()
    fabric = LoopbackFabric()
    rx = StreamReceiver("lumen", lc, kr)
    fabric.subscribe(CAP, rx.on_leaf)
    s = _stream(fabric)
    s.send_frame(FRAME)
    s.close()
    assert len(rx.frames) == 1 and rx.frames[0]["frame"] == FRAME


# ── the module's own surface ───────────────────────────────────────────────────────────────────────
def test_open_stream_returns_a_Stream_and_the_fabric_face_is_two_operations():
    """A real fabric (WebRTC/QUIC/RF) replaces the fabric, keeping the semantics, so the face it must
    present is pinned here: `subscribe` + `deliver_live`, with `deliver_live` reporting whether anyone was
    live. That boolean is the degrade decision."""
    fabric = LoopbackFabric()
    assert isinstance(_stream(fabric), Stream)
    assert callable(fabric.subscribe) and callable(fabric.deliver_live)
    assert fabric.deliver_live(CAP, {"id": "x"}) is False, \
        "deliver_live must report False with no subscriber — that boolean drives the degrade path"
    fabric.subscribe(CAP, lambda _l: None)
    assert fabric.deliver_live(CAP, {"id": "y"}) is True
