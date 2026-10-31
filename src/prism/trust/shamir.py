"""Shamir secret sharing over GF(256): split a secret into n shares, any k of which reconstruct it.

Fewer than k shares reveal nothing about the secret, and any k recover it, so a key split k-of-n has
no single custodian and survives the loss of n-k of them. Each secret byte is shared independently;
a share is `(x, y-bytes)`. Standard library only, so every component holds the same arithmetic:
Origin's key oracle (`origin.services.shamir` re-exports this module) and Mantle's threshold
master-key store both split and combine with it.

    shares = split(secret_bytes, k=2, n=3)     # -> [(1, b'..'), (2, b'..'), (3, b'..')]
    secret = combine(shares[:2])               # any k of the n shares reconstruct it

`combine` does not know k: a share carries no threshold, so interpolating fewer than k shares, or
shares of two different secrets, returns wrong bytes rather than raising. A caller that must know it
got the right secret back checks it against something bound to the secret (Mantle stores a key-check
value beside its share for this).
"""
from __future__ import annotations

import secrets
from typing import List, Tuple

Share = Tuple[int, bytes]

# --- GF(256) log/exp tables (AES field 0x11b, generator 3) ---
_EXP = [0] * 255
_LOG = [0] * 256
_a = 1
for _i in range(255):
    _EXP[_i] = _a
    _LOG[_a] = _i
    _a2 = (_a << 1) ^ (0x11B if _a & 0x80 else 0)   # a*2 mod poly
    _a = _a ^ _a2                                     # a*3 = a*2 ^ a  (3 generates GF(256)*)


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[(_LOG[a] + _LOG[b]) % 255]


def _div(a: int, b: int) -> int:
    if a == 0:
        return 0
    if b == 0:
        raise ZeroDivisionError
    return _EXP[(_LOG[a] - _LOG[b]) % 255]


def _eval(coeffs: List[int], x: int) -> int:
    """Evaluate the polynomial (Horner) at x in GF(256). coeffs[0] is the secret (constant term)."""
    y = 0
    for c in reversed(coeffs):
        y = _mul(y, x) ^ c
    return y


def split(secret: bytes, *, k: int, n: int) -> List[Share]:
    """Split `secret` into `n` shares, any `k` of which reconstruct it. Requires 2 <= k <= n <= 255."""
    if not (2 <= k <= n <= 255):
        raise ValueError("require 2 <= k <= n <= 255")
    xs = list(range(1, n + 1))                         # share x-coords (never 0 = the secret)
    shares_y: List[bytearray] = [bytearray() for _ in xs]
    for byte in secret:
        coeffs = [byte] + [secrets.randbelow(256) for _ in range(k - 1)]   # random degree k-1 poly
        for i, x in enumerate(xs):
            shares_y[i].append(_eval(coeffs, x))
    return [(x, bytes(y)) for x, y in zip(xs, shares_y)]


def combine(shares: List[Share]) -> bytes:
    """Reconstruct the secret from >= k shares (Lagrange interpolation at x=0)."""
    if len(shares) < 2:
        raise ValueError("need at least 2 shares")
    xs = [x for x, _ in shares]
    if any(not isinstance(x, int) or isinstance(x, bool) or not 1 <= x <= 255 for x in xs):
        raise ValueError("share x-coordinates must be integers in 1..255")
    if len(set(xs)) != len(xs):
        raise ValueError("duplicate share x-coordinates")
    length = len(shares[0][1])
    if any(len(y) != length for _, y in shares):
        raise ValueError("shares differ in length")
    out = bytearray()
    for pos in range(length):
        secret_byte = 0
        for i, (xi, yi) in enumerate(shares):
            # Lagrange basis L_i(0)
            num, den = 1, 1
            for j, (xj, _) in enumerate(shares):
                if i == j:
                    continue
                num = _mul(num, xj)          # (0 - xj) = xj in GF(256)
                den = _mul(den, xi ^ xj)     # (xi - xj)
            secret_byte ^= _mul(yi[pos], _div(num, den))
        out.append(secret_byte)
    return bytes(out)
