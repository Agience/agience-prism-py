"""Typed, stable error set for the Agience Prism (Prism Protocol §10).

Every failure a server surfaces is one of these — names idiomatic to Python,
meanings fixed by the spec. Each carries the transport status §10 mandates
(auth → 401, entitlement → 403, not-found → 404, host down → 502/503) so a
host app can map an exception to an HTTP response uniformly.

    from prism import AuthError, EntitlementError, install_error_handlers

    install_error_handlers(host.app)      # any PrismError → its §10 status
    raise EntitlementError("missing grant tool:vnd.agience.search+json:run")

The base :class:`PrismError` lets callers catch the whole family; subclasses
carry ``http_status`` (transport mapping) and ``code`` (stable machine slug).
"""
from __future__ import annotations

from typing import Any


class PrismError(Exception):
    """Base for the typed prism error set (§10). Catch this for the family."""

    #: HTTP status this error maps to at the transport boundary (§10).
    http_status: int = 500
    #: Stable machine-readable slug, surfaced in the error body.
    code: str = "prism_error"

    def to_body(self) -> dict[str, Any]:
        """Structured error body: ``{"error": <code>, "detail": <message>}``."""
        return {"error": self.code, "detail": str(self)}


class AuthError(PrismError):
    """Missing / invalid / expired token, or unrooted delegation (§5.1)."""

    http_status = 401
    code = "auth_error"


class EntitlementError(PrismError):
    """Authenticated, but the caller lacks the required scope / grant (§8)."""

    http_status = 403
    code = "entitlement_error"


class CapabilityNotFound(PrismError):
    """No host advertises the requested capability (§10)."""

    http_status = 404
    code = "capability_not_found"


class HostUnavailable(PrismError):
    """The backing host is unreachable or still starting up (§10)."""

    http_status = 503  # 502 is also acceptable per §10 ("host down → 502/503")
    code = "host_unavailable"


class ProtocolError(PrismError):
    """Malformed request/response or protocol-version mismatch (§10, §11)."""

    http_status = 400
    code = "protocol_error"


def http_status_for(exc: BaseException) -> int:
    """Transport status for an exception: a :class:`PrismError`'s mapped status,
    else 500."""
    return getattr(exc, "http_status", 500)


def install_error_handlers(app: Any) -> None:
    """Register a FastAPI/Starlette handler so any :class:`PrismError` becomes
    a JSON response with its §10 status. Idempotent and safe to call once per app.

    ``fastapi`` is imported lazily so importing this module stays dependency-free
    for client-only users.
    """
    from fastapi import Request  # noqa: F401 — signature clarity
    from fastapi.responses import JSONResponse

    async def _handle(_request: Any, exc: PrismError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_body())

    app.add_exception_handler(PrismError, _handle)


__all__ = [
    "PrismError",
    "AuthError",
    "EntitlementError",
    "CapabilityNotFound",
    "HostUnavailable",
    "ProtocolError",
    "http_status_for",
    "install_error_handlers",
]
