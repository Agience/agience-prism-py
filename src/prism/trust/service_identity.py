"""Per-service identity and signing.

Each service (origin, mantle, chorus) holds its own RSA private key in `KEYS_DIR`.
This module loads it once at startup and exposes the API for signing service-to-service
JWTs. Verification of peer-service JWTs lives in `origin.authority_trust`.

Key files (written by the init container):
  KEYS_DIR/origin.private.pem    only origin reads this
  KEYS_DIR/mantle.private.pem     only mantle reads this
  KEYS_DIR/chorus.private.pem    only chorus reads this

Service identity contract:
  - `iss` claim equals the service name ("origin", "mantle", or "chorus")
  - `kid` claim equals "{service}-1" (matches authority manifest's JWK kid)
  - `aud` claim names the recipient service ("mantle", "chorus", "origin")
  - `principal_type` claim distinguishes payload kinds:
      - "service"      service-to-service call, no user
      - "delegation"   mantle proxying a user request to chorus (carries `act.sub`)
"""
from __future__ import annotations

import logging
import time
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import serialization
import os

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from jose import jwt as jose_jwt

logger = logging.getLogger(__name__)

# Service names recognized by the authority manifest. New services would extend this.
# `crystal` is the content-type gateway (agience-crystal): a platform service so it can
# subscribe to Mantle's change-feed as a system consumer and mint delegations for
# event-driven describers.
SERVICE_NAMES = ("origin", "mantle", "chorus", "crystal", "lumen")

# Default service-to-service JWT TTL (seconds). Short — these tokens are issued
# fresh per call. Override per-call if a longer TTL is genuinely needed.
DEFAULT_TTL_SECONDS = 300

# Delegation tokens (RFC 8693) carry user_id in `sub` and the actor in `act.sub`.
# Same TTL — delegation is per-request.
DEFAULT_DELEGATION_TTL_SECONDS = 300

# The current-instance host artifact (seeded as `agience/agience-host-current-instance`).
# Its id is the `host_id` claim required on every delegation — the Host in the
# Authority/Host/Server/User identity chain. The id is derived deterministically
# as uuid5(instance_namespace, "agience/agience-host-current-instance"), matching
# the seed loader, so any service can compute it from the shared instance.uuid.
_HOST_SEED_NAMESPACE = "agience"
_HOST_SEED_SLUG = "agience-host-current-instance"

# The platform system principal — a low-privilege identity that platform
# automation (webhooks, background sends) acts AS. Its authority roots to the
# operator (the platform_email provisioner issues its grants `granted_by` the
# operator), so it satisfies "a service principal is OK if rooted to a person".
# Deterministic per-install id so Origin (mints the delegation subject) and Mantle
# (issues the grants to this grantee) agree without a shared DB.
_SYSTEM_PRINCIPAL_SEED_NAMESPACE = "platform"
_SYSTEM_PRINCIPAL_SEED_SLUG = "platform-system-principal"


@dataclass(frozen=True)
class ServiceIdentity:
    """The loaded private key + identity metadata for the running service."""
    name: str
    kid: str
    private_key: RSAPrivateKey


_loaded: Optional[ServiceIdentity] = None


def _keys_dir() -> Path:
    """Resolve the keys directory, reading KEYS_DIR env at call time so tests can monkeypatch it."""
    return Path(os.getenv("KEYS_DIR") or "/data/keys")


