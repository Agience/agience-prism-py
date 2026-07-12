"""Canonical configuration (Bridge Protocol §4 + Appendix).

A bridge reads **only** canonical platform variable names and MUST NOT invent
aliases (`*_API_URI`, `BACKEND_URI`, …):

    ORIGIN_URI   identity / auth authority
    MANTLE_URI   artifact store + capability routing
    CHORUS_URI   host / persona discovery (`.well-known/mcp`)
    KEYS_DIR     host signing / identity keys (signing hosts only)

For a transition window the former SDK name ``AGIENCE_API_URI`` is still honored
as an alias for ``MANTLE_URI`` (where artifacts, routing, and registration
lived), but its use emits a :class:`DeprecationWarning` and a one-time log line.

Values resolve **lazily** — per call, not at import — so tests and runtime env
changes take effect, and the deprecation fires only when a legacy name is
actually read.
"""
from __future__ import annotations

import logging
import os
import warnings
from typing import Optional

log = logging.getLogger("agience_bridge.config")

# canonical name -> ordered legacy aliases (first present wins; use warns).
_ALIASES: dict[str, tuple[str, ...]] = {
    "ORIGIN_URI": (),
    "MANTLE_URI": ("AGIENCE_API_URI",),
    "CHORUS_URI": (),
    "KEYS_DIR": (),
}

# dev-friendly localhost defaults, matching agience-core's port assignments.
_DEFAULTS: dict[str, str] = {
    "ORIGIN_URI": "http://localhost:8080",
    "MANTLE_URI": "http://localhost:8081",
    "CHORUS_URI": "http://localhost:8082",
}

# emit each alias deprecation only once per process to avoid log spam.
_warned: set[str] = set()


def resolve(name: str, *, default: Optional[str] = None) -> Optional[str]:
    """Resolve a canonical config name.

    Order: the canonical env var, then any honored legacy alias (with a
    deprecation warning), then the explicit ``default``, then the built-in
    localhost default. Returns ``None`` if nothing is set and there is no
    default.
    """
    val = os.getenv(name)
    if val:
        return val
    for alias in _ALIASES.get(name, ()):
        aliased = os.getenv(alias)
        if aliased:
            if alias not in _warned:
                _warned.add(alias)
                warnings.warn(
                    f"{alias} is deprecated; set {name} instead "
                    "(Bridge Protocol §4 — canonical config names).",
                    DeprecationWarning,
                    stacklevel=2,
                )
                log.warning("%s is deprecated; use %s instead", alias, name)
            return aliased
    if default is not None:
        return default
    return _DEFAULTS.get(name)


def origin_uri(default: Optional[str] = None) -> str:
    """Origin (identity / auth authority) base URI, trailing slash stripped."""
    return (resolve("ORIGIN_URI", default=default) or "").rstrip("/")


def mantle_uri(default: Optional[str] = None) -> str:
    """Mantle (artifact store + routing) base URI, trailing slash stripped."""
    return (resolve("MANTLE_URI", default=default) or "").rstrip("/")


def chorus_uri(default: Optional[str] = None) -> str:
    """Chorus (host/persona discovery) base URI, trailing slash stripped."""
    return (resolve("CHORUS_URI", default=default) or "").rstrip("/")


def keys_dir(default: Optional[str] = None) -> Optional[str]:
    """Directory holding host signing/identity keys and the authority manifest,
    or ``None`` when unset (a verify-only host needs no keys)."""
    val = resolve("KEYS_DIR", default=default)
    return val or None


def authority_manifest_path(default: Optional[str] = None) -> Optional[str]:
    """Default authority-manifest path: ``$KEYS_DIR/authority.manifest.json`` when
    ``KEYS_DIR`` is set **and the file exists**, else ``default``. The manifest
    maps each trust anchor (origin / mantle / chorus) to its published JWKS (§5.2).

    The existence check is deliberate: a host may set ``KEYS_DIR`` only to sign,
    with no manifest present. Returning the path unconditionally would flip such
    a host into JWT-enforcing mode with an empty keyset and reject every token.
    """
    kd = keys_dir()
    if kd:
        candidate = os.path.join(kd, "authority.manifest.json")
        if os.path.isfile(candidate):
            return candidate
    return default


__all__ = [
    "resolve",
    "origin_uri",
    "mantle_uri",
    "chorus_uri",
    "keys_dir",
    "authority_manifest_path",
]
