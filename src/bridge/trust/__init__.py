"""bridge.trust — the Agience trust floor (Apache-2.0).

The shared platform-service identity + JWT signing/verification + key management that
every Agience *app* component (Origin, Chorus, the gateway) — and any third-party
Host or MCP server — stands on. No platform IP: just the auth plumbing. The floor
reads ``KEYS_DIR`` straight from the environment; the app configures the library,
never the reverse.

    from bridge.trust import service_identity, authority_trust, key_manager
    from bridge.trust import sign_service_jwt, verify_jwt

Deliberately NOT a dependency of Mantle — the database verifies tokens via a thin
issuer+JWKS seam and never signs, so it stays application-agnostic.
"""
from . import authority_trust, key_manager, service_identity
from .authority_trust import (
    get_authority_manifest,
    verify_delegation_jwt,
    verify_jwt,
)
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
    "authority_trust", "key_manager", "service_identity",
    "verify_jwt", "verify_delegation_jwt", "get_authority_manifest",
    "init_service_identity", "get_service_identity", "ServiceIdentity",
    "sign_service_jwt", "sign_delegation_jwt", "get_host_id", "SERVICE_NAMES",
]
