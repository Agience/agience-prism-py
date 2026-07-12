# agience-bridge

The **Agience developer SDK** (Apache-2.0). Build on Agience without copyleft
reaching your code — the AGPL platform is reached over the wire, never linked.
No platform IP lives here.

`agience-bridge` merges the two former SDKs into one package:

- **`agience_bridge.host`** — build a **Host**: compute that serves operators over HTTP
  (e.g. Agience Prism, the embeddings host).
- **`agience_bridge.bridge`** — build an **MCP server / Bridge**: a server that integrates
  with Agience (delegation auth + a core HTTP client + a server scaffold; e.g. Beacon).

```python
from agience_bridge import Host, create_server
```

The most-used names (`Host`, `TokenVerifier`, `AuthError`, `Bridge`, `create_server`)
are re-exported at the top level; the full surfaces live under `agience_bridge.host` and
`agience_bridge.bridge`.

> Migrated from `agience-host` + the original `agience-bridge` SDK (briefly packaged as
> `agience-kit`). Update imports: `agience_host` → `agience_bridge` (or
> `agience_bridge.host`); `agience_kit` → `agience_bridge`. The old `agience-bridge`
> **gateway** service is now part of **chorus**, not this SDK.
