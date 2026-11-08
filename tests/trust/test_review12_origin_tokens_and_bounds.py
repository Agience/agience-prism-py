"""Review 12, H4 and M8, in prism.

H4: every path that takes an Origin token checks its `iss` against the authority manifest's issuer,
so a token from another issuer signed with a key the manifest happens to trust (staging's, before
it had its own) is refused: `verify_access_token`, `ServerAuth.verify_origin_delegation` and
`ServerAuth.verify_narrowed_delegation`.

M8: the sign-in bounds poller reads Origin's rows by sequence (`after=<seq>`), keeps the bounds on
disk, refuses every token until its first good poll after a start and once its last good poll is
too old, and refuses a token with no `iat`.
"""
from __future__ import annotations

import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

ISS = "https://origin.test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _pem():
    return KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    from prism.trust import authority_trust

    pub = KEY.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    j = jwk.construct(pub, "RS256").to_dict()
    j = {a: (b.decode() if isinstance(b, bytes) else b) for a, b in j.items()}
    j.update({"kid": "origin-1", "use": "sig", "alg": "RS256"})
    path = tmp_path / "authority.manifest.json"
    path.write_text(json.dumps({"issuer": ISS, "artifact_id": "m",
                                "trust_anchors": {"origin": {"jwks": {"keys": [j]}}}}))
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    monkeypatch.setenv("AUTHORITY_MANIFEST_PATH", str(path))
    monkeypatch.setattr(authority_trust, "_manifest", None, raising=False)
    authority_trust.load_authority_manifest()
    yield path
    authority_trust._manifest = None


def _sign(claims):
    return jwt.encode(claims, _pem(), algorithm="RS256", headers={"kid": "origin-1"})


def _claims(**over):
    now = int(time.time())
    c = {"iss": ISS, "sub": "p-1", "aud": ISS, "iat": now, "exp": now + 300}
    c.update(over)
    return c


def test_an_access_token_from_another_issuer_is_refused(manifest):
    from jose.exceptions import JWTError

    from prism.trust.authority_trust import verify_access_token
    assert verify_access_token(_sign(_claims()), delegation_audiences=())["sub"] == "p-1"
    with pytest.raises(JWTError):
        verify_access_token(_sign(_claims(iss="https://staging.origin.test")),
                            delegation_audiences=())


def _server(name="lumen"):
    from prism.trust.server_auth import ServerAuth
    s = ServerAuth.__new__(ServerAuth)
    s.client_id = f"agience-server-{name}"
    return s


def test_an_origin_delegation_from_another_issuer_is_refused(manifest):
    s = _server()
    d = _claims(aud=s.client_id, act={"sub": s.client_id}, principal_type="delegation")
    assert s.verify_origin_delegation(_sign(d)) is not None
    assert s.verify_origin_delegation(_sign({**d, "iss": "https://staging.origin.test"})) is None


def test_a_narrowed_delegation_from_another_issuer_is_refused(manifest):
    s = _server()
    d = _claims(aud="lumen", act={"sub": "lumen"}, principal_type="delegation",
                scope="persona:lumen", narrowed=True)
    assert s.verify_narrowed_delegation(_sign(d)) is not None
    assert s.verify_narrowed_delegation(_sign({**d, "iss": "https://staging.origin.test"})) is None


# -- M8: the bounds ---------------------------------------------------------------------------

def _poller(tmp_path, docs, monkeypatch):
    from prism.trust import not_before
    monkeypatch.delenv("AGIENCE_NOT_BEFORE_NO_POLL", raising=False)
    urls = []

    def fetch(url):
        urls.append(url)
        return docs.pop(0) if docs else None

    nb = not_before.NotBefore("https://origin.test", fetch=fetch, verify=lambda d: d,
                              state_path=str(tmp_path / "nb.json"))
    return nb, urls


def test_a_restarted_peer_refuses_every_token_until_its_first_good_poll(tmp_path, monkeypatch):
    nb, _ = _poller(tmp_path, [{"seq": 3, "iat": time.time(), "entries": []}], monkeypatch)
    assert nb.refused(_claims())                 # no poll yet: fail closed
    nb.poll_once()
    assert not nb.refused(_claims())


