"""Server template — a minimal Agience MCP server built on agience-bridge.

A *server* exposes MCP tools/resources to agents, authorized as the calling
**user**: the Bridge captures the inbound delegation token and forwards it on
outbound calls, so the server only ever acts within that user's authorization.
Copy this, add your tools, run it, then register it as a
`vnd.agience.mcp-server+json` artifact so the Chorus gateway routes to it.

A *host* (agience-bridge) can run servers like this directly, controlled by
artifacts — see examples/host/host_template.py for the compute side.

Run:
    pip install agience-bridge uvicorn
    AGIENCE_API_URI=http://localhost:8081 python examples/bridge/server_template.py
"""
import json

from bridge import create_server

mcp, bridge = create_server(
    "agience-server-example",
    instructions="Example server demonstrating agience-bridge.",
)


@mcp.tool(description="Echo a message back, with the calling user's id.")
async def echo(message: str) -> str:
    return json.dumps({"echo": message, "user": bridge.get_user_id()})


@mcp.tool(description="Search the caller's authorized artifacts via Agience.")
async def search(query: str, size: int = 10) -> str:
    result = await bridge.client().search_query(query_text=query, candidate_budget=size * 5)
    return json.dumps(result)


app = bridge.create_app(mcp)  # ASGI app; captures the inbound delegation token


if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run(app, host=os.getenv("MCP_HOST", "0.0.0.0"), port=int(os.getenv("MCP_PORT", "8099")))
