# agience-prism-py

**An environment adapter** — prism adapts an environment (world ↔ frame) to Agience.
This is the Python adapter: the **Agience developer SDK** (Apache-2.0). Build on
Agience without copyleft reaching your code — the AGPL platform is reached over the
wire, never linked. No platform IP lives here.

`agience-prism-py` is one package with two surfaces:

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
> `prism.host`; `agience_kit` → `prism`. The **gateway** service lives in **crystal**.


> 📇 **Index addition — 2026-07-31, DOCS audit (`G6-0023`).** The prism vocabulary and its MCP
> mapping are pinned in **`CONCEPTS.md`**, which lives in the **`py/` leg** at
> `agience-prism/py/CONCEPTS.md`. It is **language-neutral** — it names prism, host,
> capability, artifact and platform, and flags the one term that collides with MCP — so a Python
> implementer needs it as much as a Python one.
>
> ⚠ **It was NOT moved to `agience-prism/CONCEPTS.md`.** That was the placement plan's step 9.1 and
> it is **refused**: `agience-prism/` is not a git repository — `c/`, `js/` and `py/` are three
> separate repositories under a plain directory — so the move would have taken a tracked document out
> of version control entirely. Making a document unversioned to fix its reach is a worse defect than
> the one being fixed. The reach is repaired with a pointer instead, which is what an orphan calls
> for. The language-neutral **contract** every leg implements is a different document:
> `agience-pharos/features/prism-protocol.md`.
