"""agience-bridge — the Agience developer SDK (Apache-2.0).

Build on Agience without copyleft reaching your code: the AGPL platform is reached
over the wire, never linked. No platform IP lives here. Two toolkits in one package
(the former `agience-host` compute SDK + the original `agience-bridge` MCP-server SDK,
consolidated):

    from agience_bridge import Host           # build a Host (compute serving operators)
    from agience_bridge import create_server  # build an MCP server / Bridge

The full surfaces live under ``agience_bridge.host`` and ``agience_bridge.bridge``; the
most-used names are re-exported here.
"""
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
    "__version__",
]
