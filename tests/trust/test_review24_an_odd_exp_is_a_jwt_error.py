"""Review 24, tidy: an `exp` that is null or not a number is a `JWTError`, like any bad claim.

`verify_jwt` let python-jose's `TypeError` through for a null `exp`, so a caller catching only
`JWTError` (Crystal's relay socket catches `KeyError` and `JWTError`) let it escape. Tokens are
signed here with a throwaway key anchored as `origin` in a manifest held in memory.
"""
from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import JWTError, jwk, jwt

from prism.trust import authority_trust as at


@pytest.fixture
def sign(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    j = jwk.construct(pub, "RS256").to_dict()
    j.update({"kid": "o-1", "alg": "RS256"})
    monkeypatch.setattr(at, "_manifest", at.AuthorityManifest(
        issuer="https://iss.test", artifact_id="m", trust_anchors={"origin": {"jwks": {"keys": [j]}}},
        bootstrap_token_hash=None, raw={}))
    now = int(time.time())

    def _sign(**claims):
        body = {"iss": "https://iss.test", "sub": "s", "aud": "x", "iat": now, "exp": now + 60}
        body.update(claims)
        return jwt.encode(body, pem, algorithm="RS256", headers={"kid": "o-1"})
    return _sign


@pytest.mark.parametrize("exp", [None, "soon", [1], {"a": 1}])
def test_an_odd_exp_is_a_jwt_error(sign, exp):
    with pytest.raises(JWTError):
        at.verify_origin_jwt(sign(exp=exp))


def test_a_good_token_still_verifies(sign):
    assert at.verify_origin_jwt(sign())["sub"] == "s"
