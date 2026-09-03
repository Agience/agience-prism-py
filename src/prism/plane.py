"""The communication plane (iris) — `send(to=<artifact>, signal)`, one primitive over real crypto and carriers.

The target is always an artifact: a group is a collection artifact, an ember is an agent artifact. Both are
artifacts, so one code path serves both. A caller drops one signal on one artifact; the receiver absorbs and
propagates — a collection propagates to its members, down containment, and an agent consumes.

Reception is observer agreement enforced by key derivation: a signal exists for a principal exactly when its
lightcone reaches the target and it holds the derived group key. Isolation is cryptographic rather than a
filter — a non-member holds no key to open with.

Transport is a carrier (`carriers.py`) and the plane is carrier-agnostic. Delivery is content-addressed
(idempotent), HLC-ordered (order-independent), and reconciled by anti-entropy (store-and-forward across
partitions).

Concrete here: AES-256-GCM sealing with HKDF-derived per-group keys (mirroring mantle's collection-key
derivation), a hybrid logical clock, durable carriers, and anti-entropy reconcile. Pluggable: the
`Lightcone` (membership and containment) stands in for the mantle grant light-cone, and wiring that is the
one remaining seam.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .carriers import InMemoryCarrier, _leaf_order, reconcile  # noqa: F401  (re-exported)
from .canonical import canonical_string as _jcs_string   # the one canonicaliser for the package

MESSAGE_CT = "application/vnd.agience.message+json"


# ── HLC — hybrid logical clock: causal, monotonic, order-independent delivery ─────────────────────────
class HLC:
    def __init__(self, node: str, clock: Optional[Callable[[], int]] = None) -> None:
        self.node = node
        self._clock = clock or self._wall
        self._last = 0
        self._ctr = 0

    @staticmethod
    def _wall() -> int:
        import time
        return time.time_ns()

    def tick(self) -> str:
        wall = int(self._clock())
        if wall > self._last:
            self._last, self._ctr = wall, 0
        else:
            self._ctr += 1
        return "%020d.%06d.%s" % (self._last, self._ctr, self.node)


# ── Keyring — per-group AES-256 keys derived by HKDF from a fleet root (mirrors content-key derivation) ─
class Keyring:
    """Derives a per-group key from a fleet root secret (HKDF). Deterministic, so every member derives the
    same group key; a non-member derives none, because it never reaches the group and the lightcone gates
    which keys a principal is entitled to. Isolation is cryptographic: a non-member holds no key.

    The derivation is fully specified and reproduces in any language: HKDF-SHA256, `salt=None` (the
    RFC 5869 default of a zero-filled hash-length string), `info="comms:group:<group>"` as UTF-8,
    32 bytes out. A WebCrypto implementation is `deriveBits` with those parameters.
    """

    def __init__(self, root: bytes) -> None:
        self._root = root
        self._cache: Dict[str, bytes] = {}

    def group_key(self, group: str) -> bytes:
        """The raw 32 bytes — an AES-256 key.

        Raw rather than the base64 Fernet key format, because Fernet splits its 32 bytes into two
        16-byte halves and spends them on AES-128 encryption plus HMAC. The same material used
        directly is AES-256.
        """
        if group not in self._cache:
            self._cache[group] = HKDF(
                algorithm=hashes.SHA256(), length=32, salt=None,
                info=("comms:group:%s" % group).encode("utf-8")).derive(self._root)
        return self._cache[group]

    def principal_keys(self, principal: str, lightcone: "Lightcone") -> List[bytes]:
        """The keys a principal is entitled to: the keys of the groups it reaches. Authorization is key
        derivation — reaching a group (a grant) is the right to its key."""
        return [self.group_key(g) for g in lightcone.reaches(principal)]


# ── Lightcone — membership + containment (stands in for the mantle grant light-cone) ──────────────────
class Lightcone:
    def __init__(self) -> None:
        self._member_of: Dict[str, Set[str]] = {}
        self._contains: Dict[str, Set[str]] = {}

    def define_group(self, group: str, *, contains: Iterable[str] = ()) -> "Lightcone":
        self._contains.setdefault(group, set()).update(contains)
        return self

    def join(self, principal: str, group: str) -> "Lightcone":
        self._member_of.setdefault(principal, set()).add(group)
        self._contains.setdefault(group, set())
        return self

    def reaches(self, principal: str) -> Set[str]:
        """The artifacts whose messages a principal receives — its read light-cone, computed exactly as the
        grant model computes it (`ember.access.reachable_collections`). A principal reaches itself (its own
        ember address, where a direct `send(to=<ember>)` lands), the groups granted to it, and the
        containment descendants of those (a grant on a container collection reaches the collections it
        contains). Comms delivery is therefore read-access — "who can read the message artifact" — one
        mechanism serving both.

        Consequence for nesting: a grant on a parent reaches its children, so a parent's member reads a
        child group's message, which is oversight. A message to a parent reaches a child only when the child
        holds a grant on the parent. Broadcast-down is achieved by granting, through this same rule."""
        seen: Set[str] = set(self._member_of.get(principal, set())) | {principal}   # reaches its own address
        frontier = list(self._member_of.get(principal, set()))
        while frontier:
            g = frontier.pop()
            for kid in self._contains.get(g, set()):         # descendants (grant on a parent reaches children)
                if kid not in seen:
                    seen.add(kid)
                    frontier.append(kid)
        return seen


# ── seal / open — AES-256-GCM authenticated encryption (tamper → InvalidTag → honest silence) ─────────
# The sealed format: base64url(`BSL1` + nonce(12) + ciphertext‖tag), with the target artifact as
# additional authenticated data.
#
# Every piece of it is WebCrypto-native, which is what puts the edge profile in reach: a browser
# extension opens a sealed signal with `AES-GCM` as a named algorithm, `deriveBits` for the HKDF, and
# an envelope that is 12 bytes of nonce in front of the ciphertext. Fernet, by contrast, is
# AES-128-CBC + HMAC-SHA256 in a container of its own design that no browser implements. This is also
# the construction mantle uses at rest (`content_cache._encrypt`), so the system has one
# authenticated-encryption shape.
#
# The AAD is the target artifact. A sealed blob authenticates the group it was sealed for, so a
# ciphertext lifted from one leaf and dropped on another fails its tag rather than opening — mantle's
# invariant 3 ("ciphertext is bound to its identity"), holding on the wire as well as at rest.
#
# The 4-byte magic makes the envelope self-describing. Fernet tokens begin with a version byte 0x80,
# and a GCM nonce is random, so it would collide with that marker 1 time in 256; a version prefix is
# what makes reading both formats unambiguous rather than probabilistic.
SEAL_MAGIC = b"BSL1"


def seal(signal: Any, key: bytes, *, aad: str) -> str:
    """Seal one signal under a group key. `aad` is the target artifact, authenticated but not
    encrypted, so the ciphertext stays bound to the target it was sealed for.

    `aad` is required and has no default. A seal whose AAD disagrees with the open's produces silence
    — the tag fails — and silence is indistinguishable from "not addressed to me", the normal case on
    a shared carrier. Making the argument required moves any disagreement to the call site, where it
    is a TypeError naming the caller, rather than to a stream that delivers nothing."""
    plain = _jcs_string(signal).encode("utf-8")
    nonce = os.urandom(12)
    blob = SEAL_MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, aad.encode("utf-8"))
    return base64.urlsafe_b64encode(blob).decode("ascii")


def open_sealed(sealed: str, keys: Iterable[bytes], *, aad: str) -> Optional[Any]:
    """The first key that opens it, or `None`. A key that does not open a signal yields silence rather
    than an error: on a shared carrier most leaves are addressed to groups this principal is not in,
    and that is the normal case rather than a fault."""
    try:
        raw = base64.urlsafe_b64decode(sealed.encode("ascii"))
    except Exception:
        return None

    if raw[:4] == SEAL_MAGIC:
        nonce, ct, ad = raw[4:16], raw[16:], aad.encode("utf-8")
        for k in keys:
            try:
                return json.loads(AESGCM(k).decrypt(nonce, ct, ad).decode("utf-8"))
            except (InvalidTag, ValueError):
                continue
        return None

    # ── A Fernet token ──
    # Signals dropped on a durable carrier stay readable — a carrier is store-and-forward, so a leaf
    # outlives the code that wrote it by however long a node was partitioned. Fernet has no AAD, so
    # such a signal carries no target binding; that is a property of what was written, and re-sealing
    # is what gives it one.
    for k in keys:
        try:
            return json.loads(
                Fernet(base64.urlsafe_b64encode(k)).decrypt(sealed.encode("ascii")).decode("utf-8"))
        except (InvalidToken, ValueError):
            continue
    return None


# ── The one primitive + delivery ─────────────────────────────────────────────────────────────────────
def _leaf_id(frm: str, to: str, hlc: str, signal: Any) -> str:
    import hashlib
    body = _jcs_string({"frm": frm, "to": to, "hlc": hlc, "sig": signal})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def send(carrier, *, to: str, frm: str, signal: Any, keyring: Keyring, hlc: str) -> Dict[str, Any]:
    """Drop one signal on the target artifact `to`, sealed under `to`'s group key (AES-256-GCM, with `to` as AAD). Content-addressed
    (idempotent), HLC-stamped (order-independent). One leaf serves every recipient, whatever the target type."""
    leaf = {"id": _leaf_id(frm, to, hlc, signal), "content_type": MESSAGE_CT,
            "to": to, "frm": frm, "hlc": hlc, "sealed": seal(signal, keyring.group_key(to), aad=to)}
    return carrier.put(leaf)


def receive(carrier, *, principal: str, lightcone: Lightcone, keyring: Keyring) -> List[Dict[str, Any]]:
    """What `principal` receives: poll the carrier and, for every leaf addressed to an artifact this
    principal reaches, open it with the principal's keys. A target outside the lightcone is invisible; a
    reachable one no key opens is noise. Idempotent (dedup by leaf id) and HLC-ordered
    (arrival-independent)."""
    reachable = lightcone.reaches(principal)
    keys = keyring.principal_keys(principal, lightcone)
    out: Dict[str, Dict[str, Any]] = {}
    for leaf in carrier.poll():
        if leaf.get("to") not in reachable:
            continue
        opened = open_sealed(leaf["sealed"], keys, aad=leaf.get("to", ""))
        if opened is None:
            continue
        out[leaf["id"]] = {"id": leaf["id"], "to": leaf["to"], "frm": leaf["frm"],
                           "hlc": leaf["hlc"], "signal": opened}
    return sorted(out.values(), key=_leaf_order)   # UTF-8 byte order — see carriers._leaf_order


# ── Plane — the per-node API: carriers + keyring + lightcone + HLC ────────────────────────────────────
class Plane:
    """One node's view of the communication plane. `send(to, signal)` seals and drops on the primary carrier;
    `receive(principal)` merges all carriers (anti-entropy) and opens what the principal's keys cover.
    `carriers` are cost-ordered (direct or LAN first, S3 last) and the merge tries them all, so a leaf on any
    carrier is delivered."""

    def __init__(self, *, node: str, keyring: Keyring, lightcone: Lightcone, carriers,
                 clock: Optional[Callable[[], int]] = None) -> None:
        self.node = node
        self.keyring = keyring
        self.lightcone = lightcone
        self.carriers = list(carriers)
        self.hlc = HLC(node, clock=clock)

    def send(self, to: str, signal: Any, *, frm: Optional[str] = None) -> Dict[str, Any]:
        return send(self.carriers[0], to=to, frm=frm or self.node, signal=signal,
                    keyring=self.keyring, hlc=self.hlc.tick())

    def reconcile(self) -> int:
        """Anti-entropy across this node's carriers (store-and-forward / partition heal)."""
        n = 0
        for c in self.carriers[1:]:
            n += reconcile(self.carriers[0], c)
        return n

    def receive(self, principal: str) -> List[Dict[str, Any]]:
        merged = InMemoryCarrier()
        for c in self.carriers:
            for leaf in c.poll():
                merged.put(leaf)
        return receive(merged, principal=principal, lightcone=self.lightcone, keyring=self.keyring)


__all__ = ["Plane", "HLC", "Keyring", "Lightcone", "seal", "open_sealed", "send", "receive",
           "InMemoryCarrier", "reconcile", "MESSAGE_CT"]
