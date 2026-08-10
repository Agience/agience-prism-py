"""Host — serve operators over HTTP and (optionally) register with Agience.

A Host is COMPUTE that exposes one or more operators (capabilities). It owns a
FastAPI app with a ``/health`` endpoint, optional shared-bearer auth, a resource
warmup hook, and — when given a connection token — best-effort self-registration
so the platform can discover it. Operators mount their own typed routes via
``@host.operator(...)``; the handler's annotations drive request/response
validation.

    from prism import Host

    host = Host("agience-prism", api_key=os.getenv("EMBEDDINGS_SERVER_API_KEY"))

    @host.operator("embeddings.embed", path="/embed")
    def embed(req: EmbedRequest) -> EmbedResponse: ...

    app = host.app            # uvicorn app:app
    # or: host.serve(port=8083)
"""
from __future__ import annotations

import logging
import os
import typing
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Iterable, Optional, Union

from fastapi import Depends, FastAPI, Header, HTTPException

from .. import config
from ..errors import install_error_handlers
from .auth import AuthError, TokenVerifier

log = logging.getLogger("agience.host")


def _split_env(name: str) -> tuple[str, ...]:
    """Read a comma-separated env var into a tuple of trimmed, non-empty values."""
    return tuple(p.strip() for p in (os.getenv(name, "") or "").split(",") if p.strip())

WarmupFn = Callable[[], Union[None, Awaitable[None]]]


