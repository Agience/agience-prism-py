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
    c = _client()
    asyncio.run(c.invoke("art-1", "do_thing", {"x": 1}))
    asyncio.run(c.create("vnd.agience.note+json", container_id="w1"))
    asyncio.run(c.resolve("vnd.agience.note+json"))
    asyncio.run(c.embed({"text": "hi"}))
    assert urls == [
        f"{CRYSTAL}/artifacts/art-1/op/invoke",
        f"{CRYSTAL}/create",
        f"{CRYSTAL}/resolve/vnd.agience.note+json",
        f"{CRYSTAL}/embed",
    ]


def test_crud_and_search_stay_on_mantle(urls):
    """This pins which base is chosen, and that is all it ever pinned.

    It passed while `search_query` posted to `/search/query` — a path mantle does not serve and
    never has. The routing was right and the target was dead, and a test named for "search" gave
    no sign. The URL is now the real one; `test_the_search_target_is_a_route_mantle_serves`
    below checks the half this one cannot see."""
    c = _client()
    asyncio.run(c.get_artifact("art-1"))
    asyncio.run(c.search_query(query_text="hello"))
    assert urls == [f"{MANTLE}/artifacts/art-1", f"{MANTLE}/artifacts/recall"]


def test_the_search_target_is_a_route_mantle_serves():
    """The half the routing test cannot reach: does the path EXIST?

    Checked against mantle's live route table when it is checked out beside prism — not
    against a remembered list, which is how `/search/query` survived. Skipped when it is not,
    so this SDK stays testable alone."""
    import pathlib
    import re

    ws = pathlib.Path(__file__).resolve().parents[4]
    mantle_src = ws / "agience-mantle" / "src"
    if not mantle_src.is_dir():
        import pytest
        pytest.skip("agience-mantle not checked out beside prism")

    src = (mantle_src / "mantle" / "routers" / "artifacts_router.py").read_text(
        encoding="utf-8")
    served = set(re.findall(r'@router\.\w+\(\s*"([^"]+)"', src))
    assert "/recall" in served, (
        "the artifacts router no longer declares /recall; this SDK targets /artifacts/recall")
