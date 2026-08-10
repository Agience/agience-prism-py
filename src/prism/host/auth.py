"""Inbound credential verification for Agience hosts.

A host authorizes inbound calls with, in precedence order:

  1. **Authority JWT (primary).** An RS256 JWT signed by a member of the
     platform *authority* — Origin's authority manifest (origin / mantle /
     chorus). Trust is "the signing key, selected by ``kid``, is present in the
     authority's published JWKS." So a service that self-signs (e.g. Mantle:
     ``iss=mantle, aud=<host>``) verifies here, and an Origin-issued OAuth2
     token (``kid=origin-1, aud=agience``) verifies the same way — no special
     casing, no per-issuer code.

  2. **Local HS256 JWT (fallback).** A JWT signed with a shared secret held
     locally on the host. The standalone/dev path when no authority is
     reachable to issue or verify RS256 tokens.

  3. **Static API key (fallback).** A shared bearer from an allowlist
     (constant-time compare). Cross-authority / shared-host path.

Verifying keys come from a mounted authority-manifest file and/or a JWKS URL
(e.g. Origin's ``/.well-known/jwks.json``). No platform code is imported: the
manifest is plain public JSON and tokens are verified with PyJWT. A host with no
source configured is open, so configuring one is what closes it.
"""
from __future__ import annotations

import json
import logging
import os
import secrets as _secrets
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from ..errors import AuthError  # re-exported here: callers catch it from this module

log = logging.getLogger("agience.host.auth")


def _looks_like_jwt(token: str) -> bool:
    """A compact JWS is three non-empty base64url segments split by dots."""
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


