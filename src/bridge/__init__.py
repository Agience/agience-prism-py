"""agience-bridge — the Agience developer SDK (Apache-2.0).

Build on Agience without copyleft reaching your code: the AGPL platform is reached
over the wire, never linked. No platform IP lives here. Two toolkits in one package
(the former `agience-host` compute SDK + the original `agience-bridge` MCP-server SDK,
consolidated):

    from bridge import Host           # build a Host (compute serving operators)
    from bridge import create_server  # build an MCP server / Bridge
    from bridge import sign_service_jwt, verify_jwt  # stand on the trust floor

The full surfaces live under ``bridge.host``, ``bridge.bridge``, and
``bridge.trust``; the most-used names are re-exported here.
"""
from . import trust
from .errors import (
    AuthError,
    BridgeError,
    CapabilityNotFound,
    EntitlementError,
    HostUnavailable,
    ProtocolError,
    http_status_for,
    install_error_handlers,
)
from .host import Host, TokenVerifier
from .bridge import Bridge, create_server
from .trust import (
    SERVICE_NAMES,
    ServiceIdentity,
    get_authority_manifest,
    get_host_id,
    get_service_identity,
    init_service_identity,
    sign_delegation_jwt,
    sign_service_jwt,
    verify_delegation_jwt,
    verify_jwt,
)

__version__ = "0.1.0"
__all__ = [
    "Host",
    "TokenVerifier",
    "Bridge",
    "create_server",
    # typed error set (§10)
    "BridgeError",
    "AuthError",
    "EntitlementError",
    "CapabilityNotFound",
    "HostUnavailable",
    "ProtocolError",
    "http_status_for",
    "install_error_handlers",
    # trust floor (bridge.trust)
    "trust",
    "SERVICE_NAMES",
    "ServiceIdentity",
    "get_authority_manifest",
    "get_host_id",
    "get_service_identity",
    "init_service_identity",
    "sign_delegation_jwt",
    "sign_service_jwt",
    "verify_delegation_jwt",
    "verify_jwt",
    "__version__",
]