class Host:
    """A unit of compute that serves operators and may register with the platform."""

    def __init__(
        self,
        name: str,
        *,
        api_key: Optional[str] = None,
        api_keys: Optional[Iterable[str]] = None,
        api_keys_dir: Optional[str] = None,
        authority_manifest_path: Optional[str] = None,
        authority_jwks_url: Optional[str] = None,
        hs256_secret: Optional[str] = None,
        expected_audiences: Optional[Iterable[str]] = None,
        allowed_issuers: Optional[Iterable[str]] = None,
        api_uri: Optional[str] = None,
        token: Optional[str] = None,
        warmup: Optional[WarmupFn] = None,
    ) -> None:
        self.name = name
        # --- inbound auth ---------------------------------------------------
        # Three modes, tried in order by the verifier (see auth.TokenVerifier):
        #   1. authority JWT (RS256) — keys from a mounted authority manifest
        #      and/or a JWKS URL (e.g. Origin's /.well-known/jwks.json).
        #   2. local HS256 JWT — verified against a locally-held shared secret.
        #   3. static API key(s) — a shared-bearer allowlist (ONE or MANY, so a
        #      dev install can present its own key without sharing prod's). Keys
        #      may be inline (api_key/api_keys) and/or a hot-reloaded directory
        #      of key files on a persistent volume (api_keys_dir / HOST_API_KEYS_DIR)
        #      — drop or remove a file to grant/revoke without a redeploy.
        # A host with nothing configured is open. Explicit args win over the
        # generic HOST_* env fallbacks so an embedding host can map its own env
        # names (e.g. EMBEDDINGS_SERVER_API_KEY) onto these.
        raw = api_key if api_key else os.getenv("HOST_API_KEY", "")
        if isinstance(api_keys, str):
            api_keys = [k for k in api_keys.split(",")]
        key_candidates: list[str] = list(api_keys or [])
        if raw:
            key_candidates.extend(raw.split(","))
        seen: set[str] = set()
        ordered: list[str] = []
        for key in key_candidates:
            key = (key or "").strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)
        self.api_keys: tuple[str, ...] = tuple(ordered)
        # `.api_key` is the singular form of the same setting: the first key, or
        # an empty string when none is set. `.api_keys` carries the full tuple.
        self.api_key = ordered[0] if ordered else ""

        self.verifier = TokenVerifier(
            api_keys=self.api_keys,
            api_keys_dir=api_keys_dir or os.getenv("HOST_API_KEYS_DIR"),
            authority_manifest_path=authority_manifest_path
            or os.getenv("HOST_AUTHORITY_MANIFEST")
            or config.authority_manifest_path(),
            authority_jwks_url=authority_jwks_url or os.getenv("HOST_AUTHORITY_JWKS_URL"),
            hs256_secret=hs256_secret or os.getenv("HOST_JWT_HS256_SECRET"),
            expected_audiences=tuple(expected_audiences)
            if expected_audiences is not None
            else _split_env("HOST_EXPECTED_AUDIENCES"),
            allowed_issuers=tuple(allowed_issuers)
            if allowed_issuers is not None
            else _split_env("HOST_ALLOWED_ISSUERS"),
        )
        if self.verifier.enabled:
            log.info("host %r auth: %s", name, self.verifier.describe())
        else:
            log.warning(
                "host %r is OPEN — no auth configured (add a key file to the keys "
                "dir, set an API key, or configure JWT before exposing it publicly)",
                name,
            )

        # Platform connection (optional). When both are present the host
        # self-registers on start; otherwise it just serves (standalone).
        # Registration target is the canonical MANTLE_URI (§4) — resolved with
        # no fabricated localhost default so registration stays strictly opt-in.
        self.api_uri = (api_uri or config.resolve("MANTLE_URI", default="") or "").rstrip("/")
        self.token = token or os.getenv("AGIENCE_TOKEN")
        self._warmup = warmup
        self._operators: list[str] = []

        self.app = FastAPI(title=f"agience-host:{name}", lifespan=self._lifespan)
        self.app.add_api_route("/health", self._health, methods=["GET"])
        # Any PrismError raised by an operator maps to its §10 transport status.
        install_error_handlers(self.app)

    # -- auth ---------------------------------------------------------------
    async def _auth_dep(self, authorization: Optional[str] = Header(default=None)) -> None:
        try:
            self.verifier.verify(authorization)
        except AuthError:
            raise HTTPException(status_code=401, detail="invalid or missing credentials")

    @property
    def auth_dependency(self):
        """The same credential check ``@host.operator`` applies, for hand-mounted routes.

        Auth here is a per-route dependency, not middleware — it is attached only by
        ``operator()``. A route registered straight onto ``host.app`` (``@app.post(...)``)
        is unauthenticated, and nothing in the type system or at startup says so. Use this
        property for any hand-mounted route that needs the same check::

            app.add_api_route("/thing", fn, dependencies=[Depends(host.auth_dependency)])
        """
        return self._auth_dep

    # -- operators ----------------------------------------------------------
    def operator(
        self,
        name: str,
        *,
        path: Optional[str] = None,
        methods: Iterable[str] = ("POST",),
    ) -> Callable:
        """Register a capability and mount its typed route on the host app.

        The decorated function's annotations drive validation — FastAPI infers
        the request body model and ``response_model`` from them.
        """
        route = path or f"/operators/{name}"

        def decorator(fn: Callable) -> Callable:
            try:
                response_model = typing.get_type_hints(fn).get("return")
            except Exception:  # unresolved forward ref — let FastAPI infer later
                response_model = None
            self.app.add_api_route(
                route,
                fn,
                methods=list(methods),
                response_model=response_model,
                dependencies=[Depends(self._auth_dep)],
                name=name,
            )
            self._operators.append(name)
            log.info("operator %r mounted at %s", name, route)
            return fn

        return decorator

    # -- lifecycle ----------------------------------------------------------
    def _health(self) -> dict:
        return {"status": "ok", "host": self.name, "operators": self._operators}

    @asynccontextmanager
    async def _lifespan(self, app: FastAPI):
        if self._warmup is not None:
            result = self._warmup()
            if hasattr(result, "__await__"):
                await result  # type: ignore[func-returns-value]
        await self._register()
        yield

    async def _register(self) -> None:
        """Best-effort: announce this host + its operators to the platform.

        No token -> standalone mode: the host just serves, and an operator like
        embeddings is wired by pointing the platform's ``EMBEDDINGS_URI`` at it.
        Registration never blocks serving.
        """
        if not (self.api_uri and self.token):
            return
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.api_uri}/hosts/register",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"name": self.name, "operators": self._operators},
                )
            log.info("self-register -> %s (%s)", self.api_uri, resp.status_code)
        except Exception as exc:
            log.warning("self-register failed (non-fatal): %s", exc)

    # -- run ----------------------------------------------------------------
    def serve(self, host: str = "0.0.0.0", port: int = 8083) -> None:
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, timeout_graceful_shutdown=10)
