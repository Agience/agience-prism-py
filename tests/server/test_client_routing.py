"""AgienceClient plane routing: artifact OPERATIONS dispatch through Crystal (the
content-type gateway); raw CRUD + search stay on Mantle. Mirrors facet + the JS
server so every caller agrees on which plane owns a path.
Pure unit tests — httpx.AsyncClient is monkeypatched, no network."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from prism import Server
from prism.server.client import AgienceClient

MANTLE = "http://mantle.test:8081"
CRYSTAL = "http://crystal.test:8085"


class _Resp:
    content = b""
    status_code = 200

    def raise_for_status(self):  # noqa: D401 - test stub
        return None

    def json(self):
        return None


@asynccontextmanager
async def _fake_async_client(urls):
    class _C:
        async def get(self, url, **_kw):
            urls.append(url)
            return _Resp()

        async def post(self, url, **_kw):
            urls.append(url)
            return _Resp()

    yield _C()


@pytest.fixture()
def urls(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        "prism.server.client.httpx.AsyncClient",
        lambda *a, **k: _fake_async_client(seen),
    )
    return seen


def _client():
    return AgienceClient(Server("t", MANTLE, crystal_uri=CRYSTAL, api_key="agc_test"))


def test_crystal_uri_defaults_from_env():
    b = Server("t", MANTLE)
    assert b.crystal_uri == "http://localhost:8085"
    assert b.api_uri == MANTLE


def test_ops_route_to_crystal(urls):
    """Every method that reaches Crystal, and the full URL each one builds."""
    c = _client()
    asyncio.run(c.invoke("art-1", "do_thing", {"x": 1}))
    asyncio.run(c.create("vnd.agience.note+json", container_id="w1"))
    asyncio.run(c.resolve("vnd.agience.note+json"))
    assert urls == [
        f"{CRYSTAL}/artifacts/art-1/op/invoke",
        f"{CRYSTAL}/create",
        f"{CRYSTAL}/resolve/vnd.agience.note+json",
    ]


def test_crud_and_search_stay_on_mantle(urls):
    """Which base is chosen, and the full URL that is built on it.

    The base and the path fail differently: routing to the right plane and posting to a path the
    server does not serve produces a well-formed request and a 404, and a test that asserted only
    the base would report that as correct. Both are pinned. Whether the server declares the route
    is the server's own check to run — prism has no way to see it.
    """
    c = _client()
    asyncio.run(c.get_artifact("art-1"))
    asyncio.run(c.search_query(query_text="hello"))
    assert urls == [f"{MANTLE}/artifacts/art-1", f"{MANTLE}/artifacts/recall"]
