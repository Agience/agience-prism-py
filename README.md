# agience-prism

**An environment adapter** — prism adapts an environment (world ↔ frame) to Agience.
This is the Python adapter: the **Agience developer SDK** (Apache-2.0).

```python
from prism import Host, create_server
```

## Install

```bash
pip install agience-prism
```

The base install has **no dependencies**. It carries the contract — canonical JSON, the crystal
model, the capability vocabulary, the config shape, the error set, and the structural address — so a
component can hold the same answers as every other component without taking on an install cost.

Runtime surfaces are extras:

| Extra | Installs | For |
| --- | --- | --- |
| `trust` | python-jose, cryptography | the trust floor: keys, signing, scopes |
| `host` | fastapi, uvicorn, httpx, pyjwt | `prism.Host` |
| `server` | mcp, httpx | `prism.create_server` |
| `cli` | cryptography, httpx | the `prism` command line |
| `vector` | numpy | vector types |
| `wire` | numpy, cryptography | the plane: reach, frames, carriers, settlement |
| `all` | all of the above | |
| `dev` | `all` + pytest, pytest-asyncio, ruff | working on prism itself |

```bash
pip install "agience-prism[host]"
pip install "agience-prism[all]"
```

The runtime surfaces resolve through PEP 562 `__getattr__`, so reaching one without its extra raises
an `ImportError` naming the extra to install, while `from prism.canonical import canonical_string`
costs nothing.

Nine of the sixteen wire modules — carriers, pump, minhash, minting, settlement, extraction, schema,
error_threshold, mcp_bridge — import on the bare base install. `tests/test_wire_extra.py` imports
each in a subprocess with numpy and cryptography blocked, so that claim can fail rather than only be
asserted.

The aperture is reached by **injection** (`prism.instrument`), never by import. A published SDK
depends only on packages its consumers can install.

## Two toolkits

A **host** is compute that serves capabilities over HTTP. The platform reaches it over the wire; it
imports nothing of the platform.

```python
from prism import Host
from pydantic import BaseModel

host = Host("my-host")


class EchoIn(BaseModel):
    text: str


@host.operator("echo", path="/echo")
def echo(req: EchoIn) -> dict:
    """The function's type hints drive request and response validation."""
    return {"echo": req.text}


app = host.app                  # or: host.serve(port=8083)
```

`api_key=...` requires a bearer; `EMBER_URI` + `AGIENCE_TOKEN` make the host self-register on start.
Routes mounted by hand onto `host.app` are unauthenticated — use `Depends(host.auth_dependency)` to
apply the same check `@host.operator` does.

A **server** exposes MCP tools authorized as the calling user: it captures the inbound delegation
token and forwards it on outbound calls, so it only ever acts within that user's authorization.

```python
import json

from prism import create_server

mcp, server = create_server("my-server")


@mcp.tool(description="Echo a message back, with the calling user's id.")
async def echo(message: str) -> str:
    return json.dumps({"echo": message, "user": server.get_user_id()})


app = server.create_app(mcp)    # ASGI; captures the inbound delegation token
```

## The shared contract

`prism/vectors/contract_vectors.json` is the one artifact all three prism SDKs are checked against —
canonical JSON, the crystal sha, the structural address, capability reach.
`tests/test_contract_vectors.py` asserts it here; prism-js and prism-c assert the same bytes. That
file is what makes "one wire format, three languages" a measurement rather than a claim.

The vectors ship inside the wheel, so `pip install agience-prism` is enough to run a conformance
gate — no source tree and no sibling checkout:

```python
from prism.vectors import load_vectors
vectors = load_vectors("contract_vectors")
```

## Self-contained

Prism resolves no path outside its own installation and imports nothing from the components that
depend on it. Where a deployment supplies data — operator bundles for `prism.runner` — it names the
directory with `$AGIENCE_BUNDLE_ROOT` or binds a payload with `register_group()`. Prism never
searches for a sibling checkout, because a path derived from where a file happens to sit is a
fallback that can drift from the bytes the mesh carries while the integrity gate keeps passing.

## Development

```bash
pip install -e ".[dev]"
python -m pytest -q
python -m ruff check .
```

## License

Apache-2.0 — see [`LICENSE`](https://github.com/Agience/agience-prism-py/blob/main/LICENSE) and [`NOTICE`](https://github.com/Agience/agience-prism-py/blob/main/NOTICE). Contributing:
[`CONTRIBUTING.md`](https://github.com/Agience/agience-prism-py/blob/main/CONTRIBUTING.md). Security: [`SECURITY.md`](https://github.com/Agience/agience-prism-py/blob/main/SECURITY.md).

Prism is permissive **deliberately**: build on Agience over the wire with no copyleft reaching your
code. The base install has no dependencies, so depending on it costs nothing.
