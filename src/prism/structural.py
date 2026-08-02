# PROTOTYPE — the structural content address ("structural permanence", John 2026-07-29).
# Not wired into anything yet. It exists so the decision in `NEXT.md §P.4` can be made against a
# working thing with measured properties instead of an argument.
"""Deterministic CBOR (RFC 8949 §4.2) — a content address over the STRUCTURE, not over a rendering.

WHY THIS EXISTS. A JSON-text content address forces three separate encoding agreements, and this
workspace was measured getting all three wrong on 2026-07-29: string escaping, number→text rendering,
and key collation. RFC 8785 fixes them by pinning all three to JavaScript's semantics — which means
every non-JS SDK must emulate JavaScript forever. John: *"we should not care about ascii or char
encoding. that is a content feature. We should be encoding agnostically."*

In a structural encoding those three questions do not exist:

  | JSON-text question              | structural answer                                        |
  |---------------------------------|----------------------------------------------------------|
  | escape non-ASCII?               | none — a text string is a LENGTH-PREFIXED UTF-8 byte run |
  | how does 1.0 render?            | none — integers and floats are DIFFERENT major types     |
  | sort keys by code point or unit?| none — keys sort by their ENCODED BYTES, one total order |

And the loss JCS forces disappears: `9007199254740993` stays EXACT, because a CBOR integer is not a
float64. Under JCS, Python had to round it to match JavaScript.

THE ONE NORMALIZATION THAT REMAINS, and it is unavoidable: **JavaScript cannot distinguish integer 1
from float 1.0** — both are `number`. So an integral value encodes as a CBOR INTEGER regardless of the
source language's type, and only a non-integral value encodes as a float. Without that rule Python's
`1.0` and JavaScript's `1` would address differently. It is one rule, stated once, with no per-character
or per-locale behaviour — which is the whole difference from the JSON-text situation.

⚠ HONEST LIMIT: JS `number` still cannot REPRESENT an integer beyond 2^53, so a JS host needs BigInt to
produce or verify such an address. The difference from JCS is that this becomes a TYPED, detectable
boundary rather than a silent rounding that two hosts disagree about.

WHAT THIS ENCODER REFUSES, and why refusing is the whole point (hardened 2026-07-29, Contract Builder).
The justification for going structural is that JCS silently gives two different artifacts ONE content
address. An encoder that does the same thing for its own edge cases reproduces the defect it was built
to remove, so every case below now RAISES `Unaddressable` instead of producing bytes:

  | input                        | was                                    | now |
  |------------------------------|----------------------------------------|-----|
  | `set`, `datetime`, any object | `str(obj)` — and `str(set)` order is   | RAISES |
  |                              | PYTHONHASHSEED-dependent, so the SAME  | |
  |                              | set addressed differently per process  | |
  | non-`str` dict key           | `str(k)` — so key `1.0` collided with  | RAISES |
  |                              | key `"1.0"`, and which value won       | |
  |                              | depended on INSERTION ORDER            | |
  | integer ≥ 2^64               | opaque `struct.error` in Python while  | exact, via |
  |                              | JS SILENTLY TRUNCATED to 64 bits — two | CBOR bignum |
  |                              | hosts disagreeing with nothing raised  | |

Measured before the fix: `{1.0: "x", "1.0": "y"}` and `{"1.0": "y", 1.0: "x"}` produced DIFFERENT
addresses and emitted a duplicate-key CBOR map (invalid under RFC 8949 §5.6 for deterministic
encoding). Keys are now **`str` only** — that is not a limitation but the actual domain: this addresses
JSON-shaped documents, a non-string key cannot exist in JSON or in a JS object, so such a document
could never be verified by another SDK anyway. Refusing names the boundary; coercing hid it.

Big integers are now genuinely UNBOUNDED and exact on both sides (CBOR bignum, RFC 8949 §3.4.3:
tag 2 positive / tag 3 negative, magnitude as a big-endian byte string with no leading zeros).
Deterministic form requires major type 0/1 whenever the value fits in 64 bits, and a bignum only
beyond — otherwise one value would have two encodings.

Stdlib-only, like `prism.canonical` — a bare host must be able to address content with no dependencies.
"""
from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, List

__all__ = ["structural_encode", "structural_sha", "STRUCTURAL_ALGO", "Unaddressable"]


class Unaddressable(TypeError):
    """This value has no well-defined content address, so no bytes are produced.

    A distinct type because the caller's correct response is to REFUSE the document, not to retry or
    to fall back — and a caller enumerating what it cannot address (a migration scan, say) needs to
    tell "unaddressable" apart from an ordinary bug. Subclasses `TypeError` so existing
    `except TypeError` handlers still catch it.
    """

#: The address algorithm tag. A content address MUST carry which algorithm produced it, so a
#: structural address and a JCS address can coexist during migration instead of silently colliding.
STRUCTURAL_ALGO = "cbor-det-sha256"


def _head(major: int, n: int, out: List[bytes]) -> None:
    """CBOR head: major type + shortest-form length/value (RFC 8949 §4.2.1 requires shortest)."""
    mt = major << 5
    if n >= 0x10000000000000000:
        # A head cannot express 2^64 or more. This used to fall through to `struct.pack(">Q")` and
        # raise an opaque `struct.error`, while the JS counterpart SILENTLY TRUNCATED the value to its
        # low 64 bits — the same input, two addresses, nothing raised on either side. Integers this
        # large now take the bignum path in `_emit_number` and never reach here; a length this large
        # is not a real document. Explicit so the failure can never be silent again.
        raise Unaddressable(
            "value %d does not fit a CBOR head (>= 2^64); integers use the bignum path, and a "
            "string/array/map length this large is not addressable" % n)
    if n < 24:
        out.append(bytes([mt | n]))
    elif n < 0x100:
        out.append(bytes([mt | 24, n]))
    elif n < 0x10000:
        out.append(bytes([mt | 25]) + struct.pack(">H", n))
    elif n < 0x100000000:
        out.append(bytes([mt | 26]) + struct.pack(">I", n))
    else:
        out.append(bytes([mt | 27]) + struct.pack(">Q", n))


