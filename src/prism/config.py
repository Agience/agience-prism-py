"""Canonical configuration (Prism Protocol §4 + Appendix).

The vocabulary is closed: a server reads the canonical platform variable names,
and names outside this table (`*_API_URI`, `BACKEND_URI`, …) carry no meaning.

    ORIGIN_URI   identity / auth authority
    MANTLE_URI   artifact store + capability routing
    CRYSTAL_URI  content-type gateway (artifact operation dispatch)
    CHORUS_URI   host / persona discovery (`.well-known/mcp`)
    EMBER_URI    the local leaf -- host self-registration
    KEYS_DIR     host signing / identity keys (signing hosts only)

``EMBER_URI`` joined this table on 2026-08-26, and adding a sixth name to a
deliberately closed vocabulary needs its reason recorded. Host self-registration
(``POST /hosts/register``) was addressed to ``MANTLE_URI`` by all three SDKs, and
mantle serves no such route -- 0 of 66 mounted, measured 2026-08-26 -- while the
receiver has been on the ember leaf (``ember/surface/serve.py``) since 2026-07-21.
Every host therefore posted into a 404 on every start and announced nothing. The
leaf is the right owner: it holds the store the registration writes to and the
``EMBER_INVOKE_TOKEN`` gate that protects it, so the alternative was a second
receiver on mantle duplicating both.

``AGIENCE_API_URI`` is honored as a deprecated alias for ``MANTLE_URI``; reading
it emits a :class:`DeprecationWarning` and a one-time log line.

Values resolve **lazily** — per call, not at import — so tests and runtime env
changes take effect, and the deprecation fires only when a legacy name is
actually read.
"""
from __future__ import annotations

import logging
import os
import warnings
from typing import Optional

log = logging.getLogger("prism.config")

# canonical name -> ordered legacy aliases (first present wins; use warns).
_ALIASES: dict[str, tuple[str, ...]] = {
    "ORIGIN_URI": (),
    "MANTLE_URI": ("AGIENCE_API_URI",),
    "CRYSTAL_URI": (),
    "CHORUS_URI": (),
    "EMBER_URI": (),
    "KEYS_DIR": (),
}

# dev-friendly localhost defaults, matching the platform's local port assignments.
_DEFAULTS: dict[str, str] = {
    "ORIGIN_URI": "http://localhost:8080",
    "MANTLE_URI": "http://localhost:8081",
    "CRYSTAL_URI": "http://localhost:8085",
    "CHORUS_URI": "http://localhost:8082",
    # ember's surface binds 127.0.0.1:8091 by default (`serve_openai`), and the leaf is
    # by nature same-box. A caller that must not fabricate a target passes `default=""`
    # explicitly -- which is what host registration does, to stay strictly opt-in.
    "EMBER_URI": "http://localhost:8091",
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
                    "(Prism Protocol §4 — canonical config names).",
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


def crystal_uri(default: Optional[str] = None) -> str:
    """Crystal (content-type gateway — artifact op dispatch) base URI, slash stripped."""
    return (resolve("CRYSTAL_URI", default=default) or "").rstrip("/")


def chorus_uri(default: Optional[str] = None) -> str:
    """Chorus (host/persona discovery) base URI, trailing slash stripped."""
    return (resolve("CHORUS_URI", default=default) or "").rstrip("/")


def ember_uri(default: Optional[str] = None) -> str:
    """Ember (the local leaf -- host self-registration) base URI, slash stripped."""
    return (resolve("EMBER_URI", default=default) or "").rstrip("/")


def keys_dir(default: Optional[str] = None) -> Optional[str]:
    """Directory holding host signing/identity keys and the authority manifest,
    or ``None`` when unset (a verify-only host needs no keys)."""
    val = resolve("KEYS_DIR", default=default)
    return val or None


def authority_manifest_path(default: Optional[str] = None) -> Optional[str]:
    """Default authority-manifest path: ``$KEYS_DIR/authority.manifest.json`` when
    ``KEYS_DIR`` is set **and the file exists**, else ``default``. The manifest
    maps each trust anchor (origin / mantle / chorus) to its published JWKS (§5.2).

    The existence check is what makes signing-only hosts work: a host may set
    ``KEYS_DIR`` purely to sign, with no manifest present. Returning the path
    unconditionally would put such a host into JWT-enforcing mode with an empty
    keyset, where every token fails to verify.
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
    "crystal_uri",
    "chorus_uri",
    "keys_dir",
    "authority_manifest_path",
]
