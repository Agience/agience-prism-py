"""Server scaffold — spin up an Agience-integrated MCP server in a few lines.

    from prism import create_server

    mcp, server = create_server("agience-server-example", instructions="…")

    @mcp.tool(description="…")
    async def my_tool(...): ...

    app = server.create_app(mcp)   # ASGI app with delegation-token capture
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from .. import config
from .auth import Server


def create_server(
    name: str,
    *,
    instructions: str = "",
    api_uri: Optional[str] = None,
    crystal_uri: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Tuple[object, Server]:
    """Build a FastMCP server + an Agience :class:`Server` wired for delegation auth.

    ``api_uri`` defaults to the canonical ``$MANTLE_URI`` (§4); ``crystal_uri`` to
    ``$CRYSTAL_URI``; ``api_key`` to ``$AGIENCE_API_KEY``. Returns ``(mcp, server)``
    — define tools on ``mcp``, then serve ``server.create_app(mcp)``.
    """
    from mcp.server.fastmcp import FastMCP  # lazy: importing this package needs no mcp

    server = Server(
        name,
        api_uri or config.mantle_uri(),
        crystal_uri=crystal_uri,
        api_key=api_key or os.getenv("AGIENCE_API_KEY"),
    )
    mcp = FastMCP(name, instructions=instructions)
    return mcp, server