def _emit(obj: Any, out: List[bytes]) -> None:
    if obj is None:
        out.append(b"\xf6")                                   # null
    elif obj is True:
        out.append(b"\xf5")
    elif obj is False:
        out.append(b"\xf4")
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        _emit_number(obj, out)
    elif isinstance(obj, str):
        b = obj.encode("utf-8")                               # length-prefixed: no escaping question
        _head(3, len(b), out)
        out.append(b)
    elif isinstance(obj, (bytes, bytearray)):
        _head(2, len(obj), out)
        out.append(bytes(obj))
    elif isinstance(obj, (list, tuple)):
        _head(4, len(obj), out)
        for v in obj:
            _emit(v, out)
    elif isinstance(obj, dict):
        # Keys sort by their ENCODED BYTES — one total order, identical in every language. No
        # code-point-vs-code-unit question can arise.
        items = []
        for k, v in obj.items():
            if not isinstance(k, str):
                # Was `str(k)`. That coercion made key `1.0` and key `"1.0"` the SAME encoded key, so
                # `{1.0: "x", "1.0": "y"}` emitted a duplicate-key map (invalid for deterministic CBOR,
                # RFC 8949 §5.6) whose address depended on which key Python's stable sort happened to
                # place first — i.e. on insertion order. Two dicts equal as data, two addresses. A
                # non-string key also cannot exist in JSON or in a JS object, so no other SDK could
                # ever verify such an address.
                raise Unaddressable(
                    "dict keys must be str for a structural address; got %s key %r. JSON objects and "
                    "JS objects have string keys only, so a non-string key is unverifiable by another "
                    "SDK — convert it explicitly and decide what it should mean."
                    % (type(k).__name__, k))
            kb: List[bytes] = []
            _emit(k, kb)
            items.append((b"".join(kb), v))
        items.sort(key=lambda kv: kv[0])
        _head(5, len(items), out)
        for kb, v in items:
            out.append(kb)
            _emit(v, out)
    else:
        # Was `str(obj)`, an implicit `default=str`. For a `set` that is catastrophic and invisible:
        # `str({1, "a"})` orders by hash, so PYTHONHASHSEED changes the address of the same set between
        # processes — a content address that is not a function of the content. `datetime`, `Decimal`,
        # numpy scalars and every custom object were addressed by their repr, which is a rendering
        # decision the caller never made. Refuse and name the type.
        raise Unaddressable(
            "%s has no structural encoding; supported: dict (str keys), list/tuple, str, bytes, int, "
            "float, bool, None. Serialize it to one of those yourself, so the choice of representation "
            "is explicit and recorded rather than inferred from repr()." % type(obj).__name__)


def _emit_number(x: Any, out: List[bytes]) -> None:
    """Integral -> CBOR integer (exact, unbounded). Non-integral -> float64.

    The integral rule is the ONE normalization: JavaScript cannot tell 1 from 1.0, so both sides must
    agree to treat an integral value as an integer. Everything else is exact.
    """
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise ValueError("non-finite numbers have no content address: %r" % (x,))
        if x.is_integer():
            x = int(x)                                        # 1.0 and 1 address identically
    if isinstance(x, int):
        # Major 0/1 whenever the value FITS in 64 bits, bignum only beyond. That split is required, not
        # stylistic: allowing a bignum for a small value would give one integer two valid encodings and
        # therefore two addresses, which is precisely the non-determinism this encoder exists to remove.
        if 0 <= x < 0x10000000000000000:
            _head(0, x, out)
        elif -0x10000000000000000 <= x < 0:
            _head(1, -1 - x, out)                             # CBOR negative int: -1-n
        else:
            _emit_bignum(x, out)
        return
    out.append(b"\xfb" + struct.pack(">d", float(x)))         # float64, deterministic


def _emit_bignum(x: int, out: List[bytes]) -> None:
    """Integers beyond 64 bits — CBOR bignum, RFC 8949 §3.4.3. Tag 2 positive, tag 3 negative.

    This is what makes the module docstring's "exact, unbounded" claim TRUE. Before, Python raised an
    opaque `struct.error` here while the JS counterpart silently truncated to 64 bits, so the two SDKs
    disagreed about the same integer with neither one complaining — the exact failure mode that
    motivated leaving JCS, reappearing one layer down.

    The magnitude carries NO leading zero bytes: a leading zero would be a second encoding of the same
    number. Negative values encode the magnitude of `-1 - x`, mirroring major type 1.
    """
    if x >= 0:
        tag, mag = 2, x
    else:
        tag, mag = 3, -1 - x
    n = mag.bit_length()
    raw = mag.to_bytes((n + 7) // 8 or 1, "big")               # `or 1`: mag==0 still needs one byte
    raw = raw.lstrip(b"\x00") or b"\x00"                       # shortest magnitude, no leading zeros
    out.append(bytes([(6 << 5) | tag]))                        # tag head (2 and 3 are < 24)
    _head(2, len(raw), out)                                    # byte string
    out.append(raw)


def structural_encode(obj: Any) -> bytes:
    """Deterministic CBOR bytes for `obj` — the structure itself, in no particular text rendering."""
    out: List[bytes] = []
    _emit(obj, out)
    return b"".join(out)


def structural_sha(obj: Any) -> str:
    """The structural content address. Pair it with `STRUCTURAL_ALGO` — never store a bare digest."""
    return hashlib.sha256(structural_encode(obj)).hexdigest()
