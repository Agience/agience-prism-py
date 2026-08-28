"""Persona / MCP-server auth — the host adapter that sits on the trust floor.

**Verification is a contract; issuance is a service.** That line decides what is in this file.

    *Verifying* a token is a pure function over the token bytes plus a key from the authority
    manifest, which is a file on disk (`authority_trust` reads the inline JWKS rather than fetching
    it over HTTP). It is stateless, it is the same in every deployment, and every consumer of the
    platform needs it — so it is a contract, and contracts live in prism.

    *Minting* a token needs user records, WebAuthn, a database and key custody. It is stateful and
    per-deployment. It lives in Origin, and is reached over the wire at `ORIGIN_URI`.

The one HTTP call in here follows from that: `_mint_delegation_for_user` is a *client of* issuance.
Origin verifies the subject token, derives the subject itself, and holds the signing key; this side
only asks.

## Why there is no `httpx` import

`prism`'s base install is `dependencies = []`, guarded by `tests/test_contract_install_is_pure.py`,
and each extra names only what its own modules import. The `trust` extra is `python-jose` +
`cryptography` — sign and verify. Keeping `httpx` out of it keeps the trust floor at *sign/verify*
rather than widening it to *network* for every consumer.

Verification needs no HTTP here — the JWKS is inline in the on-disk authority manifest — so the only
HTTP is the issuance client, and it is an injected seam, the pattern `prism.reach` uses for
`keyring=` / `lightcone=`: pass `token_exchange=` and this module never touches a socket. The
default is `urllib.request` on a worker thread, which is stdlib, so an install that asked only for
`[trust]` gets the full behaviour.

## The trust model this implements

Each persona running inside the Chorus container shares one service identity (`chorus.private.pem`,
written by the init container into `KEYS_DIR`). The persona's `client_id` distinguishes who is
calling — it lands in the `sub`/`client_id` claims of every outbound JWT, while `iss` reads
`chorus`. Inbound delegation JWTs (Mantle → Chorus, RFC 8693) and inbound user JWTs
(Origin → Chorus) verify against the relevant service's inline JWKS in the authority manifest —
signature and claims only, with no shared secret, no token exchange and no JWKS fetch on the
verification path.

Identity binding here is at the claim level: `aud` binds intent. Transport-level binding
(mTLS / DPoP) sits outside this adapter.

Usage
-----
Create one :class:`ServerAuth` at module level per persona::

    from prism.trust import ServerAuth
    auth = ServerAuth(SERVER_CLIENT_ID, MANTLE_URI)

Then expose the standard server interface::

    def create_server_app():
        return auth.create_app(mcp)

    async def server_startup():
        await auth.startup()

Multiple instances are safe in a single process (the unified ``chorus`` host) — each owns its own
ContextVar (disambiguated by ``client_id``) and self-identifies via its ``client_id``.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Optional

from jose import jwt as jose_jwt, JWTError

from . import service_identity
from .authority_trust import (
    verify_delegation_jwt as _verify_delegation_jwt,
    verify_jwt as _verify_jwt,
)

log = logging.getLogger(__name__)

#: The injected issuance-client seam. Given the Origin base URI, this persona's client id, the
#: caller's raw user token and the Authorization header value to present, return the delegation
#: token Origin minted — or ``None`` if it declined. Async, because the call is I/O.
TokenExchange = Callable[[str, str, str, str], Awaitable[Optional[str]]]


class MissingDelegationError(PermissionError):
    """Raised when a tool needs the caller's identity and no delegation is active.

    Tools that authorize on a caller-supplied ``workspace_id`` / ``artifact_id``
    MUST fail closed rather than fall back to the persona's platform JWT — the
    service identity carries platform authority over every tenant.
    """


async def _stdlib_token_exchange(
    origin_uri: str, server_client_id: str, subject_token: str, authorization: str
) -> Optional[str]:
    """The default issuance client: `POST {origin_uri}/internal/delegation-token`.

    Stdlib only — `httpx` is not in prism's `trust` extra and must not be added to it, see the
    module docstring. `urllib.request` blocks, so it runs on a worker thread with an 8-second
    timeout; `urlopen` raises on a non-2xx response, and `HTTPError` is a subclass of `OSError`, so
    the caller's exception handling covers it too.
    """

    def _post() -> Optional[str]:
        body = json.dumps(
            {"server_client_id": server_client_id, "subject_token": subject_token}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{origin_uri}/internal/delegation-token",
            data=body,
            headers={"Authorization": authorization, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:      # raises on 4xx/5xx
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("token") if isinstance(payload, dict) else None

    return await asyncio.to_thread(_post)


#: RFC 9728. The crystal host serves this per Host header, so the pointer below resolves to the
#: metadata for whichever persona hostname the caller actually used.
_PROTECTED_RESOURCE_PATH = "/.well-known/oauth-protected-resource"


async def _send_unauthenticated(scope: Any, send: Any, client_id: str) -> None:
    """401 with a discovery pointer, so the caller can tell which authorization server to use.

    RFC 9728 / the MCP authorization spec: the challenge names the document that tells a client
    which authorization server to use. The host publishes that document per hostname, so this
    points at the host the caller addressed rather than at a configured constant — one process
    answers for several personas, and they are different protected resources.
    """
    host = ""
    scheme = "https"
    for k, v in scope.get("headers") or []:
        lk = k.lower()
        if lk == b"host":
            host = v.decode("latin-1", errors="ignore")
        elif lk == b"x-forwarded-proto":
            scheme = v.decode("latin-1", errors="ignore").split(",")[0].strip() or "https"
    if not host:
        host = scope.get("server", ("", 0))[0] or ""
        scheme = scope.get("scheme", "http")

    challenge = f'Bearer resource_metadata="{scheme}://{host}{_PROTECTED_RESOURCE_PATH}"'
    body = json.dumps({
        "error": "unauthorized",
        # Names the persona: a caller talking to several cannot otherwise tell which one refused —
        # the same reason `MissingDelegationError` carries the client_id.
        "error_description": (
            f"{client_id}: this endpoint requires an authenticated caller. Obtain a token from the "
            f"authorization server named in {_PROTECTED_RESOURCE_PATH} and send it as a Bearer token."
        ),
    }).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"www-authenticate", challenge.encode()),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class ServerAuth:
    """Per-persona authentication and delegation context.

    Holds a per-request ContextVar for the inbound delegation JWT, exposes
    helpers for signing outbound platform JWTs (via the chorus service identity),
    and provides ASGI middleware that verifies inbound delegation JWTs against
    the platform authority manifest.

    Parameters
    ----------
    client_id:
        The persona's ``agience-server-<name>`` identifier, used as the
        expected ``aud`` claim on inbound delegation JWTs and as ``client_id`` on
        outbound platform JWTs signed by this persona.
    agience_api_uri:
        Base URI of the Mantle backend (kept for tools that need to make REST
        calls to Mantle).
    token_exchange:
        The issuance client (keyword-only). Defaults to the stdlib POST above.
        Injecting one keeps this module off the network entirely — which is what
        the tests do, and what a host with its own HTTP stack should do.
    """

    def __init__(
        self,
        client_id: str,
        agience_api_uri: str,
        *,
        token_exchange: Optional[TokenExchange] = None,
        require_auth: bool = True,
    ) -> None:
        from .. import config

        self.client_id = client_id
        self.agience_api_uri = agience_api_uri.rstrip("/")
        # Authentication is required by default: a request carrying no token, or a garbage one, is
        # refused by the middleware before the inner app runs — `initialize` and `tools/list` never
        # answer an unauthenticated caller.
        #
        # No environment override. A variable that switches authentication off is the one setting
        # that gets exported in a shell, forgotten, and inherited by a process nobody meant it for.
        # Turning this off is an explicit keyword at a construction site, where review can see it.
        self.require_auth = require_auth
        # Origin mints the delegation when a caller forwards a raw user token
        # (the gateway model — see `_mint_delegation_for_user`). Read once at
        # construction rather than on every call.
        self.origin_uri = config.origin_uri().rstrip("/")
        self._token_exchange: TokenExchange = token_exchange or _stdlib_token_exchange

        # Per-request ContextVar — name includes client_id so multiple personas
        # mounted in one process stay isolated.
        self.request_user_token: contextvars.ContextVar[str] = contextvars.ContextVar(
            f"agience_request_user_token_{client_id}", default=""
        )

    # ------------------------------------------------------------------
    # Inbound JWT verification (delegation, user)
    # ------------------------------------------------------------------

    def verify_delegation_jwt(self, token: str) -> dict | None:
        """Verify a delegation JWT issued by Mantle with `aud == self.client_id`.

        Validates:
        - RS256 signature against Mantle's inline JWKS in the authority manifest
        - `iss == "mantle"`
        - `aud == self.client_id`
        - `principal_type == "delegation"`
        - `act.sub == "mantle"`
        - Token not expired

        Returns decoded claims on success, ``None`` on any failure.
        """
        if not token:
            return None
        try:
            return _verify_delegation_jwt(
                token,
                expected_issuer="mantle",
                expected_audience=self.client_id,
                expected_actor="mantle",
            )
        except (KeyError, JWTError) as exc:
            log.debug("Delegation JWT rejected for %s: %s", self.client_id, exc)
            return None

    def verify_origin_delegation(self, token: str) -> dict | None:
        """Verify a delegation minted by ORIGIN for this persona.

        Two Origin-minted shapes verify identically here: the gateway user
        exchange (`/internal/delegation-token`, sub=user) and the autonomous
        event-driven describer (`/internal/describe-delegation`, sub=operator-
        rooted system principal, scope=platform.describe). Both carry aud=this
        client_id, act.sub=this client_id, iss=AUTHORITY_ISSUER, and are signed by
        Origin's key — so verify against the `origin` anchor's JWKS with the
        iss-claim check skipped (iss is the issuer URL, not the service name
        "origin"), then confirm it is a delegation issued TO this persona. Returns
        claims or None.
        """
        if not token:
            return None
        try:
            claims = _verify_jwt(token, expected_issuer_service="origin")
        except (KeyError, JWTError) as exc:
            log.debug("Origin delegation rejected for %s: %s", self.client_id, exc)
            return None
        if claims.get("principal_type") != "delegation":
            return None
        if claims.get("aud") != self.client_id:
            return None
        if (claims.get("act") or {}).get("sub") != self.client_id:
            return None
        return claims

    def verify_user_jwt(self, token: str) -> dict | None:
        """Verify a user-token JWT issued by Origin (non-delegation).

        Used by tools that need to confirm a user identity from a forwarded
        bearer token. Audience is variable (per-OAuth-client), so the caller
        gets the decoded claims and inspects `aud` itself.

        Returns decoded claims on success, ``None`` on any failure.
        """
        if not token:
            return None
        try:
            claims = _verify_jwt(token, expected_issuer_service="origin")
            if claims.get("principal_type") == "delegation":
                # Delegation tokens must use verify_delegation_jwt — they have
                # a different aud and require the actor check.
                log.debug(
                    "User JWT rejected for %s: delegation tokens must use verify_delegation_jwt",
                    self.client_id,
                )
                return None
            if not claims.get("aud"):
                log.debug("User JWT rejected for %s: missing aud claim", self.client_id)
                return None
            return claims
        except (KeyError, JWTError) as exc:
            log.debug("User JWT rejected for %s: %s", self.client_id, exc)
            return None

    # Back-compat alias: some callers still use this name. Equivalent semantics.
    def verify_core_jwt(self, token: str) -> dict | None:
        return self.verify_user_jwt(token)

    # ------------------------------------------------------------------
    # Outbound JWT signing (this persona → Mantle or other services)
    # ------------------------------------------------------------------

    def sign_self_jwt(self, audience: str = "mantle", ttl_seconds: int = 300) -> str:
        """Sign a service JWT identifying this persona to a peer service.

        Claims:
            iss = "chorus"            (the signer — the container holding the key)
            sub = "chorus"            (service-as-subject; the signed contract is
                                       that service JWTs keep sub = service name —
                                       `additional_claims` cannot override it, see
                                       `service_identity.sign_service_jwt`)
            client_id = self.client_id  (the acting persona — Iris/Ophan/etc.; this
                                       is how a peer distinguishes personas that
                                       share the one chorus key)
            aud = audience            (peer service; defaults to "mantle")
            principal_type = "service"
            iat / exp = now / now+ttl

        Returns the encoded JWT string.
        """
        return service_identity.sign_service_jwt(
            audience=audience,
            additional_claims={"client_id": self.client_id},
            ttl_seconds=ttl_seconds,
        )

    # ------------------------------------------------------------------
    # Forwarded user token -> delegation (the gateway model)
    # ------------------------------------------------------------------

    async def _mint_delegation_for_user(self, user_token: str) -> str | None:
        """Exchange a forwarded user token for a delegation rooted to that user.

        This is a client of issuance, not issuance. Origin owns the signing key and is the sole
        authority on who the subject is; this side never asserts a `user_id`. That is why the call
        travels with the verifier while the minter stays a service.

        In the gateway model the caller forwards the user's Origin token (not a Mantle-minted
        delegation). To act on the user's behalf with the persona recorded in the chain, this
        forwards the raw user token to Origin as the `subject_token`; Origin verifies it and
        derives the subject itself, then mints an RFC 8693 delegation (sub=user, act.sub=this
        persona, aud=this persona). A local fast-fail verify avoids a round-trip on obvious garbage;
        Origin re-verifies authoritatively. Returns the delegation, or `None` if the token is not a
        valid user token or the mint fails — the caller falls back to the persona's own service
        identity.
        """
        # Fast-fail on obviously-invalid tokens; Origin is the authority.
        if not self.verify_user_jwt(user_token):
            return None
        try:
            return await self._token_exchange(
                self.origin_uri,
                self.client_id,
                user_token,
                f"Bearer {self.sign_self_jwt(audience='origin')}",
            )
        except Exception as exc:  # noqa: BLE001 — any transport failure is a failed mint
            log.warning("delegation mint failed for %s: %s", self.client_id, exc)
            return None

    # ------------------------------------------------------------------
    # Per-request header helpers
    # ------------------------------------------------------------------

    def headers(self, audience: str = "mantle") -> dict[str, str]:
        """Return outbound REST headers carrying this persona's signed platform JWT."""
        return {
            "Authorization": f"Bearer {self.sign_self_jwt(audience=audience)}",
            "Content-Type": "application/json",
        }

    def user_headers(self, audience: str = "mantle") -> dict[str, str]:
        """Outbound REST headers carrying the verified inbound delegation JWT.

        The middleware captures and verifies the inbound delegation token before
        storing it in the ContextVar — presenting it to Mantle endpoints is using
        a token explicitly issued FOR this persona, not forwarding.

        Falls back to ``self.headers()`` (the persona's own platform JWT) when
        there is no user delegation context — startup tasks, background work,
        and direct server-to-server calls land here.
        """
        h = {"Content-Type": "application/json"}
        delegated = self.request_user_token.get("")
        if delegated:
            h["Authorization"] = f"Bearer {delegated}"
            return h
        return self.headers(audience=audience)

    def require_user_headers(self, audience: str = "mantle") -> dict[str, str]:
        """Outbound headers carrying the caller's delegation JWT, or raise.

        The strict counterpart to :meth:`user_headers`. Use this — never
        :meth:`headers` or :meth:`user_headers` — in any tool that reads a
        ``workspace_id``, ``artifact_id``, or other resource id from its
        arguments. Both of the others resolve to the persona's platform JWT
        when no delegation is active, which makes Mantle apply *platform*
        authority to a *caller-chosen* resource.

        Raises:
            MissingDelegationError: when no verified delegation is in context.
        """
        delegated = self.request_user_token.get("")
        if not delegated:
            raise MissingDelegationError(
                f"{self.client_id}: this operation acts on a caller-supplied resource id "
                "and requires a verified user delegation; none is present on this request."
            )
        return {
            "Authorization": f"Bearer {delegated}",
            "Content-Type": "application/json",
        }

    def get_delegation_user_id(self) -> str:
        """Extract the `sub` (user ID) from the stored delegation JWT.

        Returns ``"anonymous"`` when no delegation context is active.
        """
        token = self.request_user_token.get("")
        if not token:
            return "anonymous"
        try:
            claims = jose_jwt.get_unverified_claims(token)
            return claims.get("sub", "anonymous")
        except JWTError:
            return "anonymous"

    # ------------------------------------------------------------------
    # ASGI middleware
    # ------------------------------------------------------------------

    def make_middleware_class(self):
        """Return an ASGI middleware class that verifies and captures delegation JWTs.

        Only delegation JWTs explicitly issued TO this persona (`aud == client_id`)
        are stored. Any other token leaves the ContextVar empty and tools fall
        back to the persona's own platform JWT.
        """
        auth = self

        class UserTokenMiddleware:
            def __init__(self, inner_app: Any) -> None:
                self._app = inner_app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                if scope["type"] != "http":
                    await self._app(scope, receive, send)
                    return

                hdrs = dict(scope.get("headers", []))
                raw_auth = hdrs.get(b"authorization", b"").decode()
                raw_token = raw_auth[7:].strip() if raw_auth.lower().startswith("bearer ") else ""

                # A delegation JWT explicitly issued TO this persona is used as-is
                # (the Mantle-proxy model). Otherwise, if the caller forwarded a raw
                # user token (the gateway model), exchange it for a delegation rooted
                # to that user via Origin. Either way the ContextVar ends up holding
                # a delegation the persona may present back to Mantle.
                if auth.verify_delegation_jwt(raw_token):
                    stored = raw_token            # Mantle-minted delegation for us
                elif auth.verify_origin_delegation(raw_token):
                    stored = raw_token            # Origin-minted delegation for us (gateway/event path)
                else:
                    stored = await auth._mint_delegation_for_user(raw_token) or ""

                # `stored` is empty exactly when no delegation could be established by any of the
                # three routes above — no token, a malformed one, one issued to a different
                # persona, or a user token Origin declined to exchange. Every one of those is an
                # unauthenticated request.
                if auth.require_auth and not stored:
                    # CORS preflight is exempt: a browser sends `OPTIONS` with no `Authorization`
                    # header by specification, to ask whether it may send one. Answering 401 here
                    # would mean no browser could ever reach this persona — a CORS failure
                    # presenting as an auth decision.
                    if scope.get("method", "").upper() != "OPTIONS":
                        await _send_unauthenticated(scope, send, auth.client_id)
                        return

                tok = auth.request_user_token.set(stored)
                try:
                    await self._app(scope, receive, send)
                finally:
                    auth.request_user_token.reset(tok)

        return UserTokenMiddleware

    # ------------------------------------------------------------------
    # Startup + app factory
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Run startup tasks for this persona.

        The chorus host's lifespan calls `init_service_identity("chorus")`
        before any persona module loads. If that hasn't happened, this raises
        — no silent lazy-init.
        """
        service_identity.get_service_identity()
        log.info("ServerAuth ready for %s (chorus identity, kid=chorus-1)", self.client_id)

    def create_app(self, mcp_instance: Any) -> Any:
        """Return the MCP ASGI app wrapped with verifying middleware and startup hook.

        The returned ASGI app:
        - Verifies delegation JWTs on every request
        - Stores verified tokens in the per-request ContextVar
        - Runs `self.startup()` on lifespan startup

        Suitable for both standalone ``uvicorn.run()`` and sub-app mounting in
        the unified chorus host.
        """
        inner_app = mcp_instance.streamable_http_app()
        auth = self

        async def _on_startup() -> None:
            await auth.startup()

        # Pure ASGI lifespan interceptor — runs `_on_startup` after the inner
        # app reports `lifespan.startup.complete`, before forwarding the message.
        class _LifespanWrapper:
            def __init__(self, app: Any) -> None:
                self._app = app

            async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
                if scope["type"] != "lifespan":
                    await self._app(scope, receive, send)
                    return

                startup_hooked = False

                async def _patched_send(message: Any) -> None:
                    nonlocal startup_hooked
                    if (
                        isinstance(message, dict)
                        and message.get("type") == "lifespan.startup.complete"
                        and not startup_hooked
                    ):
                        startup_hooked = True
                        await _on_startup()
                    await send(message)

                await self._app(scope, receive, _patched_send)

        return self.make_middleware_class()(_LifespanWrapper(inner_app))

    # ------------------------------------------------------------------
    # JWE secret delivery — not implemented here
    # ------------------------------------------------------------------

    def decrypt_jwe(self, jwe: dict) -> str:
        """No JWE decryption path exists in this module.

        A credential value is the CONTENT of an ordinary artifact: the write boundary encrypts it
        at rest, and the read path decrypts it for a caller the light cone already authorised. So
        there is nothing for this shim to do — it exists only so a caller still presenting a JWE
        envelope fails fast rather than silently doing nothing.

        CORRECTED 2026-08-25. This docstring named two things that DO NOT EXIST: the content type
        `vnd.agience.secret+json`, which is defined nowhere in the workspace, and a `fetch`
        operation dispatched to `secrets_service.fetch_secret_material` in Mantle, where neither
        that module nor that function is present. The real type is
        `application/vnd.agience.credential+json` (`mantle/services/bootstrap_types.py`, written by
        `seed_provisioning/platform_email.py`), and it needs no operation dispatch or type handler:
        reading the artifact IS the read.
        """
        del jwe
        raise NotImplementedError(
            "JWE decryption was removed. A credential is an ordinary artifact whose content is "
            "encrypted at rest: read it through the artifact API, which decrypts for an "
            "authorised caller. There is no envelope for this method to open."
        )


#: All seven chorus personas import this name. `ServerAuth` is the same class under both names.
AgienceServerAuth = ServerAuth

__all__ = ["ServerAuth", "AgienceServerAuth", "MissingDelegationError", "TokenExchange"]
