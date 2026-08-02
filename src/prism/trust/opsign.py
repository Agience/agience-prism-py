"""Operator signing — WHO authored this behaviour, verifiable by anyone, independent of who served it.

This is the integrity half of AGENT-HOST-DESIGN.md D10/D12: bundles are reached in peer mantles and
cached, never installed, so a node must be able to verify an operator it did not author and did not
fetch from its author. Signing gives exactly that and nothing more.

⚠ WHAT A SIGNATURE DOES AND DOES NOT BUY — state it plainly, because the difference decides whether
the rest of the design is sound:

  * IT ATTESTS AUTHORSHIP AND INTEGRITY. This spec is the one that author published, unmodified.
  * IT SAYS NOTHING ABOUT WHAT THE OPERATOR DOES. A validly-signed operator can be hostile.

So a signature NEVER authorizes execution on its own. Admission is: verify signature -> check the
EFFECT CONTRACT against what this host offers -> and for code-backed operators, a sandbox. Declarative
operators are safe not because they are signed but because they can only invoke capabilities the host
already published (D12). Signing tells you who to blame; the capability model is what limits harm.

## What is signed

`canonical_operator()` covers the EXECUTABLE CONTENT and the CONTRACT — `id`, `kind`, `spec`,
`requires`, `effects` — and deliberately nothing else. Excluded, with reasons:

  * fitness counters (`invocations`, `verified`, …) — these ACCRUE LOCALLY and differ per node. If
    they were signed, every invocation would invalidate the signature.
  * `created_time`, `state` — lifecycle, not behaviour.
  * `context`/`content`/`lemmas` — the human-facing offer text. ⚠ NOTE THIS IS A REAL TRADE-OFF:
    the offer is how an operator is DISCOVERED (need->offer match), so an unsigned offer means a
    relay could re-describe an operator to make it match needs it should not. That is a
    discoverability attack, not an execution one — the spec still cannot change — and closing it
    means signing the offer too, at the cost of re-signing on every wording edit. Flagged, not
    hidden; revisit when cross-origin sharing is real (D11).

## Draft is enforced by the ABSENCE of a signature

Publishing IS commit + canonicalize + hash + sign. A draft simply has no signature, so it cannot be
admitted anywhere — no separate visibility flag, and it fails closed by construction.

⚠ MOVED HERE FROM `ember/identity/opsign.py` — 2026-08-02, the chorus→ember DAG work. Behaviour
unchanged; only the address did. It was never ember's, and the imports proved it: measured at the move
this module reached `cryptography`, `prism.canonical` and `prism.crystal_model` and **nothing from
ember at all**. It sat in the runner's repo because the runner was its loudest caller, not because it
was the runner's concern.

Why `prism.trust` specifically, rather than origin (identity) or a new home:
  * The `trust` extra is already declared as *"sign/verify, keys"* and already carries
    `cryptography>=42` — this module needs exactly that and adds no new dependency.
  * What is signed here is an OPERATOR and a BUNDLE — crystal-shaped artifacts whose canonical form
    (`prism.crystal_model.bundle_canonical`) and content addressing already live in prism. Signing them
    from anywhere else puts the signer on one side of the DAG and the thing it canonicalizes on the
    other.
  * It is NOT user identity, which is the concern-map reason it does not go to origin: origin answers
    *who is this principal*; this answers *who authored this behaviour*. And prism is a pure leaf, so
    the bundle loader that verifies signatures (`prism.runner`) reaches it without an upward edge.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from prism.canonical import canonical_string as _jcs_string

# The fields that constitute the operator's behaviour and its contract. Order is irrelevant —
# `canonical_operator` sorts — but the SET is the security boundary, so it is named in one place.
SIGNED_FIELDS = ("id", "kind", "spec", "requires", "effects")


def canonical_operator(doc: Dict[str, Any]) -> bytes:
    """The exact bytes that are signed and verified. Deterministic across processes and machines:
    sorted keys, no whitespace, absent fields normalized so `{}` and missing agree."""
    payload = {
        "id": doc.get("id") or "",
        "kind": doc.get("kind") or "",
        "spec": doc.get("spec") or {},
        "requires": sorted(doc.get("requires") or []),      # capability names (D12)
        "effects": doc.get("effects") or {},                # the effect contract
    }
    return _jcs_string(payload).encode("utf-8")


def authority_key(keys_dir, *, create: bool = False
                  ) -> Tuple[Optional[Ed25519PrivateKey], Optional[Ed25519PublicKey]]:
    """This node's operator-signing key, persisted at `<keys_dir>/operator.key`.

    ⛔ `create` DEFAULTS TO FALSE, AND THAT IS DELIBERATE. `content.py` records what happens
    otherwise: `_content_key` minted a fresh key on the READ path when the file was absent, which
    silently partitioned the node from the fleet while every health metric stayed green. A verify
    path must never mint a key — a missing key is "I cannot verify", never "here is a new identity".
    Signing (a write) may create; verification (a read) may not.
    """
    kp = Path(keys_dir) / "operator.key"
    if kp.exists():
        priv = Ed25519PrivateKey.from_private_bytes(kp.read_bytes())
        return priv, priv.public_key()
    if not create:
        return None, None
    Path(keys_dir).mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    kp.write_bytes(priv.private_bytes(serialization.Encoding.Raw,
                                      serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption()))
    try:                                    # best-effort: not world-readable where the OS allows it
        kp.chmod(0o600)
    except (OSError, NotImplementedError):
        pass
    return priv, priv.public_key()


def sign_bytes(canonical: bytes, priv: Ed25519PrivateKey) -> str:
    """Ed25519 over already-canonical bytes → hex. The generic primitive both operators and signals
    sign with, so there is ONE signing mechanism, not two that can drift apart."""
    return priv.sign(canonical).hex()


def verify_bytes(canonical: bytes, sig_hex: str, pub: Ed25519PublicKey) -> bool:
    """True iff `sig_hex` is `pub`'s signature over `canonical`. Never raises — a malformed
    signature is `False`, not an exception, so a caller cannot forget to catch it."""
    try:
        pub.verify(bytes.fromhex(sig_hex), canonical)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def public_key_hex(pub: Ed25519PublicKey) -> str:
    return pub.public_bytes(serialization.Encoding.Raw,
                            serialization.PublicFormat.Raw).hex()


def load_public(hex_key: str) -> Optional[Ed25519PublicKey]:
    try:
        return Ed25519PublicKey.from_public_bytes(bytes.fromhex(hex_key))
    except (ValueError, TypeError):
        return None


def sign_operator(doc: Dict[str, Any], priv: Ed25519PrivateKey, *,
                  authority: str = "") -> Dict[str, Any]:
    """Publish: stamp the signature, the signer's public key, and the content address.

    `signed_by` carries the PUBLIC KEY so a peer can verify without a key-distribution round trip;
    `authority` names the issuing origin (D11) for the trust decision that sits ABOVE verification.
    Verifying the signature proves authorship — deciding whether that author is trusted is a
    separate question this function does not answer."""
    doc["signature"] = priv.sign(canonical_operator(doc)).hex()
    doc["signed_by"] = public_key_hex(priv.public_key())
    if authority:
        doc["authority"] = authority
    # ⛔ `spec_hash` IS NO LONGER STAMPED (2026-07-30). EVERYTHING IS AN ARTIFACT — and this was a
    # SECOND, WEAKER content address stored beside one the artifact already has.
    #
    # Measure it against what it sat next to: `canonical_operator` covers
    # {id, kind, spec, requires, effects} and is bound by an Ed25519 signature, while `spec_hash`
    # digests only (kind, spec) — a strict SUBSET of the signed payload. It therefore protected
    # nothing the signature did not already protect. Note the ordering above: the signature is
    # computed BEFORE the stamp, so it never covered `spec_hash` either.
    #
    # What the stored copy DID do was go stale. Being a stored derived value, it had to be
    # re-derived whenever its canonicalizer changed — which is the entire "workspace-wide address
    # migration" that blocked the bundle rebuild for days. And the two canonicalizers do not agree:
    # `json.dumps(sort_keys, separators)` vs RFC 8785 differ on non-ASCII strings and on floats
    # (`1.0` → "1.0" vs "1"). Two spellings, one operator.
    #
    # `evolution.spec_hash()` remains as a FUNCTION, computed on demand where fitness needs to ask
    # "is this the same behaviour?". A value you can always recompute never needs migrating.
    return doc


def verify_operator(doc: Dict[str, Any], *, pub: Optional[Ed25519PublicKey] = None
                    ) -> Tuple[bool, str]:
    """`(ok, reason)` — is this operator authentic and internally consistent?

    Checks, in order, each failing CLOSED with a distinct reason so "unsigned" is never confused
    with "forged" and neither is confused with "valid":
      1. a signature is present at all (absent => DRAFT, not admissible)
      2. the signature verifies against `pub`, or against the embedded `signed_by` if none is given

    ⛔ THERE IS NO LONGER A THIRD CHECK, and removing it lost nothing. It compared a STORED
    `spec_hash` against a recomputed one "so a doc cannot advertise one content address while
    carrying different behaviour". But `canonical_operator` — the bytes the signature binds —
    already covers {id, kind, spec, requires, effects}, a superset of what `spec_hash` digests. A doc
    carrying different behaviour fails check 2. So check 3 could only ever fire on a doc whose
    signature had ALREADY verified, i.e. on an untampered doc whose stored hash was STALE — turning
    a canonicalizer change into a fleet-wide verification failure. A stale copy of a signed value is
    not a second opinion; it is a second thing to keep in sync.

    ⚠ Verifying against the EMBEDDED key proves only self-consistency: anyone can sign anything with
    a key they generated. It answers "was this tampered with in transit", not "do I trust the
    author". Pass `pub` from a trusted source to answer the second question. The distinction is
    returned in the reason string rather than hidden."""
    sig = doc.get("signature")
    if not sig:
        return False, "unsigned (draft — publishing is commit + hash + sign)"
    key = pub or load_public(str(doc.get("signed_by") or ""))
    if key is None:
        return False, "no verifying key: none supplied and `signed_by` is missing or malformed"
    try:
        key.verify(bytes.fromhex(sig), canonical_operator(doc))
    except (InvalidSignature, ValueError):
        return False, "signature does not verify (tampered, or signed by a different key)"
    return True, ("verified against a supplied key" if pub is not None
                  else "self-consistent (verified against the embedded key — authorship is "
                       "unattested; supply a trusted key to check WHO)")


# ── bundles ───────────────────────────────────────────────────────────────────────────────────
#
# A SOURCE BUNDLE (runner.py's single distribution path) is signed with the SAME mechanism as an
# operator — Ed25519 over canonical bytes, `signature`/`signed_by` stamped beside the content —
# so there is ONE signing scheme, not two that can drift apart. The canonical bytes are exactly
# the payload the bundle's sha256 already covers (`runner._canonical`: group, entry_module,
# register_fns, host_seams, modules — build_bundles.canonical, byte for byte). Consequences:
#
#   * signing does NOT change the sha256 — the envelope fields sit OUTSIDE the hashed payload,
#     exactly as an operator's `signature` sits outside `SIGNED_FIELDS`. A signed bundle is the
#     same content-addressed artifact as its unsigned twin.
#   * signature and sha attest the SAME bytes, so "sha verifies but signature covers something
#     else" cannot happen — there is one canonicalization, defined once (build side), reproduced
#     once (runner), and reused here.
#   * like an operator, verifying against the EMBEDDED `signed_by` proves only self-consistency.
#     WHO signed — and whether that author's rung admits execution — is the runner's trust gate
#     (`runner.verify_provenance`), which binds the key to the store-resolved author artifact.


def _bundle_canonical(bundle: Dict[str, Any]) -> bytes:
    """⚠ FROM THE CONTRACT, NOT FROM THE RUNNER (2026-07-31). This reached into
    `ember.runtime.runner._canonical` — a signing module depending on the runner's private helper
    for the bytes it signs over. That was `identity/`'s last tie to `runtime/`, and the direction was
    wrong anyway: what a signature covers is a contract, not a runner detail."""
    from prism.crystal_model import bundle_canonical
    return bundle_canonical(bundle)


def sign_bundle(bundle: Dict[str, Any], priv: Ed25519PrivateKey, *,
                authority: str = "") -> Dict[str, Any]:
    """Publish a bundle: stamp `signature` (Ed25519 hex over the sha-canonical payload) and
    `signed_by` (the signer's public key, hex) — the operator envelope, applied to a bundle.
    Mutates and returns `bundle`. Raises KeyError on a malformed bundle: signing garbage is a
    caller bug, never something to paper over."""
    bundle["signature"] = sign_bytes(_bundle_canonical(bundle), priv)
    bundle["signed_by"] = public_key_hex(priv.public_key())
    if authority:
        bundle["authority"] = authority
    return bundle


def verify_bundle(bundle: Dict[str, Any], *, pub: Optional[Ed25519PublicKey] = None
                  ) -> Tuple[bool, str]:
    """`(ok, reason)` — mirror of `verify_operator` for bundles, same fail-closed order:
    unsigned, no key, and forged are three DISTINCT reasons, never conflated."""
    sig = bundle.get("signature")
    if not sig:
        return False, "unsigned (no `signature` on the bundle)"
    key = pub or load_public(str(bundle.get("signed_by") or ""))
    if key is None:
        return False, "no verifying key: none supplied and `signed_by` is missing or malformed"
    try:
        canonical = _bundle_canonical(bundle)
    except (KeyError, TypeError) as e:
        return False, "malformed bundle, cannot canonicalize: %s" % e
    if not verify_bytes(canonical, str(sig), key):
        return False, "signature does not verify (tampered, or signed by a different key)"
    return True, ("verified against a supplied key" if pub is not None
                  else "self-consistent (verified against the embedded key — authorship is "
                       "unattested; supply a trusted key to check WHO)")


def admit(doc: Dict[str, Any], *, host_offers=None, pub: Optional[Ed25519PublicKey] = None
          ) -> Tuple[bool, str]:
    """May this node RUN this operator? Signature + capability contract + runtime, in that order.

    Admission is separate from acquisition on purpose (D10): a node routinely holds operators it
    will not run, and an unadmitted operator stays HELD AND VISIBLE so it becomes runnable if the
    host later gains the capability, and so the agent can say what it would need.

    `host_offers` is the set of capability names this host publishes (D12). `None` means NOT
    PROBED — which is refused rather than treated as "offers nothing", keeping the three-valued
    discipline `resource.py` establishes: has / hasn't / didn't-probe must stay distinguishable."""
    ok, why = verify_operator(doc, pub=pub)
    if not ok:
        return False, why
    if str(doc.get("kind") or "") not in ("source", "composition"):
        # D10: code-backed operators are reachable but NOT runnable until a sandbox exists.
        # Signing tells you who wrote it; without isolation that is a liability model, not security.
        return False, "runtime %r is not admissible: no sandbox exists yet" % doc.get("kind")
    requires = sorted(doc.get("requires") or [])
    if not requires:
        return True, "admitted"
    if host_offers is None:
        return False, "host capabilities not probed — refusing rather than assuming"
    missing = [c for c in requires if c not in set(host_offers)]
    if missing:
        return False, "host does not offer: %s" % ", ".join(missing)
    return True, "admitted"
