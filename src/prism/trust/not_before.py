"""Origin's sign-in bounds, as every peer honours them (review 11, M2).

Origin ends a person's tokens at sign-out (and everyone's at a signing-key rollover) by recording a
"not before" time: a token whose `iat` is earlier is no longer good. Origin refuses such tokens at
its own routes; the peers that verify Origin's tokens themselves (Mantle, Crystal, Chorus and its
personas, Ember) must refuse them too, or a stolen token outlives the sign-out everywhere but at
Origin.

Origin publishes the bounds at `GET {ORIGIN}/auth/not-before?after=<seq>`: a JWT signed by its
current key, `{"iss", "iat", "seq", "entries": [{"seq", "sub", "not_before"}], "all_before"}`,
read by Origin's own monotonic sequence so a row committed late is never skipped (review 12, M8).
A `NotBefore` polls it (every `POLL_SECONDS`), verifies the signature and issuer against the
authority manifest's Origin anchor, keeps each person's latest bound, and writes the bounds to its
own state file (`NOT_BEFORE_STATE`, else `$KEYS_DIR/not_before.json`) so a restart forgets none.

It fails closed: after a start it refuses every token until its first good poll, and again once its
last good poll is older than `STALE_SECONDS`. A token with no `iat` is refused. A node with no Origin
configured has no bounds to enforce. An answer whose signature does not verify is ignored, logged,
and does not count as a good poll. So is a verified one that is not current (review 14): one with
no `iat`, one issued more than `STALE_SECONDS` ago or ahead of the clock beyond `SKEW_SECONDS`, and
one older than the last document accepted (kept in the state file too), so a captured document
replayed later keeps no poller fresh.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional

log = logging.getLogger(__name__)

POLL_SECONDS = float(os.getenv("AGIENCE_NOT_BEFORE_POLL_SECONDS", "15"))
#: A poller whose last good poll is older than this refuses every token (review 12, M8).
STALE_SECONDS = float(os.getenv("AGIENCE_NOT_BEFORE_STALE_SECONDS", "120"))
#: How far ahead of this clock a bounds document's `iat` may be.
SKEW_SECONDS = float(os.getenv("AGIENCE_NOT_BEFORE_SKEW_SECONDS", "30"))
_MAX_ANSWER = 4 * 1024 * 1024


def _verify(token: str) -> dict:
    """Origin's signature on the bounds, and its issuer, checked against the manifest."""
    from .authority_trust import verify_origin_jwt
    return verify_origin_jwt(token)


def _default_state_path() -> Optional[str]:
    explicit = (os.getenv("NOT_BEFORE_STATE") or "").strip()
    if explicit:
        return explicit
    keys = (os.getenv("KEYS_DIR") or "").strip()
    return os.path.join(keys, "not_before.json") if keys else None


def _test_mode() -> bool:
    """Polling switched off for a test run: honoured only while pytest is loaded, so a setting
    left in a deployed env never turns fail-closed off."""
    import sys
    return bool(os.getenv("AGIENCE_NOT_BEFORE_NO_POLL")) and "pytest" in sys.modules


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as r:            # noqa: S310 — Origin's own URI
        raw = r.read(_MAX_ANSWER + 1)
    if len(raw) > _MAX_ANSWER:
        raise ValueError("not-before answer too large")
    body = raw.decode("utf-8").strip()
    if body.startswith("{"):
        body = str(json.loads(body).get("token") or "")
    return body


