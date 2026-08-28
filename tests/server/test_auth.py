"""Server auth: delegation-token forwarding + user-id decode + API-key fallback.
Pure unit tests — no network, no mcp/httpx needed."""

import base64
import json

from prism import Server


def _jwt(sub: str) -> str:
    """A structurally-valid (unsigned) JWT carrying ``sub`` — for decode tests only."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_forwards_captured_delegation_token_and_decodes_user():
    b = Server("agience-server-test", "http://core:8081")
    token = _jwt("user-123")
    reset = b._token.set(token)
    try:
        assert b.user_headers()["Authorization"] == f"Bearer {token}"
        assert b.get_user_id() == "user-123"
    finally:
        b._token.reset(reset)


def test_falls_back_to_api_key_without_delegation():
    b = Server("agience-server-test", "http://core:8081", api_key="agc_test")
    assert b.user_headers()["Authorization"] == "Bearer agc_test"
    assert b.get_user_id() == "anonymous"  # no delegation token → no user


def test_no_auth_header_when_no_token_or_key():
    b = Server("agience-server-test", "http://core:8081")
    assert "Authorization" not in b.user_headers()


def test_api_uri_is_normalized():
    assert Server("s", "http://core:8081/").api_uri == "http://core:8081"
