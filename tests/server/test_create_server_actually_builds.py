"""`create_server()` is called here, not merely imported.

`prism/server/server.py` reaches its mcp entry point lazily, inside the call, so
`from prism import create_server` succeeds against any installed mcp — including one whose API this
code does not speak. Importing the name therefore proves nothing about the function; only calling it
does.

The mcp coupling is pinned outright, so a version whose entry point has moved fails here, with a
message that names the coupling, rather than in a consumer's first traceback.
"""
from __future__ import annotations

import pytest

mcp_pkg = pytest.importorskip("mcp", reason="the 'server' extra is not installed")

from prism import create_server                                          # noqa: E402
from prism.server import Server                                          # noqa: E402


def test_create_server_returns_a_live_mcp_and_a_wired_server():
    """The call a consumer's first line makes."""
    mcp, server = create_server("probe", instructions="an example server")

    assert mcp is not None, "create_server returned no mcp object"
    assert isinstance(server, Server)
    assert hasattr(mcp, "tool"), (
        "the mcp object has no `tool` decorator — the surface every consumer's first tool uses")


def test_the_tool_decorator_accepts_a_tool():
    """The README's own snippet shape. A decorator that exists but rejects the call is no better."""
    mcp, server = create_server("probe")

    @mcp.tool(description="Echo a message back.")
    async def echo(message: str) -> str:
        return message

    assert callable(echo)


def test_create_app_wraps_the_mcp_app():
    """`server.create_app(mcp)` is the ASGI object a consumer hands to uvicorn."""
    mcp, server = create_server("probe")
    app = server.create_app(mcp)
    assert callable(app), "create_app did not return an ASGI callable"


def test_the_mcp_entry_point_this_code_speaks_is_present():
    """The coupling, stated. `server.py` builds `FastMCP` from `mcp.server.fastmcp`, which is why
    the `server` extra caps mcp below 2 — mcp 2.x carries `mcp.server.mcpserver.MCPServer` instead.
    Lifting the cap means porting `server.py` to that API, and this test is where that decision
    surfaces."""
    pytest.importorskip(
        "mcp.server.fastmcp",
        reason=("this mcp does not carry `mcp.server.fastmcp`. Keep the `mcp[cli]<2` cap, or port "
                "prism/server/server.py to the 2.x `MCPServer` API."))
    from mcp.server.fastmcp import FastMCP

    mcp, _ = create_server("probe")
    assert isinstance(mcp, FastMCP)
