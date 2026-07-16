"""The trust floor works standalone — no `kernel`, no app `config`, just KEYS_DIR.

Proves bridge.trust can load a service identity, sign a service JWT,
and verify it against the on-disk authority manifest, entirely on its own.
"""
import base64
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _write_keyset(keys_dir, name="bridge"):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (keys_dir / f"{name}.private.pem").write_text(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
    )
    nums = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": f"{name}-1",
        "n": _b64u(nums.n.to_bytes((nums.n.bit_length() + 7) // 8, "big")),
        "e": _b64u(nums.e.to_bytes((nums.e.bit_length() + 7) // 8, "big")),
    }
    (keys_dir / "authority.manifest.json").write_text(json.dumps({
        "artifact_id": "test-authority",
        "content_type": "application/vnd.agience.authority+json",
        "schema_version": 1,
        "issuer": "https://platform.test",
        "trust_anchors": {name: {"uri": f"http://{name}", "jwks": {"keys": [jwk]}}},
        "bootstrap_token_hash": None,
    }))


def test_sign_and_verify_standalone(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    _write_keyset(tmp_path, "bridge")

    from bridge.trust import service_identity, authority_trust

    service_identity.reset_service_identity_for_tests()
    authority_trust.reset_authority_manifest_for_tests()

    service_identity.init_service_identity("bridge")
    token = service_identity.sign_service_jwt(audience="mantle")

    claims = authority_trust.verify_jwt(
        token, expected_issuer_service="bridge", expected_issuer_claim="bridge")
    assert claims["iss"] == "bridge"
    assert claims["aud"] == "mantle"
    assert claims["principal_type"] == "service"


def test_delegation_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    _write_keyset(tmp_path, "bridge")
    # instance.uuid lets get_host_id() resolve (stamped on every delegation)
    (tmp_path / "instance.uuid").write_text("11111111-1111-4111-8111-111111111111")

    from bridge.trust import service_identity, authority_trust

    service_identity.reset_service_identity_for_tests()
    authority_trust.reset_authority_manifest_for_tests()
    service_identity.init_service_identity("bridge")

    token = service_identity.sign_delegation_jwt(audience="agience-server-x", user_sub="user-42")
    claims = authority_trust.verify_delegation_jwt(
        token, expected_issuer="bridge", expected_audience="agience-server-x",
        expected_actor="bridge")
    assert claims["sub"] == "user-42"
    assert claims["act"]["sub"] == "bridge"
    assert claims["host_id"]  # resolved from instance.uuid
