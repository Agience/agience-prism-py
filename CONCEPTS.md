# Concepts — and how they map to MCP

Agience is MCP-native. This pins the SDK vocabulary and aligns it with the
**Model Context Protocol** so hosts, capabilities, and the platform speak one
language — and flags the one term that collides.

## Agience vocabulary

- **agience-host / Bridge** — the SDKs you *embed* to build a host. **agience-host** = the
  compute/operator flavor; **Bridge** = the MCP-server flavor. Permissive; no
  platform IP. A host *is/has* one or both.
- **Host** — COMPUTE that connects to the platform and exposes one or more
  capabilities. **Hosts live in their own repos and depend on the SDK — never
  inside it.**
- **Capability** (= operator / skill) — a unit of work a host exposes and runs,
  e.g. `embeddings.embed`. Used by a host; operates on artifacts.
- **Artifact** — the data a capability reads/writes.
- **Platform (Mantle)** — routes a capability invocation to a host that advertises
  it (and is entitled). The AGPL reference implementation; reached over the wire.

## MCP mapping

MCP roles: **Host** (the AI application — Claude Desktop, an IDE, an agent — holds
the model and contains clients) → **Client** (1:1 with a server) → **Server**
(exposes **capabilities** — tools, resources, prompts — negotiated at `initialize`).

| Agience | MCP | Notes |
|---|---|---|
| agience-host / Bridge (SDK) | the MCP server SDK | Bridge already wraps FastMCP |
| **Host** (compute) | **Server** | ⚠️ name clash — see below |
| **Capability / operator** | a **capability**, exposed as a **tool** (or resource) | `embeddings.embed` is a tool the host exposes; advertised via capability negotiation |
| **Artifact** | **Resource** (`agience://…`) | Agience already serves artifacts as MCP resources |
| Facet / the agent / the gateway (the consumer) | MCP **Host + Client** | the side that *uses* capabilities |

## The one clash to know: "Host"

In **MCP**, *Host* = the **AI application** (client side). In **Agience**, *Host* =
the **compute that exposes capabilities** — which is MCP's **Server** role.

> **An Agience host presents as an MCP server.** MCP's "host" role (the AI app) is,
> in Agience, Facet / the agent / Mantle's gateway.

We keep "Host" (it's entrenched: `vnd.agience.host+json`, `package/hosts/`), but
read it as *capability provider / MCP server*, **not** MCP's "host."

## Why this unifies Agience

A **Chorus persona** and the **embeddings host** are the *same shape*: compute (a
host) exposing capabilities (MCP **tools** / **resources**), built on the SDK — the
persona via the **bridge** (MCP flavor), embeddings via the **agience-host** (compute
flavor). **Beacon** is the same, with *closed* capabilities, entitlement-gated. The
existing scope grammar `resource|tool|prompt : mime : action` is already MCP
primitives — a capability is invoked through the `tool` scope on a content type.

**One model:** hosts expose capabilities (MCP tools/resources) · the platform
routes · the agent consumes.
