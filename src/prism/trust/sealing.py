"""Sealing a secret to the one key that will use it.

A secret released for use (`POST /artifacts/{id}/use` on Mantle) travels sealed to the executor's
public key: what Mantle answers, what crosses the edge and anything that logs a response carry
ciphertext, and the plaintext exists only inside the executor, at the call it serves.

    RSA-OAEP (SHA-256) wraps a fresh AES-256-GCM key; the secret is encrypted under it.

The associated data binds the seal to its context — the recipient's key id, the credential and
the card it was released for — so a sealed secret opens only for that use and cannot be replayed as
another. RSA keys because they are what every platform identity already is (`<name>.private.pem`,
anchored in the authority manifest as a JWK).
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALG = "RSA-OAEP-256+A256GCM"


class SealError(ValueError):
    """A seal could not be made or opened. The message names why and carries no secret."""


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def public_key_from_jwk(jwk: Dict[str, Any]) -> rsa.RSAPublicKey:
    """An RSA public key from a JWK as the authority manifest anchors it."""
    if jwk.get("kty") != "RSA":
        raise SealError("only RSA keys can be sealed to")
    n = int.from_bytes(_unb64(jwk["n"]), "big")
    e = int.from_bytes(_unb64(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _aad(kid: str, context: str) -> bytes:
    return f"{ALG}|{kid}|{context}".encode("utf-8")


def seal(plaintext: bytes, public_key: rsa.RSAPublicKey, *, kid: str, context: str) -> Dict[str, str]:
    """`plaintext` sealed to `public_key` (named `kid`), bound to `context`."""
    cek, iv = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ct = AESGCM(cek).encrypt(iv, plaintext, _aad(kid, context))
    ek = public_key.encrypt(cek, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),
                                              algorithm=hashes.SHA256(), label=None))
    return {"alg": ALG, "kid": kid, "ek": _b64(ek), "iv": _b64(iv), "ct": _b64(ct)}


def open_sealed(sealed: Dict[str, str], private_key: rsa.RSAPrivateKey, *, kid: str, context: str) -> bytes:
    """The plaintext of a seal made to `kid` for `context`. Refuses any other key or context."""
    if not isinstance(sealed, dict) or sealed.get("alg") != ALG:
        raise SealError("not a sealed secret")
    if sealed.get("kid") != kid:
        raise SealError(f"sealed to {sealed.get('kid')!r}, not to {kid!r}")
    try:
        cek = private_key.decrypt(_unb64(sealed["ek"]), padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return AESGCM(cek).decrypt(_unb64(sealed["iv"]), _unb64(sealed["ct"]), _aad(kid, context))
    except Exception:
        raise SealError("the seal does not open with this key for this use") from None
