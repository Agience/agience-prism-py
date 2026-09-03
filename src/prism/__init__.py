"""agience-prism — an environment adapter: the Agience developer SDK for Python (Apache-2.0).

Prism adapts an environment (world <-> frame) to Agience. Build on Agience without copyleft
reaching your code: the AGPL platform is reached over the wire, never linked, and no platform IP
lives here. Two toolkits in one package — a compute SDK that serves operators, and an MCP-server
SDK:

    from prism import Host           # build a Host (compute serving operators)
    from prism import create_server  # build an MCP server
    from prism import sign_service_jwt, verify_jwt  # stand on the trust floor

The full surfaces live under ``prism.host``, ``prism.server`` and ``prism.trust``; the most-used
names are re-exported here.

The contract — canonical JSON, the crystal model, the capability vocabulary, the config shape, the
error set, the structural address — is pure stdlib with no dependencies, and is imported eagerly
below. The runtime surfaces resolve through PEP 562 ``__getattr__``, so ``from prism import Host``
works and fails with a message naming the extra you need, while ``from prism.canonical import
canonical_string`` costs nothing.

    pip install agience-prism            # the contract. no dependencies.
    pip install agience-prism[trust]     # + jose, cryptography  - sign/verify
    pip install agience-prism[host]      # + fastapi, uvicorn    - serve operators
    pip install agience-prism[server]    # + mcp, httpx          - MCP server
    pip install agience-prism[wire]      # + numpy, cryptography - carry signals
    pip install agience-prism[all]

The wire lives here too: reach, plane, streams, carriers, frames, propagation, mcp_bridge, schema,
demurrage, minting, settlement, pump, minhash, error_threshold, extraction, conservation. The
members that need numpy or cryptography are covered by ``[wire]``; the other nine import on the bare
install.

The aperture is reached by injection (``prism.instrument``), never by import: a published SDK
depends only on packages its consumers can install.
"""
from __future__ import annotations

# ── The BLAS thread pin — must run before numpy is imported, or it is inert ──────────────────────
# `prism.vector` calls `numpy.linalg.norm`, and OpenBLAS sizes its worker pool when the library
# loads under `import numpy`, so setting the variable afterwards does nothing (unset -> 8 threads,
# set-before -> 1, set-after -> 8, read back through `threadpoolctl`). Python initialises parent
# packages before submodules, so this line runs before `prism.vector`'s numpy import and covers it.
# `os` is stdlib, so the zero-dependency contract above is untouched.
#
# Why 1: two threads in `numpy.linalg.eigh` fault this box's OpenBLAS on 3 runs of 3 (exit 139) and
# can hang instead of faulting, so one green run proves little; pinned, 0 of 3. `norm` is a level-1
# call and not itself the observed fault, but the pin is applied per-package rather than per-routine
# on purpose: a hand-maintained list of "which LAPACK entry points are safe enough" is exactly the
# typed-in knowledge that goes stale silently.
#
# `setdefault` leaves an operator's exported value in place, including one that reinstates the
# fault, and the pin reaches only processes that import prism before numpy.
import os as _os

_os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
del _os

from typing import Any

# ── The contract — pure stdlib, always importable ───────────────────────────────────────────────
from .environment import Capability, Prism, PRISM_CONTENT_TYPE
from .errors import (
    AuthError,
    PrismError,
    CapabilityNotFound,
    EntitlementError,
    HostUnavailable,
    ProtocolError,
    http_status_for,
    install_error_handlers,
)

__version__ = "0.1.1"

#: attribute -> (submodule, extra that provides it). Resolved on first access, then cached.
_LAZY: dict[str, tuple[str, str]] = {
    "trust": ("trust", "trust"),
    "host": ("host", "host"),
    "server": ("server", "server"),
    "Host": ("host", "host"),
    "TokenVerifier": ("host", "host"),
    "Server": ("server", "server"),
    "create_server": ("server", "server"),
    "SERVICE_NAMES": ("trust", "trust"),
    "ServiceIdentity": ("trust", "trust"),
    "get_authority_manifest": ("trust", "trust"),
    "get_host_id": ("trust", "trust"),
    "get_service_identity": ("trust", "trust"),
    "init_service_identity": ("trust", "trust"),
    "sign_delegation_jwt": ("trust", "trust"),
    "sign_service_jwt": ("trust", "trust"),
    "verify_delegation_jwt": ("trust", "trust"),
    "verify_jwt": ("trust", "trust"),
}


def __getattr__(name: str) -> Any:
    """Resolve a runtime surface on first use (PEP 562).

    An unknown name raises AttributeError. A name whose submodule needs an uninstalled extra raises
    ImportError naming the extra to install, so the traceback reads as an instruction."""
    try:
        submodule, extra = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    import importlib

    try:
        mod = importlib.import_module(f".{submodule}", __name__)
    except ImportError as exc:
        raise ImportError(
            f"`prism.{name}` needs the '{extra}' extra, which is not installed ({exc}). "
            f"Install it with: pip install agience-prism[{extra}]  — the base install is the "
            f"contract only (canonical JSON, the crystal model, the capability vocabulary, config, "
            f"errors, the structural address) and has no dependencies."
        ) from exc

    value = mod if name == submodule else getattr(mod, name)
    globals()[name] = value          # cache: the lookup happens once per process
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY))


__all__ = [
    "Host",
    "TokenVerifier",
    "Server",
    "create_server",
    # the prism environment + its capabilities (the light an organon needs)
    "Prism",
    "Capability",
    "PRISM_CONTENT_TYPE",
    # typed error set (§10)
    "PrismError",
    "AuthError",
    "EntitlementError",
    "CapabilityNotFound",
    "HostUnavailable",
    "ProtocolError",
    "http_status_for",
    "install_error_handlers",
    # trust floor (prism.trust)
    "trust",
    "SERVICE_NAMES",
    "ServiceIdentity",
    "get_authority_manifest",
    "get_host_id",
    "get_service_identity",
    "init_service_identity",
    "sign_delegation_jwt",
    "sign_service_jwt",
    "verify_delegation_jwt",
    "verify_jwt",
    "__version__",
]
