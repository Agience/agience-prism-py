"""Operator signing — who authored this behaviour, verifiable by anyone, independent of who served it.

This is the integrity half of AGENT-HOST-DESIGN.md D10/D12: bundles are reached in peer mantles and
cached rather than installed, so a node verifies an operator it did not author and did not fetch
from its author. Signing gives exactly that:

  * It attests authorship and integrity. This spec is the one that author published, unmodified.
  * It says nothing about what the operator does. A validly-signed operator can be hostile.

Admission is therefore a separate, wider decision: verify the signature -> check the effect contract
against what this host offers -> and for code-backed operators, a sandbox. A declarative operator is
safe because it can invoke only capabilities the host already published (D12). Signing tells you who
to blame; the capability model is what limits harm.

## What is signed

`canonical_operator()` covers the executable content and the contract — `id`, `kind`, `spec`,
`requires`, `effects` — and nothing else. Excluded, with reasons:

  * fitness counters (`invocations`, `verified`, …) — these accrue locally and differ per node. If
    they were signed, every invocation would invalidate the signature.
  * `created_time`, `state` — lifecycle, not behaviour.
  * `context`/`content`/`lemmas` — the human-facing offer text.

## A draft is an operator with no signature

Publishing is commit + canonicalize + hash + sign. A draft carries no signature, so it is
inadmissible everywhere by construction — one state, no separate visibility flag.

Why this lives in `prism.trust`:
  * The `trust` extra is declared as *"sign/verify, keys"* and carries `cryptography>=42` — this
    module needs exactly that and adds no dependency.
  * What is signed is an operator or a bundle — crystal-shaped artifacts whose canonical form
    (`prism.crystal_model.bundle_canonical`) and content addressing already live in prism, so the
    signer sits beside the thing it canonicalizes.
  * prism is a pure leaf, so the bundle loader that verifies signatures (`prism.runner`) reaches it
    without an upward edge. Origin answers *who is this principal*; this answers *who authored this
    behaviour*.
"""
from __future__ import annotations

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
# `canonical_operator` sorts — but the set is the security boundary, so it is named in one place.
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
    """This node's operator-signing key, persisted as raw Ed25519 bytes at `<keys_dir>/operator.key`.

    Returns `(private, public)`. An existing file is loaded. When there is none, `create=True`
    generates and persists one (mode 0600 where the OS supports it) and `create=False` returns
    `(None, None)`, so a verify-only node can ask without minting an identity.
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
    sign with, so there is one signing mechanism across both."""
    return priv.sign(canonical).hex()


def verify_bytes(canonical: bytes, sig_hex: str, pub: Ed25519PublicKey) -> bool:
    """True iff `sig_hex` is `pub`'s signature over `canonical`. Total: a malformed signature
    returns `False`, so the result is the whole answer and there is nothing to catch."""
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
    """Publish: stamp `signature`, `signed_by`, and `authority` when one is given. Mutates and
    returns `doc`.

    `signed_by` carries the public key so a peer can verify without a key-distribution round trip;
    `authority` names the issuing origin (D11) for the trust decision that sits above verification.
    Verifying the signature proves authorship; whether that author is trusted is a separate
    question, answered by the caller's trust gate."""
    doc["signature"] = priv.sign(canonical_operator(doc)).hex()
    doc["signed_by"] = public_key_hex(priv.public_key())
    if authority:
        doc["authority"] = authority
    return doc


def verify_operator(doc: Dict[str, Any], *, pub: Optional[Ed25519PublicKey] = None
                    ) -> Tuple[bool, str]:
    """`(ok, reason)` — is this operator authentic and internally consistent?

    Checks, in order, each failing closed with a distinct reason so unsigned, no-verifying-key and
    forged stay three separate outcomes:
      1. a signature is present at all (absent => draft, and a draft is inadmissible)
      2. the signature verifies against `pub`, or against the embedded `signed_by` if none is given

    On success the reason distinguishes the two strengths of the result: verified against a
    supplied key (authorship attested) versus self-consistent against the embedded key
    (authorship unattested). That distinction rides in the reason string rather than being
    collapsed into the boolean."""
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
                       "unattested; supply a trusted key to check who)")


# ── bundles ───────────────────────────────────────────────────────────────────────────────────
#
# A source bundle (runner.py's single distribution path) is signed with the same mechanism as an
# operator — Ed25519 over canonical bytes, `signature`/`signed_by` stamped beside the content —
# so there is one signing scheme. The canonical bytes are exactly the payload the bundle's sha256
# already covers (`runner._canonical`, which delegates to `prism.crystal_model.bundle_canonical`:
# group, entry_module, register_fns, host_seams, modules). Consequences:
#
#   * signing leaves the sha256 unchanged — the envelope fields sit outside the hashed payload,
#     exactly as an operator's `signature` sits outside `SIGNED_FIELDS`. A signed bundle is the
#     same content-addressed artifact as its unsigned twin.
#   * signature and sha attest the same bytes, so a bundle whose sha verifies has a signature over
#     that same payload — one canonicalization, defined once and reused on every side.
#   * like an operator, verifying against the embedded `signed_by` proves self-consistency. Who
#     signed — and whether that author's rung admits execution — is the runner's trust gate
#     (`runner.verify_provenance`), which binds the key to the store-resolved author artifact.


def _bundle_canonical(bundle: Dict[str, Any]) -> bytes:
    """The bundle's canonical bytes, taken from the contract (`prism.crystal_model`)."""
    from prism.crystal_model import bundle_canonical
    return bundle_canonical(bundle)


def sign_bundle(bundle: Dict[str, Any], priv: Ed25519PrivateKey, *,
                authority: str = "") -> Dict[str, Any]:
    """Publish a bundle: stamp `signature` (Ed25519 hex over the sha-canonical payload) and
    `signed_by` (the signer's public key, hex) — the operator envelope, applied to a bundle.
    Mutates and returns `bundle`. Raises KeyError on a malformed bundle, so a partial payload is
    never signed."""
    bundle["signature"] = sign_bytes(_bundle_canonical(bundle), priv)
    bundle["signed_by"] = public_key_hex(priv.public_key())
    if authority:
        bundle["authority"] = authority
    return bundle


def verify_bundle(bundle: Dict[str, Any], *, pub: Optional[Ed25519PublicKey] = None
                  ) -> Tuple[bool, str]:
    """`(ok, reason)` — mirror of `verify_operator` for bundles, same fail-closed order. Unsigned,
    no verifying key, malformed and forged each carry their own reason."""
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
                       "unattested; supply a trusted key to check who)")


def admit(doc: Dict[str, Any], *, host_offers=None, pub: Optional[Ed25519PublicKey] = None
          ) -> Tuple[bool, str]:
    """May this node run this operator? Signature + capability contract + runtime, in that order.

    Admission is separate from acquisition (D10): a node routinely holds operators it will not run,
    and an unadmitted operator stays held and visible, so it becomes runnable if the host later
    gains the capability, and so the agent can say what it would need.

    `host_offers` is the set of capability names this host publishes (D12). `None` means the host
    was not probed, and yields no admission rather than being read as "offers nothing" — has,
    hasn't, and didn't-probe stay three distinguishable states."""
    ok, why = verify_operator(doc, pub=pub)
    if not ok:
        return False, why
    if str(doc.get("kind") or "") not in ("source", "composition"):
        # D10: "source" and "composition" are the admissible kinds. A code-backed operator is
        # reachable and held, and becomes runnable once a sandbox exists — signing names the author,
        # and isolation is what bounds the harm.
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
