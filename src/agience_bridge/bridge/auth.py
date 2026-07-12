"""Agience Bridge — delegation auth for MCP servers integrating with Agience.

The :class:`Bridge` captures the inbound delegation token a request carries (the
token Agience issued FOR this server) and forwards it on outbound calls, so
Agience authorizes as the **end user** — the server never holds standing user
credentials. For server-to-server calls with no user context, an optional API
key is used instead.

No `agience-core` dependency (Beacon and third-party closed servers can use this
freely — see the repo's Apache-2.0 license vs core's AGPL). Tokens are decoded
UNVERIFIED only to surface a user id for logging; **Agience is the verifier**.
"""

from __future__ import annotations

import base64
import contextvars
import json
import logging
from typing import Any, Optional

log = logging.getLogger("agience_bridge")


class Bridge:
    """Per-server integration handle: inbound token capture + outbound auth.

    Parameters
    ----------
    server_name: the server's identifier (e.g. ``"agience-server-beacon"``).
    api_uri:     base URI of the Agience core backend.
    api_key:     optional API key for calls made without a user delegation context.
    """

    def __init__(self, server_name: str, api_uri: str, *, api_key: Optional[str] = None) -> None:
        self.server_name = server_name
        self.api_uri = api_uri.rstrip("/")
        self._api_key = api_key
        # Per-instance ContextVar so multiple Bridges can coexist in one process.
        self._token: contextvars.ContextVar[str] = contextvars.ContextVar(
            f"agience_bridge_token_{server_name}", default=""
        )

    # ------------------------------------------------------------------
    # Inbound: capture the delegation token for the duration of a request
    # ------------------------------------------------------------------
    def middleware(self, app: Any) -> Any:
        """Wrap an ASGI app so the inbound bearer token is captured per request."""
        return _CaptureTokenMiddleware(app, self._token)

    def create_app(self, mcp: Any) -> Any:
        """Wrap a FastMCP streamable-http app with the capture middleware."""
        return self.middleware(mcp.streamable_http_app())

    # ------------------------------------------------------------------
    # Outbound: present the right credential to Agience
    # ------------------------------------------------------------------
    def user_headers(self) -> dict[str, str]:
        """Headers for a call to Agience: forward the captured user delegation
        token if present, else fall back to the configured API key."""
        headers = {"Content-Type": "application/json"}
        token = self._token.get("")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def get_user_id(self) -> str:
        """Best-effort user id from the captured token (UNVERIFIED — display only)."""
        token = self._token.get("")
        if not token:
            return "anonymous"
        try:
            parts = token.split(".")
            if len(parts) >= 2:
                payload = parts[1] + "=" * (-len(parts[1]) % 4)
                claims = json.loads(base64.urlsafe_b64decode(payload))
                return str(claims.get("sub", "anonymous"))
        except Exception:  # noqa: BLE001 — never let a malformed token break a tool
            pass
        return "anonymous"

    def client(self, *, timeout: float = 60.0) -> "Any":
        """Return an :class:`agience_bridge.client.AgienceClient` bound to this Bridge."""
        from .client import AgienceClient

        return AgienceClient(self, timeout=timeout)


class _CaptureTokenMiddleware:
    """ASGI middleware: store the inbound bearer token in the Bridge's ContextVar
    for the duration of the request. Non-HTTP scopes pass straight through."""

    def __init__(self, app: Any, token_var: contextvars.ContextVar) -> None:
        self._app = app
        self._token = token_var

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        hdrs = dict(scope.get("headers", []))
        raw = hdrs.get(b"authorization", b"").decode()
        token = raw[7:].strip() if raw.lower().startswith("bearer ") else ""
        reset = self._token.set(token)
        try:
            await self._app(scope, receive, send)
        finally:
            self._token.reset(reset)
