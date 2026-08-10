"""Server template — a minimal Agience MCP server built on agience-prism-py.

A *server* exposes MCP tools/resources to agents, authorized as the calling
**user**: the Server captures the inbound delegation token and forwards it on
outbound calls, so the server only ever acts within that user's authorization.
Copy this, add your tools, run it, then register it as a
`vnd.agience.mcp-server+json` artifact so the Chorus gateway routes to it.

A *host* (agience-prism-py) can run servers like this directly, controlled by
artifacts — see examples/host/host_template.py for the compute side.

Run:
    pip install "agience-prism-py[server]" uvicorn
    MANTLE_URI=http://localhost:8081 python examples/server/server_template.py

The `server` extra carries mcp and httpx; uvicorn is named separately because this
template runs it directly.
"""
import json

from prism import create_server

mcp, server = create_server(
    "agience-server-example",
    instructions="Example server demonstrating agience-prism-py.",
)


@mcp.tool(description="Echo a message back, with the calling user's id.")
async def echo(message: str) -> str:
    return json.dumps({"echo": message, "user": server.get_user_id()})


@mcp.tool(description="Search the caller's authorized artifacts via Agience.")
async def search(query: str, size: int = 10) -> str:
    result = await server.client().search_query(query_text=query, candidate_budget=size * 5)
    return json.dumps(result)


app = server.create_app(mcp)  # ASGI app; captures the inbound delegation token


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("MCP_HOST", "0.0.0.0"), port=int(os.getenv("MCP_PORT", "8099")))