def test_a_token_with_no_iat_is_refused(tmp_path, monkeypatch):
    nb, _ = _poller(tmp_path, [{"seq": 1, "iat": time.time(), "entries": []}], monkeypatch)
    nb.poll_once()
    c = _claims()
    c.pop("iat")
    assert nb.refused(c)


def test_a_stale_document_fails_closed(tmp_path, monkeypatch):
    from prism.trust import not_before
    nb, _ = _poller(tmp_path, [{"seq": 1, "iat": time.time(), "entries": []}], monkeypatch)
    nb.poll_once()
    nb._last_good = time.monotonic() - not_before.STALE_SECONDS - 1
    assert nb.refused(_claims())


def test_rows_are_read_by_sequence_and_a_late_commit_is_not_skipped(tmp_path, monkeypatch):
    now = time.time()
    docs = [{"seq": 5, "iat": now, "entries": [{"seq": 5, "sub": "p-1", "not_before": now - 10}]},
            {"seq": 6, "iat": now, "entries": [{"seq": 6, "sub": "p-2",
                                                "not_before": now - 3600}]}]
    nb, urls = _poller(tmp_path, docs, monkeypatch)
    nb.poll_once()
    nb.poll_once()
    assert "after=0" in urls[0] and "after=5" in urls[1]
    assert nb.refused(_claims(sub="p-2", iat=int(now - 7200)))


def test_the_bounds_survive_a_restart(tmp_path, monkeypatch):
    from prism.trust import not_before
    now = time.time()
    nb, _ = _poller(tmp_path, [{"seq": 2, "iat": now, "entries": [
        {"seq": 2, "sub": "p-1", "not_before": now}]}], monkeypatch)
    nb.poll_once()
    again = not_before.NotBefore("https://origin.test", fetch=lambda u: None,
                                 verify=lambda d: d, state_path=str(tmp_path / "nb.json"))
    assert again._by_sub.get("p-1") == pytest.approx(now) and again._seq == 2


# -- review 14: a replayed or old bounds document is no good poll -------------------------------

def test_a_bounds_document_older_than_the_last_accepted_is_refused(tmp_path, monkeypatch):
    """A captured, validly signed bounds document replayed later keeps no poller fresh: one whose
    `iat` is older than the last accepted is ignored and is no good poll."""
    now = time.time()
    nb, _ = _poller(tmp_path, [{"seq": 2, "iat": now, "entries": []},
                               {"seq": 1, "iat": now - 30, "entries": [
                                   {"seq": 1, "sub": "p-1", "not_before": now - 100}]}],
                    monkeypatch)
    nb.poll_once()
    nb._last_good = time.monotonic() - 100
    assert nb.poll_once() == [] and "p-1" not in nb._by_sub
    assert nb._last_good < time.monotonic() - 99                 # the replay refreshed nothing


def test_a_bounds_document_with_no_iat_or_past_the_freshness_window_is_refused(tmp_path,
                                                                                monkeypatch):
    from prism.trust import not_before
    now = time.time()
    nb, _ = _poller(tmp_path, [{"seq": 1, "entries": []},
                               {"seq": 1, "iat": now - not_before.STALE_SECONDS - 5,
                                "entries": []}], monkeypatch)
    nb.poll_once()
    nb.poll_once()
    assert nb._last_good is None and nb.refused(_claims())


def test_the_last_accepted_iat_survives_a_restart(tmp_path, monkeypatch):
    from prism.trust import not_before
    now = time.time()
    nb, _ = _poller(tmp_path, [{"seq": 2, "iat": now, "entries": []}], monkeypatch)
    nb.poll_once()
    again = not_before.NotBefore("https://origin.test",
                                 fetch=lambda u: {"seq": 1, "iat": now - 10, "entries": []},
                                 verify=lambda d: d, state_path=str(tmp_path / "nb.json"))
    again.poll_once()
    assert again._last_good is None
