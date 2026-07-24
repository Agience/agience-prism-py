# agience-prism-py

**An environment adapter** — prism adapts an environment (world ↔ frame) to Agience.
This is the Python adapter: the **Agience developer SDK** (Apache-2.0). Build on
Agience without copyleft reaching your code — the AGPL platform is reached over the
wire, never linked. No platform IP lives here.

`agience-prism-py` merges the two former SDKs into one package:

- **`prism.host`** — build a **Host**: compute that serves operators over HTTP
  (e.g. Agience Prism, the embeddings host).
- **`prism.server`** — build an **MCP server**: a server that integrates
  with Agience (delegation auth + a core HTTP client + a server scaffold; e.g. Beacon).

```python
from prism import Host, create_server
```

The most-used names (`Host`, `TokenVerifier`, `AuthError`, `Server`, `create_server`)
are re-exported at the top level; the full surfaces live under `prism.host` and
`prism.server`.

> Migrated from `agience-host` + `agience-kit`. Update imports: `agience_host` →
> `prism.host`; `agience_kit` → `prism`. The old **gateway** service is now
> **crystal**, not this SDK.
