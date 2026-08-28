"""`prism.trust.server_auth` — the persona/MCP host adapter.

The oracle is independent of the subject. Every token below is minted right here with `jose` and a
key this file generated, against a manifest this file wrote. Nothing under test helps build the
input, so a bug that made the verifier accept everything could not also make the fixture produce
something it accepts.

The tamper is at the byte level. base64url packs 6 bits per character, so the final character of an
N-byte signature carries only the bits that do not divide evenly — for a 32-byte Ed25519 signature
that is 2 significant bits, and 4 of the 64 possible final characters decode to identical bytes.
Substituting trailing base64url characters therefore leaves the signature intact one time in sixteen
(one in 4096 for a two-character variant). Here the signature is decoded to bytes, one byte is XOR'd,
`assert` proves the bytes differ, and only then is it re-encoded.

Every negative has a positive control beside it. "It raised" is not evidence the signature was what
got checked — a typo in the fixture raises just as loudly.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt as jose_jwt

CLIENT_ID = "agience-server-iris"
ISSUER_URL = "https://platform.test"


# ── the oracle: keys, a manifest, and a signer that is not the subject ────────────────────────────
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class _Service:
    """One signing service: a keypair, its JWK, and a `sign(claims)` that emits RS256."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.kid = f"{name}-1"
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.pem = self.key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
        n = self.key.public_key().public_numbers()
        self.jwk = {
            "kty": "RSA", "alg": "RS256", "use": "sig", "kid": self.kid,
            "n": _b64u(n.n.to_bytes((n.n.bit_length() + 7) // 8, "big")),
            "e": _b64u(n.e.to_bytes((n.e.bit_length() + 7) // 8, "big")),
        }

    def sign(self, claims: dict) -> str:
        return jose_jwt.encode(claims, self.pem, algorithm="RS256", headers={"kid": self.kid})


@pytest.fixture()
def floor(tmp_path, monkeypatch):
    """A KEYS_DIR holding a chorus identity plus mantle/origin trust anchors."""
    monkeypatch.setenv("KEYS_DIR", str(tmp_path))
    monkeypatch.delenv("AUTHORITY_ISSUER", raising=False)

    services = {name: _Service(name) for name in ("chorus", "mantle", "origin")}
    (tmp_path / "chorus.private.pem").write_text(services["chorus"].pem)
    (tmp_path / "authority.manifest.json").write_text(json.dumps({
        "artifact_id": "test-authority",
        "content_type": "application/vnd.agience.authority+json",
        "schema_version": 1,
        "issuer": ISSUER_URL,
        "trust_anchors": {
            name: {"uri": f"http://{name}.test", "jwks": {"keys": [svc.jwk]}}
            for name, svc in services.items()
        },
        "bootstrap_token_hash": None,
    }))

    from prism.trust import authority_trust, service_identity

    service_identity.reset_service_identity_for_tests()
    authority_trust.reset_authority_manifest_for_tests()
    service_identity.init_service_identity("chorus")
    yield services
    service_identity.reset_service_identity_for_tests()
    authority_trust.reset_authority_manifest_for_tests()


def _auth(**kw):
    from prism.trust import ServerAuth

    return ServerAuth(CLIENT_ID, "http://mantle.test", **kw)


def _now() -> int:
    return int(time.time())


def _mantle_delegation(svc: _Service, *, aud=CLIENT_ID, actor="mantle", sub="user-1",
                       ttl=300, principal_type="delegation") -> str:
    return svc.sign({
        "iss": "mantle", "sub": sub, "aud": aud, "act": {"sub": actor},
        "host_id": "host-1", "principal_type": principal_type,
        "iat": _now(), "exp": _now() + ttl,
    })


def _origin_delegation(svc: _Service, *, aud=CLIENT_ID, actor=CLIENT_ID, sub="user-1",
                       ttl=300, principal_type="delegation") -> str:
    return svc.sign({
        "iss": ISSUER_URL, "sub": sub, "aud": aud, "act": {"sub": actor},
        "principal_type": principal_type, "iat": _now(), "exp": _now() + ttl,
    })


def _origin_user_token(svc: _Service, *, aud="agience", sub="user-1", ttl=300, **extra) -> str:
    claims = {"iss": ISSUER_URL, "sub": sub, "aud": aud, "iat": _now(), "exp": _now() + ttl}
    claims.update(extra)
    return svc.sign(claims)


def _tamper_signature(token: str) -> str:
    """Flip one bit of one byte of the signature, and prove the bytes actually changed.

    Decode → XOR → assert-different → re-encode. A character-level edit cannot make this promise;
    see the module docstring for the 4-in-64 collision."""
    head, payload, sig = token.split(".")
    raw = bytearray(_b64u_decode(sig))
    original = bytes(raw)
    raw[0] ^= 0x01
    assert bytes(raw) != original, "the tamper changed no bytes — this control proves nothing"
    return f"{head}.{payload}.{_b64u(bytes(raw))}"


# ── verify_delegation_jwt: Mantle-minted, aud = this persona ───────────────────────────────────────
def test_a_valid_mantle_delegation_verifies(floor):
    """Positive control. Everything below asserts that a bad token does not verify; without this
    one, a fixture that produced garbage would look like a working verifier."""
    claims = _auth().verify_delegation_jwt(_mantle_delegation(floor["mantle"]))
    assert claims is not None and claims["sub"] == "user-1"
    assert claims["aud"] == CLIENT_ID and claims["act"]["sub"] == "mantle"


def test_a_tampered_signature_is_refused(floor):
    """The negative control on the auth path: a tampered signature does not verify. Byte-level
    tamper; see `_tamper_signature`.

    It isolates the signature as the cause: only the third segment changed, so the two tokens carry
    byte-identical headers and byte-identical claims. That is asserted rather than assumed, since a
    failure over an expired token or a missing `aud` would otherwise read as a signature check
    working."""
    auth, good = _auth(), _mantle_delegation(floor["mantle"])
    assert auth.verify_delegation_jwt(good) is not None, "positive control failed FIRST"

    bad = _tamper_signature(good)
    assert bad.rsplit(".", 1)[0] == good.rsplit(".", 1)[0], "more than the signature changed"
    assert jose_jwt.get_unverified_claims(bad) == jose_jwt.get_unverified_claims(good)
    assert auth.verify_delegation_jwt(bad) is None


def test_a_signature_from_the_wrong_service_is_refused(floor):
    """Signed by origin's key, claiming `iss: mantle`. The claim is right and the key is wrong,
    which is the check the JWKS anchor exists to make."""
    forged = floor["origin"].sign({
        "iss": "mantle", "sub": "user-1", "aud": CLIENT_ID, "act": {"sub": "mantle"},
        "principal_type": "delegation", "iat": _now(), "exp": _now() + 300,
    })
    assert _auth().verify_delegation_jwt(forged) is None


def test_a_delegation_for_another_persona_is_refused(floor):
    assert _auth().verify_delegation_jwt(
        _mantle_delegation(floor["mantle"], aud="agience-server-sage")) is None


def test_a_delegation_with_the_wrong_actor_is_refused(floor):
    assert _auth().verify_delegation_jwt(
        _mantle_delegation(floor["mantle"], actor="chorus")) is None


def test_an_expired_delegation_is_refused(floor):
    assert _auth().verify_delegation_jwt(
        _mantle_delegation(floor["mantle"], ttl=-60)) is None


def test_a_non_delegation_principal_type_is_refused(floor):
    assert _auth().verify_delegation_jwt(
        _mantle_delegation(floor["mantle"], principal_type="service")) is None


def test_an_empty_token_is_refused(floor):
    assert _auth().verify_delegation_jwt("") is None


# ── verify_origin_delegation: the gateway / event path ────────────────────────────────────────────
def test_a_valid_origin_delegation_verifies(floor):
    claims = _auth().verify_origin_delegation(_origin_delegation(floor["origin"]))
    assert claims is not None and claims["act"]["sub"] == CLIENT_ID


def test_a_tampered_origin_delegation_is_refused(floor):
    auth, good = _auth(), _origin_delegation(floor["origin"])
    assert auth.verify_origin_delegation(good) is not None, "positive control failed FIRST"
    assert auth.verify_origin_delegation(_tamper_signature(good)) is None


def test_an_origin_delegation_acting_as_someone_else_is_refused(floor):
    assert _auth().verify_origin_delegation(
        _origin_delegation(floor["origin"], actor="agience-server-sage")) is None


def test_an_origin_delegation_for_another_audience_is_refused(floor):
    assert _auth().verify_origin_delegation(
        _origin_delegation(floor["origin"], aud="agience-server-sage")) is None


def test_a_mantle_signed_origin_delegation_is_refused(floor):
    """Right shape, wrong signer — verified against the `origin` anchor, so mantle's key must fail."""
    assert _auth().verify_origin_delegation(_origin_delegation(floor["mantle"])) is None


# ── verify_user_jwt ───────────────────────────────────────────────────────────────────────────────
def test_a_valid_user_token_verifies(floor):
    claims = _auth().verify_user_jwt(_origin_user_token(floor["origin"]))
    assert claims is not None and claims["sub"] == "user-1"


def test_a_tampered_user_token_is_refused(floor):
    auth, good = _auth(), _origin_user_token(floor["origin"])
    assert auth.verify_user_jwt(good) is not None, "positive control failed FIRST"
    assert auth.verify_user_jwt(_tamper_signature(good)) is None


def test_a_delegation_is_not_a_user_token(floor):
    """A delegation carries platform reach; letting it through here would skip the actor check."""
    assert _auth().verify_user_jwt(_origin_delegation(floor["origin"])) is None


def test_a_user_token_without_an_audience_is_refused(floor):
    tok = floor["origin"].sign(
        {"iss": ISSUER_URL, "sub": "user-1", "iat": _now(), "exp": _now() + 300})
    assert _auth().verify_user_jwt(tok) is None


def test_verify_core_jwt_is_the_same_function(floor):
    auth, tok = _auth(), _origin_user_token(floor["origin"])
    assert auth.verify_core_jwt(tok) == auth.verify_user_jwt(tok)


# ── outbound signing + headers ────────────────────────────────────────────────────────────────────
def test_sign_self_jwt_names_the_persona_and_verifies_as_chorus(floor):
    from prism.trust import authority_trust

    token = _auth().sign_self_jwt(audience="mantle")
    claims = authority_trust.verify_jwt(
        token, expected_issuer_service="chorus", expected_issuer_claim="chorus")
    assert claims["iss"] == "chorus" and claims["sub"] == "chorus"
    assert claims["client_id"] == CLIENT_ID and claims["aud"] == "mantle"
    assert claims["principal_type"] == "service"


def test_headers_carry_the_service_jwt(floor):
    h = _auth().headers()
    assert h["Content-Type"] == "application/json"
    assert h["Authorization"].startswith("Bearer ")


def test_user_headers_fall_back_to_the_service_jwt(floor):
    auth = _auth()
    assert auth.user_headers()["Authorization"].startswith("Bearer ")


def test_user_headers_present_the_delegation_when_one_is_in_context(floor):
    auth = _auth()
    tok = _mantle_delegation(floor["mantle"])
    reset = auth.request_user_token.set(tok)
    try:
        assert auth.user_headers()["Authorization"] == f"Bearer {tok}"
    finally:
        auth.request_user_token.reset(reset)


def test_require_user_headers_raises_without_a_delegation(floor):
    """Fail closed. `user_headers` resolving to the platform JWT would make Mantle apply platform
    authority to a caller-chosen resource id."""
    from prism.trust import MissingDelegationError

    with pytest.raises(MissingDelegationError):
        _auth().require_user_headers()


def test_require_user_headers_returns_the_delegation_when_present(floor):
    auth = _auth()
    tok = _mantle_delegation(floor["mantle"])
    reset = auth.request_user_token.set(tok)
    try:
        assert auth.require_user_headers()["Authorization"] == f"Bearer {tok}"
    finally:
        auth.request_user_token.reset(reset)


def test_get_delegation_user_id(floor):
    auth = _auth()
    assert auth.get_delegation_user_id() == "anonymous"
    reset = auth.request_user_token.set(_mantle_delegation(floor["mantle"], sub="user-42"))
    try:
        assert auth.get_delegation_user_id() == "user-42"
    finally:
        auth.request_user_token.reset(reset)
    reset = auth.request_user_token.set("not-a-jwt")
    try:
        assert auth.get_delegation_user_id() == "anonymous"
    finally:
        auth.request_user_token.reset(reset)


# ── the ASGI middleware ───────────────────────────────────────────────────────────────────────────
async def _run_middleware(auth, token: str) -> str:
    """Drive the middleware once and report what the ContextVar held inside the request.

    Returns "" when the inner app was never reached — since `require_auth` defaults on, that is
    what an unauthenticated request leaves behind here. Use `_drive` when the response is the thing
    under test.
    """
    seen, _ = await _drive(auth, token)
    return seen


async def _drive(auth, token: str, *, method: str = "POST", host: str = "aria.home.agience.ai"):
    """Drive the middleware and return (captured ContextVar, response or None).

    A real `send` is supplied because the middleware can answer for itself — sending a 401 response
    is part of what enforcement means here.
    """
    seen: dict = {}
    sent: dict = {}

    async def _inner(scope, receive, send):
        seen["token"] = auth.request_user_token.get("")

    async def _send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
            sent["headers"] = {k.decode().lower(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            sent["body"] = message.get("body", b"").decode()

    app = auth.make_middleware_class()(_inner)
    headers = [(b"host", host.encode())]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    await app({"type": "http", "method": method, "headers": headers}, None, _send)
    return seen.get("token", ""), (sent or None)


def test_middleware_stores_a_mantle_delegation(floor):
    auth = _auth(token_exchange=_never_called)
    tok = _mantle_delegation(floor["mantle"])
    assert asyncio.run(_run_middleware(auth, tok)) == tok
    assert auth.request_user_token.get("") == "", "the ContextVar leaked past the request"


def test_middleware_stores_an_origin_delegation(floor):
    auth = _auth(token_exchange=_never_called)
    tok = _origin_delegation(floor["origin"])
    assert asyncio.run(_run_middleware(auth, tok)) == tok


def test_middleware_stores_nothing_for_a_tampered_delegation(floor):
    """The token verifies as neither shape, so the exchange is attempted and declines. The
    ContextVar ends up empty rather than holding an unverified token."""
    # `require_auth=False` isolates the capture semantics under test here. Enforcement is a
    # separate contract with its own tests below; conflating them would leave the "verifies as
    # neither shape" behaviour untested the day enforcement changes.
    auth = _auth(token_exchange=_declines, require_auth=False)
    tampered = _tamper_signature(_mantle_delegation(floor["mantle"]))
    assert asyncio.run(_run_middleware(auth, tampered)) == ""


def test_middleware_exchanges_a_raw_user_token(floor):
    """The gateway model: a forwarded user token is swapped for a delegation by Origin."""
    calls: list = []

    async def _exchange(origin_uri, client_id, subject_token, authorization):
        calls.append((origin_uri, client_id, subject_token, authorization))
        return "minted-delegation"

    auth = _auth(token_exchange=_exchange)
    user = _origin_user_token(floor["origin"])
    assert asyncio.run(_run_middleware(auth, user)) == "minted-delegation"
    assert len(calls) == 1
    assert calls[0][1] == CLIENT_ID and calls[0][2] == user
    assert calls[0][3].startswith("Bearer ")


def test_a_garbage_token_never_reaches_the_exchange(floor):
    """The local fast-fail verify keeps an unauthenticated caller from making this persona hammer
    Origin. `_never_called` fires if it regresses."""
    auth = _auth(token_exchange=_never_called, require_auth=False)
    assert asyncio.run(_run_middleware(auth, "not-a-jwt")) == ""


def test_a_non_http_scope_passes_straight_through(floor):
    auth = _auth(token_exchange=_never_called)
    hit = []

    async def _inner(scope, receive, send):
        hit.append(scope["type"])

    app = auth.make_middleware_class()(_inner)
    asyncio.run(app({"type": "websocket"}, None, None))
    assert hit == ["websocket"]


async def _never_called(*a, **kw):
    raise AssertionError("the issuance client was called when it must not have been")


async def _declines(*a, **kw):
    return None


# ── the issuance seam ─────────────────────────────────────────────────────────────────────────────
def test_the_default_exchange_is_stdlib_and_prism_gained_no_http_dependency():
    """The constraint that decided the design. `prism`'s base install is dependency-free and each
    extra "names only what its own modules import". `httpx` belongs to the `host` and `server`
    extras and deliberately stays out of `trust` — the trust floor is sign/verify, not network. So
    the exchange is an injected seam whose default is `urllib.request`.

    This reads the module source, so it fails on a re-added import even though the environment here
    has httpx installed, which is exactly why a bare `import httpx` would prove nothing."""
    import ast
    import pathlib

    import prism.trust.server_auth as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = imported & {"httpx", "requests", "aiohttp", "fastapi", "starlette", "uvicorn"}
    assert not forbidden, f"server_auth grew an HTTP/web dependency: {sorted(forbidden)}"
    assert "urllib" in imported, "the stdlib fallback exchange is gone"


def test_the_module_imports_with_every_web_package_blocked():
    """The AST pass above reads source, and source analysis cannot see an import through
    `importlib`, a `__getattr__` that fires on load, or a transitive pull from a sibling module.
    This blocks the web packages outright with a `meta_path` finder that raises, then imports
    `prism.trust.server_auth` for real and constructs one — in a subprocess, because the packages
    are installed here and blocking them in this interpreter would not survive `sys.modules`.

    Same mechanism as `test_contract_install_is_pure.py`, applied to the `trust` extra: a `[trust]`
    install has jose and cryptography and nothing else, and this is what proves that is enough."""
    import subprocess
    import sys

    program = """
import sys

BLOCKED = ('httpx', 'fastapi', 'starlette', 'uvicorn', 'mcp', 'requests', 'aiohttp')

class _Blocker:
    def find_module(self, name, path=None):
        return self.find_spec(name, path)
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in BLOCKED:
            raise ImportError('BLOCKED BY THE TEST: server_auth reached for %r' % name)
        return None

sys.meta_path.insert(0, _Blocker())
for m in list(sys.modules):
    if m.split('.')[0] in BLOCKED:
        del sys.modules[m]

from prism.trust import ServerAuth, MissingDelegationError
a = ServerAuth('agience-server-iris', 'http://mantle.test')
assert a.verify_delegation_jwt('') is None
assert a.get_delegation_user_id() == 'anonymous'
try:
    a.require_user_headers()
except MissingDelegationError:
    pass
else:
    raise SystemExit('require_user_headers did not fail closed')
print('TRUST SURFACE OK')
"""
    import pathlib

    import prism

    cwd = pathlib.Path(prism.__file__).resolve().parents[2]
    r = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, cwd=str(cwd))
    assert "TRUST SURFACE OK" in r.stdout, (r.stderr or r.stdout)[-2500:]


def test_the_trust_extra_still_declares_only_sign_and_verify():
    """The other half of the same claim: source purity is worthless if the manifest grew the dep."""
    try:
        import tomllib
    except ModuleNotFoundError:                                   # pragma: no cover
        import tomli as tomllib                                   # type: ignore[no-redef]
    import pathlib

    import prism

    root = pathlib.Path(prism.__file__).resolve().parents[2]
    extras = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    names = " ".join(extras["trust"]).lower()
    assert "httpx" not in names and "fastapi" not in names and "requests" not in names, (
        f"the trust extra grew a network/web dependency: {extras['trust']}")


def test_issuance_did_not_move_here():
    """Verification is a contract; issuance is a service. Minting needs user records, WebAuthn and
    a database, and it stays in Origin behind `ORIGIN_URI`. This module may only ask.

    An executable statement of that boundary: nothing here writes a delegation, and the one HTTP
    call is a POST to Origin's `/internal/delegation-token`."""
    import pathlib

    import prism.trust.server_auth as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    assert "sign_delegation_jwt" not in src, (
        "server_auth signs a delegation — that is issuance, and it belongs in Origin")
    assert "/internal/delegation-token" in src, "the issuance client lost its endpoint"


def test_origin_uri_is_read_from_the_environment(monkeypatch, floor):
    monkeypatch.setenv("ORIGIN_URI", "https://origin.example/")
    assert _auth().origin_uri == "https://origin.example"


# ── the name the seven personas import ────────────────────────────────────────────────────────────
def test_the_back_compat_class_name_is_the_same_object():
    from prism.trust import AgienceServerAuth, ServerAuth

    assert AgienceServerAuth is ServerAuth


# ── enforcement: authentication is required ────────────────────────────────────────────────────
# The middleware answers `initialize` and `tools/list` itself with 401 when a request carries no
# token or an unverifiable one, rather than letting the request reach a tool and fail only when
# that tool calls `require_user_headers`. A caller sees 401 at the door, not deep inside the first
# authenticated call.

def test_no_token_is_refused_and_the_inner_app_is_never_reached(floor):
    auth = _auth(token_exchange=_never_called)
    seen, resp = asyncio.run(_drive(auth, ""))
    assert resp is not None and resp["status"] == 401
    assert seen == "", "the handler ran for an unauthenticated request"


def test_a_garbage_token_is_refused(floor):
    auth = _auth(token_exchange=_never_called)
    _, resp = asyncio.run(_drive(auth, "not-a-jwt"))
    assert resp["status"] == 401


def test_a_delegation_issued_to_ANOTHER_persona_is_refused(floor):
    """The token is real, signed by a trusted anchor, and unexpired — it is addressed to someone
    else. Accepting it would let any persona's delegation open every persona."""
    auth = _auth(token_exchange=_declines)
    other = _mantle_delegation(floor["mantle"], aud="agience-server-someone-else")
    _, resp = asyncio.run(_drive(auth, other))
    assert resp["status"] == 401


def test_a_tampered_delegation_is_refused(floor):
    auth = _auth(token_exchange=_declines)
    _, resp = asyncio.run(_drive(auth, _tamper_signature(_mantle_delegation(floor["mantle"]))))
    assert resp["status"] == 401


def test_the_refusal_carries_a_discovery_pointer_at_the_HOST_THAT_WAS_ADDRESSED(floor):
    """A bare 401 is a dead end without a discovery pointer. The pointer must name the host the
    caller used: one process answers for several personas, and they are different protected
    resources."""
    auth = _auth(token_exchange=_never_called)
    _, resp = asyncio.run(_drive(auth, "", host="sage.home.agience.ai"))
    challenge = resp["headers"]["www-authenticate"]
    assert challenge.startswith("Bearer ")
    assert 'resource_metadata="https://sage.home.agience.ai/.well-known/oauth-protected-resource"' in challenge


def test_the_refusal_names_the_persona(floor):
    """A caller talking to several personas cannot otherwise tell which one the 401 came from."""
    auth = _auth(token_exchange=_never_called)
    _, resp = asyncio.run(_drive(auth, ""))
    assert CLIENT_ID in resp["body"]


def test_a_VALID_delegation_still_passes_through(floor):
    """The control that makes the four cases above meaningful: middleware that returned 401
    unconditionally would also pass all four of them."""
    auth = _auth(token_exchange=_never_called)
    tok = _mantle_delegation(floor["mantle"])
    seen, resp = asyncio.run(_drive(auth, tok))
    assert resp is None, "a valid delegation was refused"
    assert seen == tok


def test_an_exchanged_user_token_still_passes_through(floor):
    """The gateway model must survive enforcement: a raw user token Origin exchanges is authenticated."""
    async def _exchange(origin_uri, client_id, subject_token, authorization):
        return "minted-delegation"

    auth = _auth(token_exchange=_exchange)
    seen, resp = asyncio.run(_drive(auth, _origin_user_token(floor["origin"])))
    assert resp is None and seen == "minted-delegation"


def test_CORS_PREFLIGHT_IS_EXEMPT(floor):
    """A browser sends `OPTIONS` with no `Authorization` by specification — it is asking whether it
    may send one. A 401 here would mean no browser could ever reach this persona, which would
    present as a CORS bug rather than as an auth decision."""
    auth = _auth(token_exchange=_never_called)
    seen, resp = asyncio.run(_drive(auth, "", method="OPTIONS"))
    assert resp is None, "the preflight was refused; no browser can reach this persona"
    assert seen == ""


def test_require_auth_can_be_turned_off_only_explicitly(floor):
    """No environment override — a variable that switches authentication off is the one setting
    that gets exported in a shell, forgotten, and inherited by a process nobody meant it for. It is
    a keyword at a construction site, where review can see it."""
    import os
    from prism.trust import ServerAuth

    for var in ("PRISM_REQUIRE_AUTH", "AGIENCE_REQUIRE_AUTH", "REQUIRE_AUTH"):
        os.environ[var] = "0"
    try:
        assert ServerAuth(CLIENT_ID, "http://mantle.test").require_auth is True
    finally:
        for var in ("PRISM_REQUIRE_AUTH", "AGIENCE_REQUIRE_AUTH", "REQUIRE_AUTH"):
            os.environ.pop(var, None)

    _, resp = asyncio.run(_drive(_auth(token_exchange=_never_called, require_auth=False), ""))
    assert resp is None
