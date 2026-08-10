"""MCP over the Agience signal reach — an MCP skin over a signal core.

An MCP `tools/call {name, arguments}` is a need; the answer is evidence. This bridge maps the MCP tool
envelope onto `reach.py` in both directions, so an existing MCP client is transparently resolved over the
comm plane and an external MCP server is just an organon.

  inbound  (MCP tool → reach): `tools_call(reactor, name, arguments)` places a need addressed to capability
           `name` on the reach and returns the provider's evidence shaped as an MCP `tools/call` result —
           `{"content": [{"type": "text", "text": …}], "isError": bool}`. A persona's `@mcp.tool` handler
           calls this instead of doing the work inline; external MCP hosts keep dialing `/{id}/mcp` unchanged
           as the resolution propagates natively (need → evidence), key-gated by the light-cone.

  outbound (reach → MCP): `external_mcp_handler(call_tool, server_id=…)` is a `need -> evidence` capability
           handler that, on a need, calls an external MCP server (the `chorus_client.call_tool` shape) and
           returns its result as evidence. Register it with `Reactor.serve(cap, handler)` and an external MCP
           server becomes an organon — a world the reach couples to (`iris.proxy_tool`, natively).

This module imports no ember/lumen/sage and no network client: the reach is injected (a `Reactor`) and the
external MCP client is injected (a `call_tool` callable of the `chorus_client.call_tool` shape). It is a pure
shape adapter between the MCP `tools/call` envelope and a need/evidence signal — nothing here couples a
capability or dials a wire. The round trip is event-driven: over the loopback fabric a placed need fires the
provider synchronously (place need → provider fires → places evidence → requester inbox fires); there is
nothing to poll. See `agience-pharos/genesis/MCP-VS-SIGNAL-AUDIT.md` §3 and `prism/reach.py` (the `Reactor`
this module's `reactor` parameter expects).
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

# MIME shape of an MCP tools/call text content item (what FastMCP emits for a str-returning tool).
_TEXT = "text"


# ── shape: MCP tools/call ⇄ need/evidence ─────────────────────────────────────────────────────────────
def need_from_tools_call(name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """An MCP `tools/call {name, arguments}` is a need addressed to capability `name`. The need body carries
    the tool name + arguments verbatim, so a provider (persona tool / organon) resolves it as it would an MCP
    invocation — the envelope is MCP-like, the payload is the request itself."""
    return {"name": name, "arguments": dict(arguments or {})}


def tools_call_result_from_evidence(evidence: Any, *, name: str = "") -> Dict[str, Any]:
    """Shape evidence that propagated back into an MCP `tools/call` result — the exact shape an MCP client
    reads (`{"content": [...], "isError": bool}`), so the client needs no change. Silence (no provider
    coupled the capability) is an MCP error result, never a fabricated success:

      - None                       → isError result ("no provider resolved …") — honest darkness.
      - already MCP-shaped (dict    → returned as-is (an organon that already speaks MCP, e.g. an external
        with a `content` key)         server's result relayed through the plane), isError defaulted False.
      - a content list             → wrapped `{"content": <list>, "isError": False}`.
      - any other value            → serialized to one text content item (a persona tool's plain evidence).
    """
    if evidence is None:
        return {"content": [{"type": _TEXT, "text": "no provider resolved capability %r" % name}],
                "isError": True}
    if isinstance(evidence, dict) and "content" in evidence:
        return {"content": evidence["content"], "isError": bool(evidence.get("isError", False))}
    if isinstance(evidence, list):
        return {"content": evidence, "isError": False}
    text = evidence if isinstance(evidence, str) else json.dumps(evidence, sort_keys=True, default=str)
    return {"content": [{"type": _TEXT, "text": text}], "isError": False}


# ── inbound: an MCP tools/call lands as a need, evidence returns as an MCP result ──────────────────────
def dispatch_tools_call(reactor: Any, name: str, arguments: Optional[Dict[str, Any]] = None,
                        *, cap: Optional[str] = None) -> Tuple[Any, Dict[str, Any]]:
    """Place an MCP `tools/call` on the reach as a need addressed to capability `cap` (default: the tool
    `name`) and absorb the evidence. Returns `(handle, mcp_result)`: the opaque reach handle (how the reach
    ties the evidence back to this need — provenance the caller can assert the round trip crossed the plane)
    and the MCP `tools/call` result.

    The bridge depends only on the stable `Reactor` surface — `reach(need, to=cap) -> handle` and
    `evidence(handle)`; the return mechanism (ground-plane provenance vs. carried address) is the reach's
    internal concern and is treated as opaque here.

    Propagation, not a blocking RPC: `reactor.reach` places the need and the provider fires on arrival; over
    the loopback fabric the evidence is present synchronously (event-driven, no poll). Isolation is the
    plane's — the need is sealed with the capability's group key, so only a provider whose light-cone reaches
    it can open it."""
    cap = cap or name
    handle = reactor.reach(need_from_tools_call(name, arguments), to=cap)
    return handle, tools_call_result_from_evidence(reactor.evidence(handle), name=name)


def tools_call(reactor: Any, name: str, arguments: Optional[Dict[str, Any]] = None,
               *, cap: Optional[str] = None) -> Dict[str, Any]:
    """The MCP-facing inbound entry point: an MCP `tools/call` resolved over the reach, returning only the
    MCP result (`dispatch_tools_call` without the reach handle). This is what a persona's `@mcp.tool`
    handler calls in place of doing the work inline — external MCP hosts see a normal MCP server, the work
    propagates natively as a signal."""
    return dispatch_tools_call(reactor, name, arguments, cap=cap)[1]


# ── outbound: a need calls an external MCP server; its result is evidence (external MCP = organon) ─────
def external_mcp_handler(call_tool: Callable[..., Any], *, server_id: str, user_id: str = "organon",
                         tool_name: Optional[str] = None) -> Callable[[Any], Any]:
    """A `need -> evidence` capability handler that resolves a need by calling an external MCP server, so the
    external server is just an organon — a world the reach couples to. `call_tool` is injected with the
    `chorus_client.call_tool(server_id, tool_name, arguments, *, user_id) -> content_list` shape; this module
    dials nothing itself. The external server's result (an MCP content list) is returned as evidence, already
    MCP-shaped so it relays back through the plane and out to an MCP client unchanged.

    Register it as the provider of a capability (e.g. `net.mcp`): `reactor.serve("net.mcp", handler)`. The
    need carries `{name, arguments}` (see `need_from_tools_call`); `tool_name` overrides the tool invoked on
    the external server when the reach capability name differs from the remote tool name."""
    def handler(need: Any) -> Dict[str, Any]:
        req = need if isinstance(need, dict) else {}
        remote_tool = tool_name or req.get("name")
        arguments = req.get("arguments", {})
        content = call_tool(server_id, remote_tool, arguments, user_id=user_id)
        return {"content": content, "isError": False}
    return handler


def serve_external_mcp(reactor: Any, capability: str, call_tool: Callable[..., Any], *, server_id: str,
                       user_id: str = "organon", tool_name: Optional[str] = None) -> Any:
    """Register an external MCP server as the organon behind `capability` on `reactor`'s reach. A need to the
    capability is resolved by calling the external server; its result propagates back as evidence. Returns
    the `Provider`."""
    return reactor.serve(capability, external_mcp_handler(call_tool, server_id=server_id, user_id=user_id,
                                                          tool_name=tool_name))


__all__ = ["need_from_tools_call", "tools_call_result_from_evidence", "dispatch_tools_call", "tools_call",
           "external_mcp_handler", "serve_external_mcp"]
