# The canonical source of record for JCS, and the only copy of it. Every consumer imports it from
# here rather than vendoring it: this package's base install is dependency-free, so importing it
# costs nothing that a copy would avoid, and two copies of the function that decides every content
# address agree only for as long as someone keeps them in step.
"""RFC 8785 (JCS) canonical JSON — the one serialization a content address is taken over.

Two hosts agree on a sha only if they agree on three independent things, and JCS pins all three:

  1. strings   raw UTF-8; no `\\uXXXX` escaping of non-ASCII.
  2. numbers   rendered per ECMAScript `Number::toString` — `1.0` is `1`, `-0.0` is `0`, and the
               fixed/exponential switch is at 1e21 / 1e-7. Python's `repr` disagrees on all three.
  3. keys      sorted by UTF-16 code units, not code points. They differ for astral-plane characters:
               a surrogate pair begins at 0xD800, which sorts below U+FFFD.

Stdlib-only on purpose — a bare host or an installer must be able to compute a content address
without pulling a dependency tree.
"""
from __future__ import annotations

import decimal
import json
from typing import Any, List

__all__ = ["canonical_json", "canonical_string", "jcs_number", "canonical_payload"]


def jcs_number(x: Any) -> str:
    """A number exactly as ECMAScript `Number::toString` renders it (RFC 8785 §3.2.2.3)."""
    if isinstance(x, bool):                     # bool before int — True is not 1 here
        raise TypeError("bool is not a JSON number")
    f = float(x)
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError("non-finite numbers cannot be canonicalized: %r" % (x,))
    if f == 0:
        return "0"                              # collapses -0.0 -> "0", as ECMAScript does
    if f.is_integer() and abs(f) < 1e21:
        return str(int(f))                      # 1.0 -> "1", 1e20 -> "100000000000000000000"

    d = decimal.Decimal(repr(f)).normalize()    # repr = shortest round-trip digits
    sign, digits, exp = d.as_tuple()
    s = "".join(str(t) for t in digits)
    n = len(s) + int(exp)                       # value = 0.<s> x 10^n
    neg = "-" if sign else ""
    if 0 < n <= 21:
        out = s + "0" * (n - len(s)) if n >= len(s) else s[:n] + "." + s[n:]
    elif -6 < n <= 0:
        out = "0." + "0" * (-n) + s
    else:
        mant = s[0] + ("." + s[1:] if len(s) > 1 else "")
        e = n - 1
        out = mant + "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return neg + out


def _emit(obj: Any, buf: List[str]) -> None:
    if obj is None:
        buf.append("null")
    elif obj is True:
        buf.append("true")
    elif obj is False:
        buf.append("false")
    elif isinstance(obj, str):
        buf.append(json.dumps(obj, ensure_ascii=False))
    elif isinstance(obj, (int, float, decimal.Decimal)):
        buf.append(jcs_number(obj))
    elif isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: str(kv[0]).encode("utf-16-be"))
        buf.append("{")
        for i, (k, v) in enumerate(items):
            if i:
                buf.append(",")
            buf.append(json.dumps(str(k), ensure_ascii=False))
            buf.append(":")
            _emit(v, buf)
        buf.append("}")
    elif isinstance(obj, (list, tuple)):
        buf.append("[")
        for i, v in enumerate(obj):
            if i:
                buf.append(",")
            _emit(v, buf)
        buf.append("]")
    else:
        buf.append(json.dumps(str(obj), ensure_ascii=False))   # `default=str` equivalent


def canonical_string(obj: Any) -> str:
    """The canonical form as text. Prefer `canonical_json` — a content address is over bytes."""
    buf: List[str] = []
    _emit(obj, buf)
    return "".join(buf)


def canonical_json(obj: Any) -> bytes:
    """RFC 8785 canonical JSON bytes — what a sha256 is taken over."""
    return canonical_string(obj).encode("utf-8")


def canonical_payload(content: Any) -> bytes:
    """The bytes a sha is taken over, for content of any shape.

    bytes pass through, a str is UTF-8, anything else is canonical JSON. That third case is why this
    belongs here and not beside a caller: while "what do we hash" and "how do we canonicalise" live
    in one file, they answer as one.

    There is no vendored copy of this file anywhere any more (see the module header): every site
    imports it, so "answers identically" is a property of there being one implementation rather
    than of a gate keeping two in step."""
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        return content.encode("utf-8")
    return canonical_string(content).encode("utf-8")
