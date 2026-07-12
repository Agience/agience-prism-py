"""agience-bridge — SDK for building MCP servers that integrate with Agience.

Apache-2.0, and permissive **on purpose**: `agience-core` is AGPL-3.0, but the
integration boundary is permissive so any server — first-party persona, premium
add-on (e.g. Beacon), or third-party — can build on it without copyleft reaching
their code. This package contains only integration glue (auth delegation, a core
HTTP client, a server scaffold); **no platform IP**.

Quickstart::

    from agience_bridge import create_server
    mcp, bridge = create_server("agience-server-foo")

    @mcp.tool(description="…")
    async def foo(...): ...

    app = bridge.create_app(mcp)

Importing this package pulls no heavy deps; ``mcp`` is imported lazily by
``create_server`` and ``httpx`` by the client.
"""

from .auth import Bridge
from .server import create_server

__version__ = "0.1.0"
__all__ = ["Bridge", "create_server", "__version__"]
