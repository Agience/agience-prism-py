"""Origin's signed verdict that a sealed secret may be used, and the persona's check of it.

A persona opens a credential's sealed copy only for a use Origin itself decided (review 21, F1).
Mantle hands over the sealed copy, but Mantle's word that the use is allowed is not enough: a
Mantle that is taken over would say yes to anything. So Mantle's `/use` also returns a verdict
Origin signed after its own walk over its replica of the authority ledger, on the persona's own
Origin-issued delegation as the acting credential. The verdict binds:

  persona          the persona the secret is sealed to, and the verdict's audience
                   (`aud` = `agience-server-<persona>`)
  sub              the subject the persona acts for: the person, or the platform system principal
                   for a platform purpose (`SYSTEM_SCOPES`)
  delegation_jti   the `jti` of the delegation the persona acts on
  credential_id    the credential whose secret is used
  card_id          the card it is used for
  grants           the grant ids that decided it: the subject's Invoke on the card
                   (`invoke_card`) and on the credential (`invoke_credential`), and the persona's
                   Read on the credential (`read`)
  sealed_sha256    the SHA-256 of the persona's sealed copy, and of the credential's endpoint
  endpoints_sha256 list, as the credential's writer recorded them at Origin (review 22): a copy
                   Mantle sealed itself does not match (`sealed_digest`, `endpoints_digest`)
  nonce            the persona's own fresh nonce for this one use, sent in `/use`: a verdict
                   Mantle asks for on its own is for no use the persona made

It is signed with Origin's key, carries `token_type` `use_verdict` (so every check that takes an
access token refuses it as a bearer), and lives `VERDICT_TTL` seconds.

The persona checks it against the manifest's `origin` anchor and issuer, and matches its `sub` and
`delegation_jti` to the delegation it acts on, which it also verifies here against Origin's anchor.
A grant key, a token Origin did not sign, or a delegation whose actor is not this persona proven by
its own key (`act.iss`) uses no secret.

The seal itself binds the persona's key id and the credential id (`prism.trust.sealing`). It cannot
also bind the subject: a credential is sealed once, when it is written, to each persona that will
use it, and one sealed copy serves every caller who holds Invoke on it. Binding a caller would mean
resealing per use, which needs the plaintext at the sealer. The verdict carries that binding
instead.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

#: The verdict's `token_type`.
TOKEN_TYPE = "use_verdict"

#: How long a verdict lives, in seconds.
VERDICT_TTL = 60

#: A few seconds for clocks.
SKEW = 5

#: The platform purposes a secret may be used on, by system delegation scope, and the one persona
#: that carries each out. Every other system delegation uses no secret.
SYSTEM_SCOPES: Dict[str, str] = {"platform.email.send": "iris"}

#: The claim naming each grant that decided a verdict.
GRANT_CLAIMS = ("invoke_card", "invoke_credential", "read")

SERVER_PREFIX = "agience-server-"


def sealed_digest(sealed: Dict[str, Any]) -> str:
    """The SHA-256 of a sealed copy, over its canonical JSON."""
    return hashlib.sha256(json.dumps(sealed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def endpoints_digest(endpoints: List[str]) -> str:
    """The SHA-256 of a credential's endpoint list, in its order, as canonical JSON."""
    return hashlib.sha256(json.dumps([str(e) for e in endpoints or []], separators=(",", ":"),
                                     ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


class VerdictRefused(PermissionError):
    """The use is not one Origin decided for this persona. The message carries no secret."""


def persona_delegation(token: str, persona: str) -> Dict[str, Any]:
    """The claims of `token` when it is an Origin-signed delegation this persona acts on, proven
    by its own key: `act.sub` = `agience-server-<persona>`, `act.iss` = `<persona>`, with a `jti`.
    Raises `VerdictRefused` otherwise (a grant key, another signer's token, another actor)."""
    from .server_auth import is_grant_key

    if not token or is_grant_key(token):
        raise VerdictRefused("a grant key uses no secret: a secret is used only on a delegation "
                             "Origin issued to the persona")
    try:
        from .authority_trust import verify_origin_jwt
        claims = verify_origin_jwt(token)
    except Exception:  # noqa: BLE001 — unsigned by Origin, expired, no manifest
        raise VerdictRefused("the persona's delegation is not one Origin signed") from None
    act = claims.get("act") if isinstance(claims.get("act"), dict) else {}
    if (claims.get("principal_type") != "delegation"
            or act.get("sub") != SERVER_PREFIX + persona or act.get("iss") != persona):
        raise VerdictRefused(f"the delegation is not {persona}'s own, proven by its own key")
    if not isinstance(claims.get("jti"), str) or not claims.get("jti"):
        raise VerdictRefused("the delegation carries no jti, so no verdict can be bound to it")
    if not claims.get("sub"):
        raise VerdictRefused("the delegation names no subject")
    return claims


def verify(token: str, *, persona: str, delegation: Dict[str, Any], credential_id: str,
           card_id: str, sealed: Dict[str, Any], endpoints: List[str], nonce: str,
           now: Optional[float] = None) -> Dict[str, Any]:
    """The verdict's claims when Origin signed it for this use, for this sealed copy and endpoint
    list as Mantle served them, and for this nonce; raises `VerdictRefused`."""
    if not token:
        raise VerdictRefused("Mantle returned no verdict from Origin, so nothing is opened")
    try:
        from .authority_trust import verify_origin_jwt
        claims = verify_origin_jwt(token, expected_audience=SERVER_PREFIX + persona)
    except Exception:  # noqa: BLE001
        raise VerdictRefused("the verdict is not one Origin signed for this persona") from None
    t = time.time() if now is None else now
    iat, exp = claims.get("iat"), claims.get("exp")
    checks = (
        (claims.get("token_type") == TOKEN_TYPE, "not a use verdict"),
        (claims.get("persona") == persona, "for another persona"),
        (str(claims.get("sub") or "") == str(delegation.get("sub") or ""),
         "for another subject than the delegation"),
        (claims.get("delegation_jti") == delegation.get("jti"), "bound to another delegation"),
        (claims.get("credential_id") == credential_id, "for another credential"),
        (claims.get("card_id") == card_id, "for another card"),
        (bool(nonce) and claims.get("nonce") == nonce, "for another use than this one"),
        (claims.get("sealed_sha256") == sealed_digest(sealed or {}),
         "for another sealed copy than the one Mantle served"),
        (claims.get("endpoints_sha256") == endpoints_digest(endpoints or []),
         "for another endpoint list than the one Mantle served"),
        (isinstance(iat, (int, float)) and isinstance(exp, (int, float))
         and exp - iat <= VERDICT_TTL + SKEW and iat <= t + SKEW, "not short-lived"),
        (all(isinstance((claims.get("grants") or {}).get(k), str)
             and (claims.get("grants") or {}).get(k) for k in GRANT_CLAIMS),
         "naming no grant that decided it"),
    )
    for ok, why in checks:
        if not ok:
            raise VerdictRefused(f"Origin's verdict is {why}; nothing is opened")
    return claims


__all__ = ["TOKEN_TYPE", "VERDICT_TTL", "SYSTEM_SCOPES", "GRANT_CLAIMS", "VerdictRefused",
           "persona_delegation", "verify", "sealed_digest", "endpoints_digest"]