class TokenVerifier:
    """Resolve and check inbound credentials. See module docstring for the model.

    Construct once and reuse; key material (manifest file, JWKS client) is
    cached and refreshed on a ``kid`` miss to tolerate key rotation.
    """

    def __init__(
        self,
        *,
        api_keys: Iterable[str] = (),
        api_keys_dir: Optional[str] = None,
        api_keys_dir_refresh_s: float = 5.0,
        authority_manifest_path: Optional[str] = None,
        authority_jwks_url: Optional[str] = None,
        hs256_secret: Optional[str] = None,
        expected_audiences: Iterable[str] = (),
        allowed_issuers: Iterable[str] = (),
        leeway: int = 60,
    ) -> None:
        self.api_keys = tuple(k for k in (api_keys or ()) if k)
        # Directory of key files (one key per non-blank, non-`#` line; one file per
        # consumer). Lives on a persistent volume, not in git/secrets;
        # add or remove a file to grant/revoke and it is picked up live (no
        # redeploy) within api_keys_dir_refresh_s. The filename is the label.
        self.api_keys_dir = (api_keys_dir or "").strip() or None
        self._dir_refresh_s = max(0.0, api_keys_dir_refresh_s)
        self._dir_keys: tuple[str, ...] = ()
        self._dir_sig: Any = None
        self._dir_checked_at: float = 0.0
        self.authority_manifest_path = (authority_manifest_path or "").strip() or None
        self.authority_jwks_url = (authority_jwks_url or "").strip() or None
        self.hs256_secret = (hs256_secret or "").strip() or None
        self.expected_audiences = tuple(a for a in (expected_audiences or ()) if a)
        self.allowed_issuers = tuple(i for i in (allowed_issuers or ()) if i)
        self.leeway = leeway
        self._manifest_keys: Optional[dict] = None
        self._jwk_client: Any = None

    # -- api keys (inline + hot-reloaded directory) -------------------------
    def _refresh_dir_keys(self) -> tuple[str, ...]:
        """Load keys from ``api_keys_dir``, re-reading only when it changes.

        Throttled to one filesystem scan per ``_dir_refresh_s``; a scan reloads
        only if the directory's signature (names + sizes + mtimes) changed, so
        adding/removing/editing a key file takes effect without a restart.
        """
        if not self.api_keys_dir:
            return ()
        now = time.monotonic()
        if self._dir_sig is not None and (now - self._dir_checked_at) < self._dir_refresh_s:
            return self._dir_keys
        self._dir_checked_at = now
        try:
            with os.scandir(self.api_keys_dir) as it:
                files = [e for e in it if e.is_file() and not e.name.startswith(".")]
            files.sort(key=lambda e: e.name)
            sig = tuple((e.name, st.st_size, st.st_mtime_ns) for e in files for st in (e.stat(),))
            if sig == self._dir_sig:
                return self._dir_keys
            keys: list[str] = []
            for e in files:
                try:
                    text = Path(e.path).read_text(encoding="utf-8")
                except OSError:
                    continue
                for line in text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        keys.append(line)
            self._dir_keys = tuple(keys)
            self._dir_sig = sig
            log.info("api-key dir %s: %d key(s) from %d file(s)",
                     self.api_keys_dir, len(self._dir_keys), len(files))
        except FileNotFoundError:
            self._dir_keys, self._dir_sig = (), ()
        except OSError:
            log.warning("api-key dir unreadable: %s", self.api_keys_dir, exc_info=True)
        return self._dir_keys

    def _all_api_keys(self) -> tuple[str, ...]:
        return self.api_keys + self._refresh_dir_keys()

    @property
    def jwt_enabled(self) -> bool:
        return bool(self.authority_manifest_path or self.authority_jwks_url or self.hs256_secret)

    @property
    def enabled(self) -> bool:
        """True when at least one credential is configured; a host with none is open.

        Enforcement follows the keys, not the directory: a configured-but-empty
        key directory leaves the host open until a key file is added, because
        with no inline keys and no JWT source there is nothing to check against.
        """
        return bool(self._all_api_keys()) or self.jwt_enabled

    def describe(self) -> str:
        """One-line summary of the configured modes (for startup logging)."""
        modes = []
        if self.authority_manifest_path or self.authority_jwks_url:
            modes.append("authority-jwt(RS256)")
        if self.hs256_secret:
            modes.append("local-jwt(HS256)")
        n_keys = len(self._all_api_keys())
        if n_keys or self.api_keys_dir:
            src = f"api-key x{n_keys}"
            if self.api_keys_dir:
                src += f" (dir {self.api_keys_dir})"
            modes.append(src)
        return ", ".join(modes) if modes else "open (no auth configured)"

    # -- key sources --------------------------------------------------------
    def _load_manifest_keys(self, *, force: bool = False) -> dict:
        """Map ``kid`` -> public key from every trust anchor in the manifest."""
        if self._manifest_keys is not None and not force:
            return self._manifest_keys
        keys: dict = {}
        path = self.authority_manifest_path
        if path and Path(path).is_file():
            try:
                import jwt as _jwt  # PyJWT

                raw = json.loads(Path(path).read_text(encoding="utf-8"))
                jwk_list: list = []
                for anchor in (raw.get("trust_anchors") or {}).values():
                    jwk_list.extend(((anchor or {}).get("jwks") or {}).get("keys") or [])
                if jwk_list:
                    for k in _jwt.PyJWKSet.from_dict({"keys": jwk_list}).keys:
                        if k.key_id:
                            keys[k.key_id] = k.key
            except Exception:
                log.warning("authority manifest parse failed: %s", path, exc_info=True)
        self._manifest_keys = keys
        return keys

    def _resolve_rs256_key(self, token: str):
        """Find the verifying key for ``token`` by ``kid`` (JWKS URL, then manifest)."""
        import jwt as _jwt

        if self.authority_jwks_url:
            try:
                if self._jwk_client is None:
                    self._jwk_client = _jwt.PyJWKClient(self.authority_jwks_url)
                return self._jwk_client.get_signing_key_from_jwt(token).key
            except Exception:
                pass  # fall through to the manifest file
        kid = _jwt.get_unverified_header(token).get("kid")
        if not kid:
            return None
        keys = self._load_manifest_keys()
        if kid in keys:
            return keys[kid]
        # Unknown kid — keys may have rotated; reload the manifest once.
        return self._load_manifest_keys(force=True).get(kid)

    # -- verify -------------------------------------------------------------
    def verify(self, authorization: Optional[str]) -> None:
        """Authorize a request from its ``Authorization`` header.

        Returns ``None`` when authorized; raises :class:`AuthError` otherwise.
        An unconfigured verifier authorizes everything (open host).
        """
        if not self.enabled:
            return
        presented = (authorization or "").strip()
        if presented[:7].lower() == "bearer ":
            presented = presented[7:].strip()
        if not presented:
            raise AuthError("missing bearer token")

        if self.jwt_enabled and _looks_like_jwt(presented):
            if self._verify_rs256(presented) or self._verify_hs256(presented):
                return
        if self._match_api_key(presented):
            return
        raise AuthError("invalid or missing credential")

    def _verify_claims_ok(self, claims: dict) -> bool:
        if self.allowed_issuers and claims.get("iss") not in self.allowed_issuers:
            return False
        return True

    def _verify_rs256(self, token: str) -> bool:
        if not (self.authority_manifest_path or self.authority_jwks_url):
            return False
        try:
            import jwt as _jwt

            key = self._resolve_rs256_key(token)
            if key is None:
                return False
            claims = _jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=list(self.expected_audiences) or None,
                options={"verify_aud": bool(self.expected_audiences)},
                leeway=self.leeway,
            )
            return self._verify_claims_ok(claims)
        except Exception:
            return False

    def _verify_hs256(self, token: str) -> bool:
        if not self.hs256_secret:
            return False
        try:
            import jwt as _jwt

            claims = _jwt.decode(
                token,
                self.hs256_secret,
                algorithms=["HS256"],
                audience=list(self.expected_audiences) or None,
                options={"verify_aud": bool(self.expected_audiences)},
                leeway=self.leeway,
            )
            return self._verify_claims_ok(claims)
        except Exception:
            return False

    def _match_api_key(self, presented: str) -> bool:
        """Constant-time compare against every configured key.
        Encoding both sides to bytes keeps the comparison constant-time and total."""
        try:
            presented_b = presented.encode("utf-8", "surrogatepass")
        except Exception:
            return False
        return any(_secrets.compare_digest(presented_b, k.encode("utf-8", "surrogatepass"))
                   for k in self._all_api_keys())


__all__ = ["TokenVerifier", "AuthError"]
