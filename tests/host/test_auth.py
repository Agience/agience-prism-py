"""TokenVerifier precedence: authority RS256 JWT, local HS256 JWT, API key.

Mirrors the platform contract: a service self-signs an RS256 JWT (e.g. Mantle:
``iss=mantle, aud=prism``) and the host verifies it against the authority's
inline JWKS, selecting the key by ``kid``. HS256-local and static API keys are
fallbacks. An unconfigured verifier is open.
"""
from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from prism import AuthError, TokenVerifier


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def manifest_path(rsa_key, tmp_path):
    """An authority manifest carrying the public key under kid 'mantle-1'."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": "mantle-1", "use": "sig", "alg": "RS256"})
    manifest = {
        "issuer": "https://install",
        "artifact_id": "a",
        "trust_anchors": {"mantle": {"jwks": {"keys": [jwk]}}},
    }
    path = tmp_path / "authority.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return str(path)


def _rs256(rsa_key, *, aud="prism", iss="mantle", exp_in=300, kid="mantle-1"):
    now = int(time.time())
    return jwt.encode(
        {"iss": iss, "sub": "mantle", "aud": aud, "iat": now, "exp": now + exp_in},
        rsa_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _allows(verifier, header):
    try:
        verifier.verify(header)
        return True
    except AuthError:
        return False


# -- authority RS256 ---------------------------------------------------------

def test_rs256_authority_token_accepted(rsa_key, manifest_path):
    v = TokenVerifier(authority_manifest_path=manifest_path, expected_audiences=("prism", "agience"))
    assert _allows(v, "Bearer " + _rs256(rsa_key))
    # An Origin OAuth2 server token shape (aud=agience) verifies the same way.
    assert _allows(v, "Bearer " + _rs256(rsa_key, aud="agience"))


def test_rs256_rejections(rsa_key, manifest_path):
    v = TokenVerifier(authority_manifest_path=manifest_path, expected_audiences=("prism",))
    assert not _allows(v, "Bearer " + _rs256(rsa_key, aud="someone-else"))   # wrong aud
    assert not _allows(v, "Bearer " + _rs256(rsa_key, exp_in=-300))           # expired past leeway
    assert not _allows(v, "Bearer " + _rs256(rsa_key, kid="unknown-9"))       # unknown kid
    assert not _allows(v, "Bearer not.a.jwt")


def test_rs256_issuer_allowlist(rsa_key, manifest_path):
    v = TokenVerifier(
        authority_manifest_path=manifest_path,
        expected_audiences=("prism",),
        allowed_issuers=("mantle",),
    )
    assert _allows(v, "Bearer " + _rs256(rsa_key, iss="mantle"))
    assert not _allows(v, "Bearer " + _rs256(rsa_key, iss="chorus"))


# -- HS256 local fallback ----------------------------------------------------

def test_hs256_local_secret():
    secret = "a-local-shared-secret"
    v = TokenVerifier(hs256_secret=secret, expected_audiences=("prism",))

    def hs(aud="prism", exp_in=300, key=secret):
        now = int(time.time())
        return jwt.encode({"aud": aud, "iat": now, "exp": now + exp_in}, key, algorithm="HS256")

    assert _allows(v, "Bearer " + hs())
    assert not _allows(v, "Bearer " + hs(aud="nope"))
    assert not _allows(v, "Bearer " + hs(key="wrong-secret"))


# -- static API key ----------------------------------------------------------

def test_api_key_allowlist_multi():
    v = TokenVerifier(api_keys=("prod-key", "dev-key"))
    assert _allows(v, "Bearer prod-key")
    assert _allows(v, "Bearer dev-key")
    assert not _allows(v, "Bearer nope")
    assert not _allows(v, None)


def test_open_when_unconfigured():
    v = TokenVerifier()
    assert v.enabled is False
    assert _allows(v, None)
    assert _allows(v, "Bearer anything")


def test_api_keys_dir_hot_reload(tmp_path):
    d = tmp_path / "keys.d"
    d.mkdir()
    # refresh_s=0 → re-scan every check so the test observes changes at once.
    v = TokenVerifier(api_keys_dir=str(d), api_keys_dir_refresh_s=0)

    # Empty dir + no other creds → open (nothing enforced).
    assert v.enabled is False
    assert _allows(v, "Bearer anything")

    # Drop a key file → enforced; that key accepted, others rejected.
    (d / "prod.key").write_text("prod-key\n", encoding="utf-8")
    assert v.enabled is True
    assert _allows(v, "Bearer prod-key")
    assert not _allows(v, "Bearer dev-key")

    # Add a consumer live (no restart).
    (d / "dev.key").write_text("dev-key", encoding="utf-8")
    assert _allows(v, "Bearer prod-key") and _allows(v, "Bearer dev-key")

    # Revoke by removing the file.
    (d / "prod.key").unlink()
    assert not _allows(v, "Bearer prod-key")
    assert _allows(v, "Bearer dev-key")

    # Multi-line + comments + blanks; dotfiles ignored.
    (d / "batch.keys").write_text("# team\nk1\n\n  k2  \n#k3\n", encoding="utf-8")
    (d / ".hidden").write_text("ignored", encoding="utf-8")
    assert _allows(v, "Bearer k1") and _allows(v, "Bearer k2")
    assert not _allows(v, "Bearer k3") and not _allows(v, "Bearer ignored")


def test_api_keys_dir_missing_is_open(tmp_path):
    v = TokenVerifier(api_keys_dir=str(tmp_path / "nope"), api_keys_dir_refresh_s=0)
    assert v.enabled is False
    assert _allows(v, None)


def test_inline_and_dir_keys_coexist(tmp_path):
    d = tmp_path / "keys.d"
    d.mkdir()
    (d / "dev.key").write_text("dir-key", encoding="utf-8")
    v = TokenVerifier(api_keys=("inline-key",), api_keys_dir=str(d), api_keys_dir_refresh_s=0)
    assert _allows(v, "Bearer inline-key") and _allows(v, "Bearer dir-key")
    assert not _allows(v, "Bearer nope")


def test_jwt_primary_with_api_key_fallback(rsa_key, manifest_path):
    v = TokenVerifier(
        authority_manifest_path=manifest_path,
        expected_audiences=("prism",),
        api_keys=("fallback-key",),
    )
    assert _allows(v, "Bearer " + _rs256(rsa_key))   # authority JWT
    assert _allows(v, "Bearer fallback-key")          # static fallback
    assert not _allows(v, "Bearer wrong")
