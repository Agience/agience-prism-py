"""agience-prism-py — an environment adapter: the Agience developer SDK for Python (Apache-2.0).

Prism adapts an environment (world <-> frame) to Agience.
Build on Agience without copyleft reaching your code: the AGPL platform is reached
over the wire, never linked. No platform IP lives here. Two toolkits in one package
(the former `agience-host` compute SDK + the original `agience-prism-py` MCP-server SDK,
consolidated):

    from prism import Host           # build a Host (compute serving operators)
    from prism import create_server  # build an MCP server
    from prism import sign_service_jwt, verify_jwt  # stand on the trust floor

The full surfaces live under ``prism.host``, ``prism.server``, and
``prism.trust``; the most-used names are re-exported here.
"""
from . import trust
from .errors import (
    AuthError,
    PrismError,
    CapabilityNotFound,
    EntitlementError,
    HostUnavailable,
    ProtocolError,
    http_status_for,
    install_error_handlers,
)
from .host import Host, TokenVerifier
from .server import Server, create_server
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
    "Server",
    "create_server",
    # typed error set (§10)
    "PrismError",
    "AuthError",
    "EntitlementError",
    "CapabilityNotFound",
    "HostUnavailable",
    "ProtocolError",
    "http_status_for",
    "install_error_handlers",
    # trust floor (prism.trust)
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
