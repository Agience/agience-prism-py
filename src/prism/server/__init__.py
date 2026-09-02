"""The MCP server surface — SDK for building MCP servers that integrate with Agience.

Installed with `pip install "agience-prism[server]"`.

Apache-2.0, and permissive on purpose: the AGPL components are the platform (ember,
origin, chorus), and the integration boundary is permissive so any server — first-party
persona, premium add-on, or third-party — can build on it without copyleft reaching
their code. This package holds only integration glue: auth delegation, a core HTTP
client, a server scaffold. No platform IP.

The licence rule holds by topology rather than by anyone remembering it: AGPL
components are sinks, so nothing imports them. Everything imports prism, which is why
prism is not one of them.

Quickstart::

    from prism import create_server
    mcp, server = create_server("agience-server-foo")

    @mcp.tool(description="…")
    async def foo(...): ...

    app = server.create_app(mcp)

Importing this package pulls no heavy deps; ``mcp`` is imported lazily by
``create_server`` and ``httpx`` by the client.
"""

from .auth import Server
from .server import create_server

from .. import __version__          # one version for the package, read from `prism`
__all__ = ["Server", "create_server", "__version__"]
