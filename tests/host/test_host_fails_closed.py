"""A Host with no credential refuses its operator routes, and binds loopback by default.

Driven through the FastAPI app the Host builds, so the dependency `@host.operator` attaches is what
answers — not the verifier called on its own.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from prism.host.host import Host

_ENV = ("HOST_API_KEY", "HOST_API_KEYS_DIR", "HOST_AUTHORITY_MANIFEST", "HOST_AUTHORITY_JWKS_URL",
        "HOST_JWT_HS256_SECRET", "HOST_EXPECTED_AUDIENCES", "HOST_ALLOWED_ISSUERS", "KEYS_DIR",
        "AGIENCE_TOKEN", "EMBER_URI")


@pytest.fixture(autouse=True)
def _no_host_env(monkeypatch):
    for name in _ENV:
        monkeypatch.delenv(name, raising=False)


def _host(**kw) -> Host:
    host = Host("probe", **kw)

    @host.operator("probe.echo", path="/echo")
    def echo(body: dict) -> dict:
        return body

    return host


def test_an_unconfigured_host_refuses_its_operators():
    client = TestClient(_host().app)
    assert client.post("/echo", json={"a": 1}).status_code == 401
    assert client.post("/echo", json={"a": 1}, headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/health").status_code == 200, "health is not an operator route"


def test_allow_open_is_the_only_way_to_serve_unauthenticated():
    client = TestClient(_host(allow_open=True).app)
    r = client.post("/echo", json={"a": 1})
    assert r.status_code == 200 and r.json() == {"a": 1}


def test_a_configured_key_is_enforced():
    client = TestClient(_host(api_key="k").app)
    assert client.post("/echo", json={}, headers={"Authorization": "Bearer k"}).status_code == 200
    assert client.post("/echo", json={}).status_code == 401


def test_there_is_no_environment_switch_for_open(monkeypatch):
    for name in ("HOST_ALLOW_OPEN", "PRISM_ALLOW_OPEN", "HOST_OPEN"):
        monkeypatch.setenv(name, "1")
    assert TestClient(_host().app).post("/echo", json={}).status_code == 401


def test_serve_binds_loopback_by_default():
    assert inspect.signature(Host.serve).parameters["host"].default == "127.0.0.1"
