"""prism.trust — the Agience trust floor (Apache-2.0).

The shared platform-service identity + JWT signing/verification + key management that
every Agience *app* component (Origin, Chorus, the gateway) — and any third-party
Host or MCP server — stands on. No platform IP: just the auth plumbing. The floor
reads ``KEYS_DIR`` straight from the environment; the app configures the library,
never the reverse.

    from prism.trust import service_identity, authority_trust, key_manager
    from prism.trust import sign_service_jwt, verify_jwt
    from prism.trust import ServerAuth              # the per-persona host adapter
    from prism.trust.scopes import parse_scope      # the claim vocabulary

Mantle stands outside this package: the database verifies tokens through a thin
issuer+JWKS seam and never signs, so it stays application-agnostic.

**Verification is a contract; issuance is a service.** Verifying a token and reading a scope string
are pure functions of bytes plus an on-disk key, identical in every deployment and needed by every
consumer, so they live here. OIDC, WebAuthn, key custody and the delegation-token endpoint are
stateful and per-deployment: they live in Origin and are reached over the wire at `ORIGIN_URI`.
Each module's docstring states which side of that line it is on.
"""
from . import authority_trust, key_manager, opsign, scopes, server_auth, service_identity
from .authority_trust import (
    get_authority_manifest,
    verify_delegation_jwt,
    verify_jwt,
)
from .server_auth import AgienceServerAuth, MissingDelegationError, ServerAuth
from .service_identity import (
    SERVICE_NAMES,
    ServiceIdentity,
    get_host_id,
    get_service_identity,
    init_service_identity,
    sign_delegation_jwt,
    sign_service_jwt,
)

__all__ = [
    "authority_trust", "key_manager", "opsign", "scopes", "server_auth", "service_identity",
    "verify_jwt", "verify_delegation_jwt", "get_authority_manifest",
    "init_service_identity", "get_service_identity", "ServiceIdentity",
    "sign_service_jwt", "sign_delegation_jwt", "get_host_id", "SERVICE_NAMES",
    "ServerAuth", "AgienceServerAuth", "MissingDelegationError",
]
