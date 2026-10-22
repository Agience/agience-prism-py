"""A sealed secret opens with the key it was sealed to, for the use it was sealed for, and nothing
else; and a persona with its own key pair makes its delegation exchange as itself.

2026-10-19: secrets released for use crossed Mantle's response, the edge and the persona's
transport in plaintext, and every persona signed as the shared `chorus` identity.
"""
from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

from prism.trust import sealing, service_identity
from prism.trust.server_auth import ServerAuth


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(key):
    nums = key.public_key().public_numbers()

    def b(i):
        return sealing._b64(i.to_bytes((i.bit_length() + 7) // 8, "big"))
    return {"kty": "RSA", "n": b(nums.n), "e": b(nums.e), "kid": "lumen-1"}


def test_a_seal_opens_for_its_key_and_use():
    k = _key()
    s = sealing.seal(b"sk-secret", sealing.public_key_from_jwk(_jwk(k)), kid="lumen-1", context="key-1|conn-1")
    assert "sk-secret" not in str(s)
    assert sealing.open_sealed(s, k, kid="lumen-1", context="key-1|conn-1") == b"sk-secret"


@pytest.mark.parametrize("other", ["key", "kid", "context"])
def test_a_seal_does_not_open_for_another_key_name_or_use(other):
    k = _key()
    s = sealing.seal(b"sk-secret", k.public_key(), kid="lumen-1", context="key-1|conn-1")
    with pytest.raises(sealing.SealError):
        sealing.open_sealed(s, _key() if other == "key" else k,
                            kid="iris-1" if other == "kid" else "lumen-1",
                            context="key-1|conn-2" if other == "context" else "key-1|conn-1")


def test_a_persona_with_its_own_key_makes_its_exchange_as_itself(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    service_identity.reset_service_identity_for_tests()
    for name in ("chorus", "lumen"):
        (tmp_path / f"{name}.private.pem").write_bytes(_key().private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    service_identity.init_service_identity("chorus")
    try:
        lumen = ServerAuth("agience-server-lumen", "http://mantle", token_exchange=lambda *a: None)
        claims = jose_jwt.get_unverified_claims(lumen.sign_exchange_jwt())
        assert claims["iss"] == claims["sub"] == "lumen" and claims["client_id"] == "agience-server-lumen"
        assert jose_jwt.get_unverified_header(lumen.sign_exchange_jwt())["kid"] == "lumen-1"

        sage = ServerAuth("agience-server-sage", "http://mantle", token_exchange=lambda *a: None)
        assert jose_jwt.get_unverified_claims(sage.sign_exchange_jwt())["iss"] == "chorus", \
            "a persona holding no key of its own still exchanges, as chorus"
    finally:
        service_identity.reset_service_identity_for_tests()