class NotBefore:
    """A person's latest sign-in bound, and everyone's, as Origin last published them."""

    def __init__(self, origin_uri: str, *, fetch: Optional[Callable[[str], str]] = None,
                 verify: Optional[Callable[[str], dict]] = None,
                 state_path: Optional[str] = None):
        self._origin = (origin_uri or "").rstrip("/")
        self._fetch = fetch or _fetch
        self._verify = verify or _verify
        self._by_sub: Dict[str, float] = {}
        self._all: Optional[float] = None
        self._seq = 0
        #: The `iat` of the last bounds document accepted.
        self._last_iat = 0.0
        #: `time.monotonic()` of the last good poll; None until the first since this start.
        self._last_good: Optional[float] = None
        self._state_path = state_path if state_path is not None else _default_state_path()
        self._lock = threading.Lock()
        self._load()
        self._listeners: List[Callable[[Optional[str]], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def on_change(self, fn: Callable[[Optional[str]], None]) -> None:
        """`fn(sub)` is called when a person's bound moves (`sub` None for everyone's)."""
        self._listeners.append(fn)

    def _load(self) -> None:
        if not self._state_path:
            return
        try:
            with open(self._state_path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            return
        self._by_sub = {str(k): float(v) for k, v in (state.get("by_sub") or {}).items()
                        if isinstance(v, (int, float))}
        ab = state.get("all_before")
        self._all = float(ab) if isinstance(ab, (int, float)) else None
        self._seq = int(state.get("seq") or 0)
        li = state.get("last_iat")
        self._last_iat = float(li) if isinstance(li, (int, float)) else 0.0

    def _save(self) -> None:
        if not self._state_path:
            return
        tmp = self._state_path + ".next"
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"by_sub": self._by_sub, "all_before": self._all, "seq": self._seq,
                           "last_iat": self._last_iat}, f)
            os.replace(tmp, self._state_path)
        except OSError:
            log.warning("the sign-in bounds could not be written to %s", self._state_path,
                        exc_info=True)

    def apply(self, claims: dict) -> List[Optional[str]]:
        """Take a verified bounds document; returns whose bounds moved."""
        moved: List[Optional[str]] = []
        with self._lock:
            for e in claims.get("entries") or ():
                sub, nb = str(e.get("sub") or ""), e.get("not_before")
                if not sub or not isinstance(nb, (int, float)):
                    continue
                if nb > self._by_sub.get(sub, 0.0):
                    self._by_sub[sub] = float(nb)
                    moved.append(sub)
                if isinstance(e.get("seq"), int):
                    self._seq = max(self._seq, int(e["seq"]))
            ab = claims.get("all_before")
            if isinstance(ab, (int, float)) and ab and (self._all is None or ab > self._all):
                self._all = float(ab)
                moved.append(None)
            if isinstance(claims.get("seq"), int):
                self._seq = max(self._seq, int(claims["seq"]))
            self._last_good = time.monotonic()
            self._save()
        for who in moved:
            for fn in self._listeners:
                try:
                    fn(who)
                except Exception:                                 # noqa: BLE001
                    log.warning("a not-before listener failed", exc_info=True)
        return moved

    def poll_once(self) -> List[Optional[str]]:
        if not self._origin:
            return []
        url = f"{self._origin}/auth/not-before?" + urllib.parse.urlencode({"after": self._seq})
        try:
            token = self._fetch(url)
        except Exception as exc:                                 # noqa: BLE001 — keep last known
            log.debug("Origin's sign-in bounds could not be read (%s)", type(exc).__name__)
            return []
        try:
            claims = self._verify(token)
        except Exception:                                        # noqa: BLE001
            log.warning("Origin's sign-in bounds did not verify; ignored")
            return []
        iat, now = claims.get("iat"), time.time()
        with self._lock:
            current = (isinstance(iat, (int, float)) and iat >= self._last_iat
                       and now - STALE_SECONDS <= iat <= now + SKEW_SECONDS)
            if current:
                self._last_iat = float(iat)
        if not current:
            log.warning("Origin's sign-in bounds are not current (iat %r, last accepted %r); "
                        "ignored", iat, self._last_iat)
            return []
        return self.apply(claims)

    def refused(self, claims: dict) -> bool:
        """Was this token issued before its person's bound, or everyone's? Also true for a token
        with no `iat`, and for every token while this poller has no fresh bounds."""
        iat = claims.get("iat")
        if not isinstance(iat, (int, float)):
            return True
        if not self._origin or _test_mode():
            pass                                  # no Origin: nothing to enforce
        elif self._last_good is None or time.monotonic() - self._last_good > STALE_SECONDS:
            return True                           # fail closed until a fresh poll
        sub = str(claims.get("sub") or "")
        with self._lock:
            if self._all is not None and iat < self._all:
                return True
            nb = self._by_sub.get(sub)
            return nb is not None and iat < nb

    def start(self) -> None:
        """Poll in a daemon thread, every `POLL_SECONDS`. Idempotent."""
        if self._thread is not None or not self._origin:
            return

        def run():
            while not self._stop.is_set():
                self.poll_once()
                self._stop.wait(POLL_SECONDS)

        self._thread = threading.Thread(target=run, name="origin-not-before", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


_shared: Optional[NotBefore] = None
_shared_lock = threading.Lock()


def shared(origin_uri: Optional[str] = None) -> NotBefore:
    """The process's one poller, started on first use when an Origin is configured."""
    global _shared
    with _shared_lock:
        if _shared is None:
            uri = origin_uri or os.getenv("ORIGIN_URI") or os.getenv("EMBER_ORIGIN_URI") or ""
            _shared = NotBefore(uri)
            if uri and not os.getenv("AGIENCE_NOT_BEFORE_NO_POLL"):
                _shared.start()
        return _shared


def refused(claims: dict) -> bool:
    """Whether Origin's published sign-in bounds end a token with these claims."""
    return shared().refused(claims)


def reset_for_tests() -> None:
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.stop()
        _shared = None
