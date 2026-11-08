"""Review 23, L1: what a persona sends Mantle for a describe is its own copy, never the delegation
Crystal sent it, which Mantle could hand back to the persona.

The middleware exchanges an inbound describe delegation at Origin
(`/internal/describe-delegation/for-mantle`, signed with the persona's own key) and keeps only the
copy, addressed to Mantle and asked for by the persona, which no persona takes inbound. With no
copy, the request is unauthenticated. The token's verification is stubbed here; its exchange is
the injected seam.
"""
from __future__ import annotations

import asyncio

from prism.trust.server_auth import ServerAuth

DESCRIBE = {"principal_type": "delegation", "sub": "sys-1", "aud": "agience-server-iris",
            "act": {"sub": "agience-server-iris"}, "scope": "platform.describe", "iat": 0}


def _run(auth, monkeypatch):
    from prism.trust import not_before
    monkeypatch.setattr(auth, "verify_origin_delegation", lambda tok: dict(DESCRIBE))
    monkeypatch.setattr(auth, "sign_exchange_jwt", lambda: "iris-signed")
    monkeypatch.setattr(not_before, "refused", lambda claims: False)
    seen = {}

    async def app(scope, receive, send):
        seen["stored"] = auth.request_user_token.get()

    async def send(message):
        seen.setdefault("sent", []).append(message)

    mw = auth.make_middleware_class()(app)
    asyncio.run(mw({"type": "http", "method": "POST", "path": "/mcp",
                    "headers": [(b"authorization", b"Bearer the-describe-delegation")]},
                   None, send))
    return seen


def test_the_persona_keeps_its_own_copy_for_mantle(monkeypatch):
    asked = []

    async def exchange(origin_uri, subject, authorization):
        asked.append(subject)
        assert authorization == "Bearer iris-signed"
        return "the-persona-s-copy"

    auth = ServerAuth("agience-server-iris", "http://mantle.test", describe_exchange=exchange)
    assert _run(auth, monkeypatch)["stored"] == "the-persona-s-copy"
    assert asked == ["the-describe-delegation"]


def test_no_copy_no_request(monkeypatch):
    async def exchange(*_a):
        return None

    auth = ServerAuth("agience-server-iris", "http://mantle.test", describe_exchange=exchange)
    seen = _run(auth, monkeypatch)
    assert "stored" not in seen and seen["sent"][0]["status"] == 401
