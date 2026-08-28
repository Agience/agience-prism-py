"""A host whose self-registration is REFUSED says so; one that succeeds stays quiet.

THE DEFECT. `Host._register` logged every reply at `info` — `self-register -> <uri> (404)`
reads exactly like `self-register -> <uri> (200)` in a log anyone is scanning. Measured
2026-08-26, the 404 is the live case: every deployment resolves `MANTLE_URI` to a mantle node and
mantle serves **no** `/hosts` route (0 of 66 mounted), so every prism host has posted into a 404 on
every start since the SDK shipped, with its operators never announced.

This does not settle WHERE registration belongs — `ember/surface/serve.py` serves
`/hosts/register` on the local leaf, and that split is an open routing question. It settles that
whichever base is configured, a refusal from it is audible.
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


# ── where the registration is addressed (changed 2026-08-26) ────────────────────────────────────

def test_the_leaf_is_resolved_from_ember_uri_not_mantle_uri(caplog, monkeypatch):
    """The routing fix. Registration used to resolve `MANTLE_URI`, and mantle serves no `/hosts`
    route (0 of 66, measured 2026-08-26) — the receiver is on the ember leaf. Pinning the source of
    the base, not just the path, because the path was never the part that was wrong."""
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
