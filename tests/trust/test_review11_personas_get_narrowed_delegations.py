"""Review 11, H3 and M2: a persona never receives or forwards a caller's full person token, and
every peer honours Origin's sign-in bounds.

* A persona takes a caller only as Origin's narrowed delegation for that persona (`aud` = `act.sub`
  = its narrow name, e.g. `iris`; scope `persona:iris`), which it exchanges at Origin for its own
  server delegation. A person's full access token is refused, never exchanged and never kept to be
  passed on.
* `prism.trust.not_before` keeps Origin's published sign-in bounds; a token issued before its
  person's bound, or everyone's, is refused by the persona middleware.
"""
from __future__ import annotations

import time

import asyncio

import pytest

from .test_server_auth import (  # noqa: F401 — the oracle's helpers; `floor` comes from conftest
    CLIENT_ID, ISSUER_URL, _auth, _now, _origin_delegation, _origin_user_token, _run_middleware)

NARROW = "iris"


def _narrowed(svc, *, aud=NARROW, actor=NARROW, scope=f"persona:{NARROW}", sub="user-1",
              iat=None):
    return svc.sign({
        "iss": ISSUER_URL, "sub": sub, "aud": aud, "act": {"sub": actor},
        "principal_type": "delegation", "scope": scope, "iat": iat or _now(),
        "exp": _now() + 300})


def test_a_full_person_token_is_refused_and_never_exchanged(floor):
    calls = []

    async def _exchange(*a):
        calls.append(a)
        return "minted"

    auth = _auth(token_exchange=_exchange)
    user = _origin_user_token(floor["origin"])
    assert asyncio.run(_run_middleware(auth, user)) == ""
    assert calls == [], "a person's full token reached Origin's exchange from a persona"


def test_the_persona_s_narrowed_delegation_is_exchanged_for_its_own(floor):
    calls = []

    async def _exchange(origin_uri, client_id, subject_token, authorization):
        calls.append((client_id, subject_token))
        return "server-delegation"

    auth = _auth(token_exchange=_exchange)
    narrowed = _narrowed(floor["origin"])
    assert asyncio.run(_run_middleware(auth, narrowed)) == "server-delegation"
    assert calls == [(CLIENT_ID, narrowed)]
    assert auth.request_caller_token.get("") == ""


@pytest.mark.parametrize("kw", [
    {"aud": "lumen", "actor": "lumen", "scope": "persona:lumen"},     # another persona's
    {"scope": "persona:lumen"},                                       # scope for another
    {"scope": "persona:iris platform:admin"},                         # never platform:admin
    {"actor": "ember"},                                               # audience is not its actor
])
def test_a_narrowed_delegation_for_anything_else_is_refused(floor, kw):
    async def _exchange(*a):
        raise AssertionError("exchanged a delegation that is not this persona's")

    auth = _auth(token_exchange=_exchange)
    assert asyncio.run(_run_middleware(auth, _narrowed(floor["origin"], **kw))) == ""


def test_nothing_the_caller_sent_is_kept_to_pass_on(floor):
    """The caller's token is never kept for another persona: only a grant key passes on."""
    async def _exchange(*a):
        return "server-delegation"

    auth = _auth(token_exchange=_exchange)
    seen = {}

    async def _inner(scope, receive, send):
        seen["caller"] = auth.request_caller_token.get("")

    app = auth.make_middleware_class()(_inner)
    tok = _narrowed(floor["origin"])
    asyncio.run(app({"type": "http", "method": "POST",
                     "headers": [(b"authorization", f"Bearer {tok}".encode())]}, None,
                    lambda m: asyncio.sleep(0)))
    assert seen.get("caller", "") == ""


# -- not-before -----------------------------------------------------------------------------------

def test_a_bound_is_kept_and_ends_older_tokens():
    from prism.trust.not_before import NotBefore

    nb = NotBefore("http://origin.test", fetch=lambda url: "t",
                   verify=lambda t: {"iat": time.time(), "entries": [{"sub": "u1", "not_before": 50}],
                                     "all_before": None})
    changed = []
    nb.on_change(changed.append)
    assert nb.poll_once() == ["u1"] and changed == ["u1"]
    assert nb.refused({"sub": "u1", "iat": 49}) and not nb.refused({"sub": "u1", "iat": 51})
    assert not nb.refused({"sub": "u2", "iat": 1})
    nb.apply({"all_before": 60})
    assert nb.refused({"sub": "u2", "iat": 59})


def test_an_unverified_answer_changes_nothing():
    from prism.trust.not_before import NotBefore

    def bad(_t):
        raise ValueError("signature")
    nb = NotBefore("http://origin.test", fetch=lambda url: "t", verify=bad, state_path="")
    # It learns no bound, and is no good poll: the poller still fails closed (review 12, M8).
    assert nb.poll_once() == [] and nb._by_sub == {} and nb.refused({"sub": "u1", "iat": 1})


def test_the_persona_refuses_a_token_from_before_the_person_s_bound(floor, monkeypatch):
    from prism.trust import not_before

    async def _exchange(*a):
        return "server-delegation"

    nb = not_before.NotBefore("http://origin.test")
    nb.apply({"entries": [{"sub": "user-1", "not_before": _now() + 10}]})
    monkeypatch.setattr(not_before, "_shared", nb)
    auth = _auth(token_exchange=_exchange)
    assert asyncio.run(_run_middleware(auth, _narrowed(floor["origin"]))) == ""
    assert asyncio.run(_run_middleware(auth, _origin_delegation(floor["origin"]))) == ""
