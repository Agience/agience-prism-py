"""A host whose self-registration is refused says so; one that succeeds stays quiet.

A host that cannot register still serves, so the log line is the only place the difference shows.
Logged at one level, `self-register -> <uri> (404)` reads exactly like
`self-register -> <uri> (200)` to anyone scanning, and a host runs indefinitely with its operators
unannounced and nothing saying so.

What is pinned here: a refusal is logged at `warning` and names the consequence; a success is
`info`; a transport failure is `warning` and non-fatal; and the base that is posted to comes from
`EMBER_URI`, which is the leaf that serves `/hosts/register`.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import types

from prism.host import Host


class _Resp:
    def __init__(self, status): self.status_code = status


def _fake_httpx(status, seen):
    class _Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, **kw):
            seen.append(url)
            return _Resp(status)
    mod = types.ModuleType("httpx")
    mod.AsyncClient = _Client
    return mod


def _run(status, caplog, monkeypatch):
    seen: list[str] = []
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(status, seen))
    host = Host("probe", api_uri="https://mantle.example.invalid", token="t")
    with caplog.at_level(logging.INFO):
        caplog.clear()                    # drop the constructor's own "host is OPEN" warning
        asyncio.run(host._register())
    return seen, " ".join(r.getMessage() for r in caplog.records), caplog.records


def test_a_404_is_a_warning_that_says_the_operators_are_not_announced(caplog, monkeypatch):
    seen, msg, records = _run(404, caplog, monkeypatch)
    assert seen == ["https://mantle.example.invalid/hosts/register"], seen
    assert any(r.levelno >= logging.WARNING for r in records), (
        "a refused registration was not logged above INFO: %s" % msg)
    assert "REFUSED" in msg and "404" in msg, msg
    # The consequence, not just the status. An operator reading "404" has to know what the call
    # was FOR; the reason this went unnoticed for months is that nobody did.
    assert "NOT announced" in msg, msg


def test_a_success_stays_at_info_and_says_nothing_alarming(caplog, monkeypatch):
    """The inverted guard. Warning on every start would be noise, and noise gets filtered — at
    which point the real refusal is invisible again, which is where this started."""
    _seen, msg, records = _run(200, caplog, monkeypatch)
    assert not [r for r in records if r.levelno >= logging.WARNING], msg
    assert "self-register" in msg and "REFUSED" not in msg, msg


def test_registration_stays_strictly_opt_in(caplog, monkeypatch):
    """No token means no call at all — the change must not make a standalone host chatty."""
    seen: list[str] = []
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(404, seen))
    host = Host("probe", api_uri="https://mantle.example.invalid", token=None)
    host.token = None                     # AGIENCE_TOKEN may be set in the environment
    with caplog.at_level(logging.INFO):
        caplog.clear()
        asyncio.run(host._register())
    assert seen == [] and not caplog.records, (seen, caplog.records)


def test_a_transport_failure_is_still_non_fatal(caplog, monkeypatch):
    """Registration never blocks serving — that contract is unchanged."""
    mod = types.ModuleType("httpx")

    class _Client:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): raise OSError("no route to host")
    mod.AsyncClient = _Client
    monkeypatch.setitem(sys.modules, "httpx", mod)
    host = Host("probe", api_uri="https://mantle.example.invalid", token="t")
    with caplog.at_level(logging.INFO):
        caplog.clear()
        asyncio.run(host._register())     # must not raise
    assert "non-fatal" in " ".join(r.getMessage() for r in caplog.records)


# ── where the registration is addressed ─────────────────────────────────────────────────────────

def test_the_leaf_is_resolved_from_ember_uri_not_mantle_uri(caplog, monkeypatch):
    """Registration resolves `EMBER_URI`: the leaf serves `/hosts/register`, and the store the
    registration writes to and the token gate that protects it are both there.

    Pins the source of the base and not just the path. A host pointed at a base that serves no
    `/hosts` route posts a well-formed request into a 404 — the path is right and the address is
    wrong, which is the failure a path-only assertion cannot see. Both variables are set here, so
    reading the wrong one produces a wrong answer rather than an empty one."""
    seen: list[str] = []
    monkeypatch.setenv("EMBER_URI", "http://leaf.invalid:8091")
    monkeypatch.setenv("MANTLE_URI", "https://mantle.invalid")
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(200, seen))
    host = Host("probe", token="t")
    asyncio.run(host._register())
    assert seen == ["http://leaf.invalid:8091/hosts/register"], seen


def test_an_explicit_api_uri_still_wins(caplog, monkeypatch):
    """The constructor argument is unchanged and still overrides the environment — a deployment
    that already passes its own target must not be re-pointed by this change."""
    seen: list[str] = []
    monkeypatch.setenv("EMBER_URI", "http://leaf.invalid:8091")
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(200, seen))
    host = Host("probe", api_uri="http://explicit.invalid", token="t")
    asyncio.run(host._register())
    assert seen == ["http://explicit.invalid/hosts/register"], seen


def test_no_leaf_configured_never_fabricates_localhost(caplog, monkeypatch):
    """The opt-in guarantee, and the one the new default could have broken. `EMBER_URI` carries
    a `http://localhost:8091` default in the config table for ordinary callers. Registration must
    not take it: a host that names no leaf would otherwise start posting a bearer token at whatever
    is listening on that port."""
    seen: list[str] = []
    monkeypatch.delenv("EMBER_URI", raising=False)
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(200, seen))
    host = Host("probe", token="t")
    assert host.api_uri == "", host.api_uri
    with caplog.at_level(logging.INFO):
        caplog.clear()
        asyncio.run(host._register())
    assert seen == [], seen
    # ...but it must not be SILENT about it: a token was supplied, so registration was intended.
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "EMBER_URI" in msg and "NOT announced" in msg, msg


def test_a_standalone_host_says_nothing(caplog, monkeypatch):
    """Neither half set is the standalone case, and it is not a misconfiguration. Warning here
    would fire for every host that never intended to register."""
    seen: list[str] = []
    monkeypatch.delenv("EMBER_URI", raising=False)
    monkeypatch.setitem(sys.modules, "httpx", _fake_httpx(200, seen))
    host = Host("probe")
    host.token = None
    with caplog.at_level(logging.INFO):
        caplog.clear()
        asyncio.run(host._register())
    assert seen == [] and not caplog.records, (seen, [r.getMessage() for r in caplog.records])
