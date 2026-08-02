"""agience-prism-py — an environment adapter: the Agience developer SDK for Python (Apache-2.0).

Prism adapts an environment (world <-> frame) to Agience.
Build on Agience without copyleft reaching your code: the AGPL platform is reached
over the wire, never linked. No platform IP lives here. Two toolkits in one package
(the former `agience-host` compute SDK + the original `agience-prism-py` MCP-server SDK,
consolidated):

    from prism import Host           # build a Host (compute serving operators)
    from prism import create_server  # build an MCP server
    from prism import sign_service_jwt, verify_jwt  # stand on the trust floor

The full surfaces live under ``prism.host``, ``prism.server``, and
``prism.trust``; the most-used names are re-exported here.

⚠ THE CONTRACT IS EAGER; THE RUNTIME SURFACES ARE LAZY. THAT IS AN INSTALL CONTRACT, NOT A STYLE
CHOICE (2026-07-30).

`import prism` used to pull `.trust`, `.host` and `.server` at module scope, so it required
python-jose, cryptography, fastapi, uvicorn, httpx and mcp — six packages — before you could read a
single constant. That weight is why `agience-beam` refused to depend on this package and VENDORED a
byte-identical copy of `canonical.py` instead, with `agience-bundle` doing the same for its bare
installer: three copies of the code that decides every content address and every signature, kept in
step by a gate, because the SDK was too heavy to import.

The split removes the cause. The CONTRACT — canonical JSON, the crystal model, the capability
vocabulary, the config shape, the error set, the structural address — is **pure stdlib with zero
dependencies** and is imported eagerly below. The runtime surfaces resolve through PEP 562
`__getattr__`, so `from prism import Host` still works and now fails with a message naming the extra
you need, while `from prism.canonical import canonical_string` costs nothing.

    pip install agience-prism            # the contract. no dependencies.
    pip install agience-prism[trust]     # + jose, cryptography  — sign/verify
    pip install agience-prism[host]      # + fastapi, uvicorn    — serve operators
    pip install agience-prism[server]    # + mcp, httpx          — MCP server
    pip install agience-prism[all]

⚠ DO NOT ADD AN EAGER IMPORT OF host/server/trust HERE. `agience-beam` imports `prism.canonical`
directly now, and importing a submodule runs THIS file first — so one eager import would put fastapi
on the fiber's install path and the vendored copy deleted to get here would have to come back.
`agience-prism/py/tests/test_contract_install_is_pure.py` fails if it does.
"""
from __future__ import annotations

from typing import Any

# ── THE CONTRACT — pure stdlib, always importable ───────────────────────────────────────────────
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

__version__ = "0.1.0"

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

    ⚠ THE ERROR MESSAGE IS HALF THE VALUE. Without this wrapper, `prism.Host` on a contract-only
    install raises `ModuleNotFoundError: No module named 'fastapi'` — naming a package the caller
    never asked for and saying nothing about what to do. Re-raising with the extra named turns a
    confusing traceback into an instruction."""
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
            f"CONTRACT only (canonical JSON, the crystal model, the capability vocabulary, config, "
            f"errors, the structural address) and deliberately has no dependencies."
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