def get_instance_namespace() -> Optional[_uuid.UUID]:
    """Per-install UUID namespace, read from the shared ``KEYS_DIR/instance.uuid``.

    Read-only: the init container / seed loader mints it on first boot. All
    services mount the same ``KEYS_DIR``, so this is a stable cross-service value.
    Returns ``None`` if the file is absent or unreadable (caller decides how to
    degrade)."""
    path = _keys_dir() / "instance.uuid"
    try:
        return _uuid.UUID(path.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def get_host_id() -> str:
    """Return the current-instance host artifact id — the ``host_id`` claim that
    must ride on every delegation (the Host in the Authority/Host/Server/User
    chain Mantle enforces).

    Derived as ``uuid5(instance_namespace, "agience/agience-host-current-instance")``
    to match the seed loader, so it equals the host artifact's actual id without a
    DB lookup. Returns ``""`` when the instance namespace can't be resolved."""
    ns = get_instance_namespace()
    if ns is None:
        return ""
    return str(_uuid.uuid5(ns, f"{_HOST_SEED_NAMESPACE}/{_HOST_SEED_SLUG}"))


def get_system_principal_id() -> str:
    """Return the platform system principal id — the low-privilege identity that
    platform automation acts AS (e.g. webhook-driven receipt/warning sends). Its
    authority roots to the operator via the grants the platform_email provisioner
    issues to it. Derived deterministically from the shared instance namespace so
    Origin and Mantle agree. Returns ``""`` when the namespace can't be resolved."""
    ns = get_instance_namespace()
    if ns is None:
        return ""
    return str(_uuid.uuid5(ns, f"{_SYSTEM_PRINCIPAL_SEED_NAMESPACE}/{_SYSTEM_PRINCIPAL_SEED_SLUG}"))


def init_service_identity(service_name: str) -> ServiceIdentity:
    """Load the running service's private key from disk. Idempotent.

    Call once at lifespan startup. After this returns, `get_service_identity()`
    is available process-wide.

    Raises FileNotFoundError if the expected `{service_name}.private.pem` is absent —
    services must fail fast at boot if their identity is missing.
    """
    global _loaded
    if _loaded is not None and _loaded.name == service_name:
        return _loaded

    if service_name not in SERVICE_NAMES:
        raise ValueError(f"Unknown service name {service_name!r}; expected one of {SERVICE_NAMES}")

    priv_path = _keys_dir() / f"{service_name}.private.pem"
    if not priv_path.is_file():
        raise FileNotFoundError(
            f"Service private key missing at {priv_path}. "
            f"The init container generates these on first boot — re-run init or check the volume mount."
        )

    pem = priv_path.read_bytes()
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise TypeError(f"{priv_path} is not an RSA private key")

    identity = ServiceIdentity(name=service_name, kid=f"{service_name}-1", private_key=key)
    _loaded = identity
    logger.info("Service identity loaded: name=%s kid=%s", identity.name, identity.kid)
    return identity


def get_service_identity() -> ServiceIdentity:
    """Return the loaded service identity. Raises if `init_service_identity` was not called."""
    if _loaded is None:
        raise RuntimeError(
            "Service identity not initialized — call init_service_identity(service_name) at lifespan startup."
        )
    return _loaded


def reset_service_identity_for_tests() -> None:
    """Test-only hook to clear the module-level identity between cases."""
    global _loaded
    _loaded = None


def sign_service_jwt(
    *,
    audience: str,
    additional_claims: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    issuer_override: Optional[str] = None,
) -> str:
    """Sign a service-to-service JWT with the running service's private key.

    Default claims:
        iss = service name
        sub = service name        (service-to-service is self-as-subject)
        aud = audience
        principal_type = "service"
        iat = now
        exp = now + ttl_seconds
        kid in header

    Pass additional_claims to add fields (e.g. scopes, request_id). Existing
    keys win — additional_claims cannot override the default claims above.

    `issuer_override` is for narrow cases where the service speaks on behalf of a
    different identity (rare; only used during bootstrap-token claim where Origin
    speaks as itself but binds to the deployment's authority issuer). Otherwise
    use the default.
    """
    identity = get_service_identity()
    now = int(time.time())
    iss = issuer_override or identity.name
    claims: Dict[str, Any] = {
        "iss": iss,
        "sub": identity.name,
        "aud": audience,
        "principal_type": "service",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if additional_claims:
        for k, v in additional_claims.items():
            claims.setdefault(k, v)

    pem = identity.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": identity.kid})


def sign_delegation_jwt(
    *,
    audience: str,
    user_sub: str,
    host_id: Optional[str] = None,
    additional_claims: Optional[Dict[str, Any]] = None,
    ttl_seconds: int = DEFAULT_DELEGATION_TTL_SECONDS,
) -> str:
    """Sign an RFC 8693 delegation JWT carrying the full identity chain.

    Every action carries Authority/Host/Server/User: `iss` (authority — the
    signing service), `host_id` (host — the current instance), `act.sub` (server
    — the actor performing the delegation), `sub` (user). Mantle's auth REQUIRES
    all of these on a delegation, so `host_id` is stamped by default (resolved via
    `get_host_id()`); pass `host_id` to override.

    Used by Mantle when proxying a user request to Chorus. Chorus persona handlers
    verify `aud` (their client_id) and `act.sub` (the issuer's name); when a
    persona forwards this delegation back to Mantle, Mantle checks the full chain.
    """
    identity = get_service_identity()
    now = int(time.time())
    claims: Dict[str, Any] = {
        "iss": identity.name,
        "sub": user_sub,
        "aud": audience,
        "act": {"sub": identity.name},
        "host_id": host_id if host_id is not None else get_host_id(),
        "principal_type": "delegation",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if additional_claims:
        for k, v in additional_claims.items():
            claims.setdefault(k, v)

    pem = identity.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": identity.kid})
