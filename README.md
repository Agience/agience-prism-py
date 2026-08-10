# agience-prism-py

**An environment adapter** — prism adapts an environment (world ↔ frame) to Agience.
This is the Python adapter: the **Agience developer SDK** (Apache-2.0).

```python
from prism import Host, create_server
```

## Install

```bash
pip install agience-prism-py
```

The base install has no dependencies. It carries the contract — canonical JSON, the crystal model,
the capability grammar, the instrument protocol, and the derivations built on them — so that a
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

```bash
pip install "agience-prism-py[host]"
pip install "agience-prism-py[all]"
```

Reaching a surface without its extra raises an `ImportError` naming the extra to install.
