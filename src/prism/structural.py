# Prototype — the structural content address ("structural permanence"). Wired into nothing. It exists
# so the lattice's content-addressing cutover can be decided against a working thing with measured
# properties rather than against an argument.
"""Deterministic CBOR (RFC 8949 §4.2) — a content address over the structure rather than a rendering.

A JSON-text content address requires three separate encoding agreements: string escaping, number→text
rendering, and key collation. RFC 8785 settles all three by pinning them to JavaScript's semantics,
which asks every non-JS SDK to emulate JavaScript. ASCII and character encoding are content features,
and an address should be agnostic to both.

In a structural encoding those three questions do not arise:

  | JSON-text question              | structural answer                                        |
  |---------------------------------|----------------------------------------------------------|
  | escape non-ASCII?               | none — a text string is a length-prefixed UTF-8 byte run |
  | how does 1.0 render?            | none — integers and floats are different major types     |
  | sort keys by code point or unit?| none — keys sort by their encoded bytes, one total order |

Precision is preserved as well: `9007199254740993` stays exact, because a CBOR integer is not a
float64. JCS requires rounding it to match JavaScript.

One normalization remains, and it is unavoidable: JavaScript represents integer 1 and float 1.0 as
the same `number`. So an integral value encodes as a CBOR integer whatever the source language's type,
and only a non-integral value encodes as a float. Without that rule Python's `1.0` and JavaScript's
`1` would address differently. It is one rule, stated once, with no per-character or per-locale
behaviour, which is the whole difference from the JSON-text situation.

Two shapes have no content address, and each raises `Unaddressable` rather than producing bytes. The
reason for going structural is that JCS gives two different artifacts one content address; an encoder
that did the same for its own edge cases would reproduce the defect it was built to remove.

  | input                         | property                                                   |
  |-------------------------------|------------------------------------------------------------|
  | `set`, `datetime`, any object | `str(obj)` is a rendering the caller never chose, and a set |
  |                               | has no stable address because its iteration order depends   |
  |                               | on PYTHONHASHSEED                                           |
  | non-`str` dict key            | `str(k)` makes key `1.0` and key `"1.0"` one encoded key,   |
  |                               | so `{1.0: "x", "1.0": "y"}` and `{"1.0": "y", 1.0: "x"}`    |
  |                               | address differently and emit a duplicate-key map, invalid   |
  |                               | for deterministic encoding under RFC 8949 §5.6              |

Keys are `str` only, which is the domain rather than a limitation: this addresses JSON-shaped
documents, and a non-string key exists neither in JSON nor in a JS object, so another SDK could not
verify such an address. Naming the boundary is what a coercion would hide.

Integers are unbounded and exact on both sides (CBOR bignum, RFC 8949 §3.4.3: tag 2 positive, tag 3
negative, magnitude as a big-endian byte string with no leading zeros). Deterministic form uses major
type 0/1 whenever the value fits in 64 bits, and a bignum only beyond, so one value has one encoding.

Stdlib-only, like `prism.canonical` — a bare host addresses content with no dependencies.
"""
from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, List

__all__ = ["structural_encode", "structural_sha", "STRUCTURAL_ALGO", "Unaddressable"]


class Unaddressable(TypeError):
    """This value has no well-defined content address, so no bytes are produced.

    A distinct type because the caller's response is to leave the document unaddressed rather than to
    retry or fall back, and because a caller enumerating what it cannot address (a migration scan,
    say) tells "unaddressable" apart from an ordinary bug by type. Subclasses `TypeError`, so an
    existing `except TypeError` handler catches it.
    """

#: The address algorithm tag. A content address carries which algorithm produced it, so a structural
#: address and a JCS address coexist during migration rather than colliding.
STRUCTURAL_ALGO = "cbor-det-sha256"


def _head(major: int, n: int, out: List[bytes]) -> None:
    """CBOR head: major type + shortest-form length/value (RFC 8949 §4.2.1 requires shortest)."""
    mt = major << 5
    if n >= 0x10000000000000000:
        # A head cannot express 2^64 or more.
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
        # Keys sort by their encoded bytes — one total order, identical in every language, so the
        # code-point-vs-code-unit question does not arise.
        items = []
        for k, v in obj.items():
            if not isinstance(k, str):
                # A `str(k)` coercion would make key `1.0` and key `"1.0"` the same encoded key, so
                # `{1.0: "x", "1.0": "y"}` would emit a duplicate-key map (invalid for deterministic
                # CBOR, RFC 8949 §5.6) whose address depends on which key Python's stable sort places
                # first — that is, on insertion order. Two dicts equal as data, two addresses. A
                # non-string key exists neither in JSON nor in a JS object, so no other SDK could
                # verify such an address.
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
        # A `str(obj)` fallback would address by repr, which is a rendering decision the caller never
        # made — for `datetime`, `Decimal`, numpy scalars and every custom object. For a `set` it is
        # worse: `str({1, "a"})` orders by hash, so PYTHONHASHSEED changes the address of the same
        # set between processes, giving a content address that is not a function of the content. The
        # type is named instead.
        raise Unaddressable(
            "%s has no structural encoding; supported: dict (str keys), list/tuple, str, bytes, int, "
            "float, bool, None. Serialize it to one of those yourself, so the choice of representation "
            "is explicit and recorded rather than inferred from repr()." % type(obj).__name__)


def _emit_number(x: Any, out: List[bytes]) -> None:
    """Integral -> CBOR integer (exact, unbounded). Non-integral -> float64.

    The integral rule is the one normalization: JavaScript represents 1 and 1.0 identically, so both
    sides treat an integral value as an integer. Everything else is exact.
    """
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            raise ValueError("non-finite numbers have no content address: %r" % (x,))
        if x.is_integer():
            x = int(x)                                        # 1.0 and 1 address identically
    if isinstance(x, int):
        # Major 0/1 whenever the value fits in 64 bits, bignum only beyond. The split is required by
        # determinism: allowing a bignum for a small value would give one integer two valid encodings
        # and therefore two addresses.
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

    This is what makes "exact, unbounded" true of the encoder. A 64-bit path alone would either raise
    an opaque `struct.error` in Python or truncate in a JS counterpart, leaving two SDKs holding
    different addresses for the same integer.

    The magnitude carries no leading zero bytes, since a leading zero would be a second encoding of
    the same number. Negative values encode the magnitude of `-1 - x`, mirroring major type 1.
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
    """The structural content address. Store it paired with `STRUCTURAL_ALGO`, so the digest carries
    the algorithm that produced it."""
    return hashlib.sha256(structural_encode(obj)).hexdigest()
