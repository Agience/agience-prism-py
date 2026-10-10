"""Which verified tokens a service may take as a caller's identity — the claim rule, in one place.

A valid signature says who minted a token. It does not say what the token is for. Origin signs every
token it issues with the one key, so the refresh token, the email-verification link, the
password-reset link, a delegation minted for another server and an ordinary access token all verify
against the same `origin` trust anchor. A verifier that stops at the signature accepts every one of
them as a session. What separates them is in the claims, and this module reads those claims.

It holds no cryptography. The caller verifies the signature and expiry first, with whatever library
its install carries (`prism.trust` uses `jose`, `prism.host` uses PyJWT), and passes the decoded
claims here. Keeping the rule free of both is what lets every verifier in the workspace apply the
same rule: the base install has no dependencies, so any component can import it.

## How Origin marks what a token is for

`origin/services/auth_service.py` and `origin/routers/auth_router.py` mint these:

  ===================================  ====================  ===========================  ==========
  token                                `token_type` claim    `principal_type`             `aud`
  ===================================  ====================  ===========================  ==========
  access, first-party client           absent                absent (a user)              issuer
  access, third-party MCP client       absent                `mcp_client`                 client id
  refresh (30 days)                    `refresh`             as the access token          as access
  email verification link (24 h)       `email_verify`        absent                       issuer
  password reset link (1 h)            `pwd_reset`           absent                       issuer
  delegation (RFC 8693)                absent                `delegation`, with `act.sub` server id
  client_credentials server token      absent                `server`                     `agience`
  ===================================  ====================  ===========================  ==========

`issuer` is `AUTHORITY_ISSUER`, which the init container also writes into the authority manifest as
`issuer`. `"token_type": "bearer"` in an OAuth *response body* is a field beside `access_token`,
never a claim inside one.

So the rule has two parts:

  1. **Purpose.** A token carrying any `token_type` claim is a special-purpose token whose only
     consumer is its own Origin endpoint. It is never a credential anywhere else. Every verifier
     applies this, whatever principal it accepts: :func:`purpose_refusal`.
  2. **Caller.** A token taken as a *caller's identity* must name a caller: a user (whose token is
     addressed to the authority issuer), an MCP client (addressed to that client), or a delegation
     (addressed to the server it was minted for, with the acting server in `act.sub`). A
     `server` or `service` token names a program, and Origin's own `resolve_auth` treats it as one:
     :func:`caller_refusal`.

Both return a reason string, or `None` when the claims pass. A reason rather than a boolean so the
refusal can be logged by what it refused.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlsplit

#: The claim Origin stamps on every special-purpose token and never on an access token.
PURPOSE_CLAIM = "token_type"

USER = "user"
MCP_CLIENT = "mcp_client"
DELEGATION = "delegation"

#: The principal types that name a caller. A token without `principal_type` is a user's.
CALLER_PRINCIPAL_TYPES = frozenset({USER, MCP_CLIENT, DELEGATION})


def issuer_origin(uri: Optional[str]) -> str:
    """Reduce an issuer URI to `scheme://host[:port]`, which is how Origin states it.

    Origin's `AUTHORITY_ISSUER` passes through `_origin_only`, which drops path, query and fragment;
    the manifest's `issuer` is written from the same environment variable without that step. Both
    sides are reduced here so a trailing slash on one of them is not a refusal.
    """
    raw = (uri or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _audiences_of(claims: Mapping[str, Any]) -> list[str]:
    aud = claims.get("aud")
    if isinstance(aud, str):
        return [aud] if aud else []
    if isinstance(aud, (list, tuple)):
        return [a for a in aud if isinstance(a, str) and a]
    return []


def purpose_refusal(claims: Mapping[str, Any]) -> Optional[str]:
    """Refuse a special-purpose token. `None` when the claims carry no `token_type`.

    Any value refuses, including an empty string: Origin never writes the claim on an access token,
    so its presence is the whole signal.
    """
    if PURPOSE_CLAIM in claims:
        return (f"a {claims.get(PURPOSE_CLAIM)!r} token is not an access token; "
                "it is accepted only at its own Origin endpoint")
    return None


def caller_refusal(
    claims: Mapping[str, Any],
    *,
    issuer: Optional[str],
    delegation_audiences: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Refuse claims that are not an access token naming a caller. `None` when they are.

    `claims` are already signature- and expiry-verified against the `origin` trust anchor.

    Audience, per principal type:

      * **user** — must be `issuer`, the authority issuer (the manifest's `issuer`). With no issuer
        to compare against, user tokens are refused rather than accepted unchecked.
      * **mcp_client** — must be non-empty. Origin addresses these to the third-party client that
        requested them, so the audience names the client, not a resource server; no resource
        server can hold the list, and Origin's own `resolve_auth` checks only that it is present.
      * **delegation** — must be one of `delegation_audiences`, the client ids this service
        answers to as a server. `None` accepts any non-empty audience, for a service that fronts
        servers it cannot enumerate; an empty collection refuses delegations outright, for a
        service no delegation is minted for, or one with its own delegation path.
    """
    refused = purpose_refusal(claims)
    if refused:
        return refused

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        return "the token names no subject"

    principal_type = claims.get("principal_type") or USER
    if principal_type not in CALLER_PRINCIPAL_TYPES:
        return f"principal_type {principal_type!r} names a program, not a caller"

    token_auds = _audiences_of(claims)
    if not token_auds:
        return "the token has no audience"

    if principal_type == USER:
        want = issuer_origin(issuer)
        if not want:
            return "no authority issuer is known, so a user token's audience cannot be checked"
        if not any(issuer_origin(a) == want for a in token_auds):
            return f"a user token addressed to {token_auds!r}, not to the authority {want!r}"
        return None

    if principal_type == DELEGATION:
        act = claims.get("act")
        actor = act.get("sub") if isinstance(act, Mapping) else None
        if not isinstance(actor, str) or not actor:
            return "a delegation with no acting server (`act.sub`)"
        if delegation_audiences is not None:
            allowed = {a for a in delegation_audiences if a}
            if not any(a in allowed for a in token_auds):
                return f"a delegation addressed to {token_auds!r}, not to this service"
    return None


__all__ = [
    "PURPOSE_CLAIM", "USER", "MCP_CLIENT", "DELEGATION", "CALLER_PRINCIPAL_TYPES",
    "issuer_origin", "purpose_refusal", "caller_refusal",
]
