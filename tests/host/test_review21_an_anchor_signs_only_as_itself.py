"""A key in the authority manifest signs only as the anchor it is listed under (review 21, F2).

`TokenVerifier` picked the verifying key by `kid` from every anchor together and never asked whose
key it was, so Mantle's key could sign a token claiming any issuer, Origin's included, and it was
taken as that issuer's. Each `kid` now remembers its anchor, and a token's `iss` must be that
anchor's name; the manifest's issuer (Origin's URL) is accepted only from the `origin` anchor.
"""
from __future__ import annotations

import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from prism import TokenVerifier

from .test_auth import _allows, _rs256

ISSUER = "https://install"


@pytest.fixture(scope="module")
def keys():
    return {n: rsa.generate_private_key(public_exponent=65537, key_size=2048)
            for n in ("mantle", "origin")}


@pytest.fixture()
def verifier(keys, tmp_path):
    def jwk(name):
        j = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keys[name].public_key()))
        j.update({"kid": f"{name}-1", "use": "sig", "alg": "RS256"})
        return j

    path = tmp_path / "authority.manifest.json"
    path.write_text(json.dumps({"issuer": ISSUER, "artifact_id": "a", "trust_anchors": {
        n: {"jwks": {"keys": [jwk(n)]}} for n in keys}}), encoding="utf-8")
    return TokenVerifier(authority_manifest_path=str(path), expected_audiences=("prism",))


def test_each_anchor_signs_as_itself(keys, verifier):
    assert _allows(verifier, "Bearer " + _rs256(keys["mantle"], iss="mantle", kid="mantle-1"))
    assert _allows(verifier, "Bearer " + _rs256(keys["origin"], iss=ISSUER, kid="origin-1"))
    assert _allows(verifier, "Bearer " + _rs256(keys["origin"], iss="origin", kid="origin-1"))


@pytest.mark.parametrize("iss", [ISSUER, "origin", "chorus", ""])
def test_mantle_s_key_signs_as_no_one_else(keys, verifier, iss):
    assert not _allows(verifier, "Bearer " + _rs256(keys["mantle"], iss=iss, kid="mantle-1"))


@pytest.mark.parametrize("extra", [
    {"principal_type": "delegation"},                         # a delegation naming no actor
    {"principal_type": "delegation", "act": {}},
    {"principal_type": "server"},                             # a program the host never takes
])
def test_a_token_naming_no_actor_or_no_caller_is_refused(keys, verifier, extra):
    """Review 23, I1: the host refuses a delegation with no `act.sub`, and a principal type that is
    neither a caller nor a service."""
    assert _allows(verifier, "Bearer " + _rs256(keys["mantle"], iss="mantle", kid="mantle-1"))
    assert not _allows(verifier, "Bearer " + _rs256(keys["mantle"], iss="mantle", kid="mantle-1",
                                                     **extra))
